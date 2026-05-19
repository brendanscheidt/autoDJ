"""Timing candidate benchmark runner against Rekordbox XML ground truth."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import platform
from pathlib import Path
import re
from typing import Any

from .. import __version__
from ..audio_io import DecodedAudio, load_audio
from ..backends import (
    ALL_IN_ONE_BACKEND,
    BEAT_THIS_BACKEND,
    CURRENT_SIGNAL_BACKEND,
    ESSENTIA_RHYTHM_BACKEND,
    AnalysisContext,
    BackendExecutionError,
    BackendRegistry,
    BeatGridBackend,
    BeatGridCandidateResult,
    CandidateProvenance,
    TempoCandidate,
    TempoCandidateResult,
    register_all_in_one_backends,
    register_beat_this_backends,
    register_current_signal_backends,
    register_essentia_rhythm_backends,
)
from ..cache import SCHEMA_VERSION, write_json_atomic
from ..debug_waveform import build_debug_waveform_artifact
from ..dependencies import require_optional_dependency
from ..rekordbox_xml import RekordboxXmlError, load_rekordbox_track
from ..tempo import normalize_dubstep_bpm
from .rekordbox import RekordboxEvaluationOptions, evaluate_analyzed_artifact_against_rekordbox


TIMING_BENCHMARK_REPORT_TYPE = "timing-candidate-benchmark"
TIMING_BENCHMARK_PARAMETERS_HASH = "sha256:timing-candidate-benchmark-v1"
DEFAULT_TIMING_CANDIDATES = (
    CURRENT_SIGNAL_BACKEND,
    ESSENTIA_RHYTHM_BACKEND,
    BEAT_THIS_BACKEND,
    ALL_IN_ONE_BACKEND,
)
DEFAULT_TIMING_ANALYSIS_SAMPLE_RATE = 44_100
DEFAULT_TIMING_DEBUG_WAVEFORM_POINTS = 32_768


class TimingBenchmarkError(ValueError):
    """Expected timing benchmark failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class TimingBenchmarkCase:
    track_id: str
    audio_path: Path
    rekordbox_xml_path: Path
    track_name: str | None = None

    def __post_init__(self) -> None:
        if not self.track_id:
            raise TimingBenchmarkError("timing_benchmark_invalid_case", "track_id must not be empty")
        object.__setattr__(self, "audio_path", _coerce_local_path(self.audio_path))
        object.__setattr__(self, "rekordbox_xml_path", _coerce_local_path(self.rekordbox_xml_path))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "trackId": self.track_id,
            "audioPath": str(self.audio_path),
            "rekordboxXmlPath": str(self.rekordbox_xml_path),
        }
        if self.track_name is not None:
            payload["trackName"] = self.track_name
        return payload


AudioLoader = Callable[..., DecodedAudio]
AnalysisAudioWriter = Callable[[Path, DecodedAudio], Path]
DebugWaveformBuilder = Callable[..., dict[str, Any]]


def default_timing_backend_registry() -> BackendRegistry:
    """Return the first-wave timing candidate registry."""

    registry = BackendRegistry()
    register_current_signal_backends(registry)
    register_essentia_rhythm_backends(registry)
    register_beat_this_backends(registry)
    register_all_in_one_backends(registry)
    return registry


def load_timing_benchmark_cases(path: str | Path) -> tuple[TimingBenchmarkCase, ...]:
    """Load benchmark cases from a JSON file."""

    payload = _load_json_object(path)
    raw_cases = payload.get("cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise TimingBenchmarkError(
            "timing_benchmark_invalid_cases",
            "Benchmark cases file must contain a list or a {'cases': [...]} object.",
        )
    cases: list[TimingBenchmarkCase] = []
    for index, item in enumerate(raw_cases):
        if not isinstance(item, dict):
            raise TimingBenchmarkError(
                "timing_benchmark_invalid_case",
                f"Benchmark case at index {index} must be an object.",
            )
        try:
            cases.append(
                TimingBenchmarkCase(
                    track_id=str(item["trackId"]),
                    audio_path=Path(str(item["audioPath"])),
                    rekordbox_xml_path=Path(str(item["rekordboxXmlPath"])),
                    track_name=str(item["trackName"]) if item.get("trackName") else None,
                )
            )
        except KeyError as exc:
            raise TimingBenchmarkError(
                "timing_benchmark_invalid_case",
                f"Benchmark case at index {index} is missing required field: {exc.args[0]}",
            ) from exc
    return tuple(cases)


def run_timing_benchmark(
    cases: Sequence[TimingBenchmarkCase],
    output_root: str | Path,
    *,
    candidates: Sequence[str] = DEFAULT_TIMING_CANDIDATES,
    registry: BackendRegistry | None = None,
    audio_loader: AudioLoader = load_audio,
    analysis_audio_writer: AnalysisAudioWriter | None = None,
    debug_waveform_builder: DebugWaveformBuilder = build_debug_waveform_artifact,
    analysis_sample_rate: int = DEFAULT_TIMING_ANALYSIS_SAMPLE_RATE,
    debug_waveform_points: int = DEFAULT_TIMING_DEBUG_WAVEFORM_POINTS,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    """Run timing candidates and write viewer/evaluation artifacts."""

    if not cases:
        raise TimingBenchmarkError("timing_benchmark_no_cases", "At least one benchmark case is required.")
    if not candidates:
        raise TimingBenchmarkError("timing_benchmark_no_candidates", "At least one candidate is required.")
    if analysis_sample_rate <= 0:
        raise TimingBenchmarkError(
            "timing_benchmark_invalid_sample_rate",
            "analysis_sample_rate must be greater than zero.",
        )
    if debug_waveform_points <= 0:
        raise TimingBenchmarkError(
            "timing_benchmark_invalid_debug_points",
            "debug_waveform_points must be greater than zero.",
        )

    registry = registry or default_timing_backend_registry()
    writer = analysis_audio_writer or write_analysis_audio_wav
    output_root_path = Path(output_root)
    created = created_at_utc or _utc_now_iso()
    output_root_path.mkdir(parents=True, exist_ok=True)

    case_results = [
        _run_case(
            case,
            output_root_path,
            candidates=tuple(candidates),
            registry=registry,
            audio_loader=audio_loader,
            analysis_audio_writer=writer,
            debug_waveform_builder=debug_waveform_builder,
            analysis_sample_rate=analysis_sample_rate,
            debug_waveform_points=debug_waveform_points,
            created_at_utc=created,
        )
        for case in cases
    ]
    summary = {
        "schemaVersion": SCHEMA_VERSION,
        "reportType": TIMING_BENCHMARK_REPORT_TYPE,
        "createdAtUtc": created,
        "outputRoot": str(output_root_path),
        "parameters": {
            "candidates": list(candidates),
            "analysisSampleRate": analysis_sample_rate,
            "debugWaveformPoints": debug_waveform_points,
            "timelineOffsetPolicy": "shared-decoded-wav",
        },
        "cases": case_results,
        "candidateSummary": _candidate_summary(case_results, candidates),
    }
    write_json_atomic(output_root_path / "timing-benchmark-summary.json", summary)
    return summary


def write_analysis_audio_wav(path: Path, audio: DecodedAudio) -> Path:
    """Write decoded mono analysis audio to WAV for file-based candidates."""

    soundfile = require_optional_dependency("soundfile", module_name="soundfile", install_extra="analysis")
    path.parent.mkdir(parents=True, exist_ok=True)
    soundfile.write(str(path), audio.samples, int(audio.sample_rate))
    return path


def _run_case(
    case: TimingBenchmarkCase,
    output_root: Path,
    *,
    candidates: tuple[str, ...],
    registry: BackendRegistry,
    audio_loader: AudioLoader,
    analysis_audio_writer: AnalysisAudioWriter,
    debug_waveform_builder: DebugWaveformBuilder,
    analysis_sample_rate: int,
    debug_waveform_points: int,
    created_at_utc: str,
) -> dict[str, Any]:
    case_dir = output_root / _safe_path_name(case.track_id)
    case_dir.mkdir(parents=True, exist_ok=True)
    audio = audio_loader(case.audio_path, target_sample_rate=analysis_sample_rate)
    analysis_audio_path = analysis_audio_writer(case_dir / "analysis.wav", audio)
    context = AnalysisContext(
        track_id=case.track_id,
        source_path=case.audio_path,
        analysis_audio_path=analysis_audio_path,
        duration_seconds=audio.duration_seconds,
        temp_dir=case_dir / "candidate-work",
    )
    debug_artifact = debug_waveform_builder(
        case.track_id,
        audio,
        analyzer_producer="autodj_analysis.timing_benchmark",
        analyzer_version=__version__,
        created_at_utc=created_at_utc,
        target_point_count=debug_waveform_points,
    )
    write_json_atomic(case_dir / "debug-waveform.json", debug_artifact)

    try:
        rekordbox_track = load_rekordbox_track(case.rekordbox_xml_path, track_name=case.track_name)
    except RekordboxXmlError as exc:
        raise TimingBenchmarkError(exc.code, exc.message) from exc

    candidate_results = [
        _run_candidate(
            candidate,
            case,
            case_dir,
            audio,
            context,
            rekordbox_track,
            registry=registry,
            debug_artifact=debug_artifact,
            created_at_utc=created_at_utc,
        )
        for candidate in candidates
    ]
    return {
        "trackId": case.track_id,
        "audioPath": str(case.audio_path),
        "rekordboxXmlPath": str(case.rekordbox_xml_path),
        "caseDir": str(case_dir),
        "durationSeconds": _round_float(audio.duration_seconds),
        "debugWaveformPath": str(case_dir / "debug-waveform.json"),
        "candidates": candidate_results,
    }


def _run_candidate(
    candidate: str,
    case: TimingBenchmarkCase,
    case_dir: Path,
    audio: DecodedAudio,
    context: AnalysisContext,
    rekordbox_track: Any,
    *,
    registry: BackendRegistry,
    debug_artifact: dict[str, Any],
    created_at_utc: str,
) -> dict[str, Any]:
    candidate_dir = case_dir / _safe_path_name(candidate)
    candidate_dir.mkdir(parents=True, exist_ok=True)
    tempo_result, beat_grid_result = _execute_timing_candidate(candidate, audio, context, registry=registry)
    artifact = _candidate_artifact(
        candidate,
        case,
        audio,
        tempo_result,
        beat_grid_result,
        created_at_utc=created_at_utc,
    )
    analyzed_path = write_json_atomic(candidate_dir / "analyzed-track.json", artifact)
    write_json_atomic(candidate_dir / "debug-waveform.json", debug_artifact)

    status = _combined_status(tempo_result, beat_grid_result)
    processing_seconds = _round_float(
        tempo_result.provenance.processing_seconds + beat_grid_result.provenance.processing_seconds
    )
    report = evaluate_analyzed_artifact_against_rekordbox(
        artifact,
        rekordbox_track,
        options=RekordboxEvaluationOptions(
            candidate_name=candidate,
            candidate_status=status,
            processing_seconds=processing_seconds,
            timeline_offset_seconds=0.0,
            timeline_offset_policy="shared-decoded-wav",
        ),
    )
    report_path = write_json_atomic(candidate_dir / "rekordbox-evaluation.json", report)
    metrics = report["metrics"]
    return {
        "candidate": candidate,
        "status": status,
        "analyzedTrackPath": str(analyzed_path),
        "debugWaveformPath": str(candidate_dir / "debug-waveform.json"),
        "rekordboxEvaluationPath": str(report_path),
        "processingSeconds": processing_seconds,
        "bpm": artifact["tempo"].get("bpm"),
        "normalizedBpm": artifact["tempo"].get("normalizedBpm"),
        "beatCount": len(artifact["beatGrid"]["beats"]),
        "downbeatCount": len(artifact["beatGrid"]["downbeats"]),
        "bpmAbsoluteError": metrics["tempo"]["bpmAbsoluteError"],
        "normalizedBpmAbsoluteError": metrics["tempo"]["normalizedBpmAbsoluteError"],
        "firstBeatOffsetMilliseconds": metrics["beatGrid"]["firstBeatOffsetMilliseconds"],
        "medianAbsoluteErrorMilliseconds": metrics["beatGrid"]["medianAbsoluteErrorMilliseconds"],
        "p95AbsoluteErrorMilliseconds": metrics["beatGrid"]["p95AbsoluteErrorMilliseconds"],
        "maxAbsoluteErrorMilliseconds": metrics["beatGrid"]["maxAbsoluteErrorMilliseconds"],
        "beatCoverageRatio": metrics["beatGrid"].get("beatCoverageRatio"),
        "referenceRecallWithin25Milliseconds": metrics["beatGrid"].get("referenceRecallWithin25Milliseconds"),
        "referenceRecallWithin50Milliseconds": metrics["beatGrid"].get("referenceRecallWithin50Milliseconds"),
        "candidatePrecisionWithin25Milliseconds": metrics["beatGrid"].get("candidatePrecisionWithin25Milliseconds"),
        "candidatePrecisionWithin50Milliseconds": metrics["beatGrid"].get("candidatePrecisionWithin50Milliseconds"),
        "cueAdjacentDrift": metrics["cueAdjacentDrift"],
        "tempoProvenance": tempo_result.provenance.to_dict(),
        "beatGridProvenance": beat_grid_result.provenance.to_dict(),
        "error": _combined_error(tempo_result, beat_grid_result),
    }


def _execute_timing_candidate(
    candidate: str,
    audio: DecodedAudio,
    context: AnalysisContext,
    *,
    registry: BackendRegistry,
) -> tuple[TempoCandidateResult, BeatGridCandidateResult]:
    tempo_backend = None
    beat_grid_backend = None
    if candidate in registry.tempo_names():
        tempo_backend = registry.create_tempo(candidate)
    if tempo_backend is not None and isinstance(tempo_backend, BeatGridBackend):
        beat_grid_backend = tempo_backend
    elif candidate in registry.beat_grid_names():
        beat_grid_backend = registry.create_beat_grid(candidate)

    if beat_grid_backend is None:
        tempo_result = _missing_tempo_result(candidate, "No beat-grid backend is registered for this candidate.")
        return tempo_result, _missing_beat_grid_result(candidate, "No beat-grid backend is registered for this candidate.")

    if tempo_backend is not None:
        tempo_result = tempo_backend.analyze_tempo(audio, context)
        beat_grid_result = beat_grid_backend.analyze_beat_grid(audio, tempo_result, context)
        return tempo_result, beat_grid_result

    placeholder_tempo = _placeholder_tempo(candidate)
    beat_grid_result = beat_grid_backend.analyze_beat_grid(audio, placeholder_tempo, context)
    tempo_result = _derive_tempo_from_beat_grid(candidate, beat_grid_result)
    return tempo_result, beat_grid_result


def _candidate_artifact(
    candidate: str,
    case: TimingBenchmarkCase,
    audio: DecodedAudio,
    tempo_result: TempoCandidateResult,
    beat_grid_result: BeatGridCandidateResult,
    *,
    created_at_utc: str,
) -> dict[str, Any]:
    warnings = _warnings(tempo_result) + _warnings(beat_grid_result)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "trackId": case.track_id,
        "source": {
            "trackId": case.track_id,
            "repositoryId": "timing-benchmark",
            "sourceUri": str(case.audio_path),
            "durationSeconds": _round_float(audio.duration_seconds),
            "title": case.audio_path.stem,
            "sampleRate": int(audio.sample_rate),
            "channels": audio.channels,
            "providerMetadata": {
                "benchmarkAudioPath": str(case.audio_path),
                "rekordboxXmlPath": str(case.rekordbox_xml_path),
            },
        },
        "analyzer": {
            "producer": candidate,
            "producerVersion": __version__,
            "createdAtUtc": created_at_utc,
            "parametersHash": TIMING_BENCHMARK_PARAMETERS_HASH,
            "candidate": {
                "tempo": tempo_result.to_dict(),
                "beatGrid": beat_grid_result.to_dict(),
            },
        },
        "durationSeconds": _round_float(audio.duration_seconds),
        "tempo": _tempo_artifact(tempo_result),
        "key": {
            "tonic": "unknown",
            "mode": "unknown",
            "confidence": 0.0,
            "candidates": [],
        },
        "beatGrid": _beat_grid_artifact(beat_grid_result),
        "sections": [],
        "energy": {
            "globalEnergy": 0.0,
            "curve": [],
            "bassEnergyCurve": [],
            "onsetDensityCurve": [],
        },
        "vocals": {
            "hasVocals": False,
            "confidence": 0.0,
            "regions": [],
        },
        "cuePoints": [],
        "quality": {
            "overallConfidence": _overall_confidence(tempo_result, beat_grid_result),
            "warnings": warnings,
        },
    }


def _tempo_artifact(result: TempoCandidateResult) -> dict[str, Any]:
    payload = result.to_dict()
    payload.setdefault("bpm", result.bpm if result.bpm is not None else 0.0)
    payload.setdefault("normalizedBpm", result.normalized_bpm if result.normalized_bpm is not None else 0.0)
    payload.setdefault("confidence", result.confidence)
    payload.setdefault("tempoClass", result.tempo_class or "unknown")
    payload.setdefault("candidates", [candidate.to_dict() for candidate in result.candidates])
    return payload


def _beat_grid_artifact(result: BeatGridCandidateResult) -> dict[str, Any]:
    payload = result.to_dict()
    payload.setdefault("beats", [beat.to_dict() for beat in result.beats])
    payload.setdefault("downbeats", [downbeat.to_dict() for downbeat in result.downbeats])
    payload.setdefault("confidence", result.confidence)
    return payload


def _derive_tempo_from_beat_grid(candidate: str, beat_grid: BeatGridCandidateResult) -> TempoCandidateResult:
    if not beat_grid.ok or len(beat_grid.beats) < 2:
        return TempoCandidateResult(
            status="failed",
            provenance=CandidateProvenance(
                backend_name=f"{candidate}-derived-tempo",
                backend_version=__version__,
                model_name="beat-interval-derived-bpm",
                processing_seconds=0.0,
                parameters={"sourceBeatGridStatus": beat_grid.status},
                warnings=("Tempo was derived from beat intervals because the candidate does not emit BPM directly.",),
            ),
            error=BackendExecutionError(
                code="derived_tempo_insufficient_beats",
                message="At least two beat markers are required to derive BPM.",
                backend_name=f"{candidate}-derived-tempo",
            ),
        )

    intervals = [
        later.time_seconds - earlier.time_seconds
        for earlier, later in zip(beat_grid.beats, beat_grid.beats[1:])
        if later.time_seconds > earlier.time_seconds
    ]
    if not intervals:
        return TempoCandidateResult(
            status="failed",
            provenance=CandidateProvenance(
                backend_name=f"{candidate}-derived-tempo",
                backend_version=__version__,
                model_name="beat-interval-derived-bpm",
                parameters={"sourceBeatGridStatus": beat_grid.status},
                warnings=("Tempo was derived from beat intervals because the candidate does not emit BPM directly.",),
            ),
            error=BackendExecutionError(
                code="derived_tempo_invalid_intervals",
                message="Beat markers did not contain positive intervals.",
                backend_name=f"{candidate}-derived-tempo",
            ),
        )
    median_interval = _median(intervals)
    bpm = 60.0 / median_interval
    normalized = normalize_dubstep_bpm(bpm)
    confidence = min(beat_grid.confidence, _regularity_confidence(intervals))
    return TempoCandidateResult(
        status="ok",
        provenance=CandidateProvenance(
            backend_name=f"{candidate}-derived-tempo",
            backend_version=__version__,
            model_name="beat-interval-derived-bpm",
            processing_seconds=0.0,
            parameters={
                "sourceBeatGridBackend": candidate,
                "sourceBeatCount": len(beat_grid.beats),
                "medianBeatIntervalSeconds": _round_float(median_interval),
            },
            warnings=("Tempo was derived from beat intervals because the candidate does not emit BPM directly.",),
        ),
        bpm=_round_float(bpm),
        normalized_bpm=normalized.normalized_bpm,
        confidence=_round_float(confidence),
        tempo_class=normalized.tempo_class,
        candidates=(
            TempoCandidate(
                bpm=_round_float(bpm),
                confidence=_round_float(confidence),
                backend=f"{candidate}-derived-tempo",
            ),
        ),
    )


def _placeholder_tempo(candidate: str) -> TempoCandidateResult:
    return TempoCandidateResult(
        status="ok",
        provenance=CandidateProvenance(
            backend_name=f"{candidate}-placeholder-tempo",
            backend_version=__version__,
            model_name="placeholder-for-beat-only-backend",
            parameters={"reason": "beat-only backend API accepts but does not consume tempo"},
        ),
        bpm=140.0,
        normalized_bpm=140.0,
        confidence=0.0,
        tempo_class="straight",
        candidates=(),
    )


def _missing_tempo_result(candidate: str, message: str) -> TempoCandidateResult:
    return TempoCandidateResult(
        status="failed",
        provenance=CandidateProvenance(backend_name=candidate, backend_version=__version__),
        error=BackendExecutionError(code="timing_candidate_not_registered", message=message, backend_name=candidate),
    )


def _missing_beat_grid_result(candidate: str, message: str) -> BeatGridCandidateResult:
    return BeatGridCandidateResult(
        status="failed",
        provenance=CandidateProvenance(backend_name=candidate, backend_version=__version__),
        error=BackendExecutionError(code="timing_candidate_not_registered", message=message, backend_name=candidate),
    )


def _combined_status(tempo: TempoCandidateResult, beat_grid: BeatGridCandidateResult) -> str:
    if tempo.ok and beat_grid.ok:
        return "ok"
    if tempo.status == "unavailable" or beat_grid.status == "unavailable":
        return "unavailable"
    return "failed"


def _combined_error(tempo: TempoCandidateResult, beat_grid: BeatGridCandidateResult) -> dict[str, Any] | None:
    errors = []
    if tempo.error is not None:
        errors.append({"kind": "tempo", **tempo.error.to_dict()})
    if beat_grid.error is not None:
        errors.append({"kind": "beatGrid", **beat_grid.error.to_dict()})
    if not errors:
        return None
    return {"errors": errors}


def _warnings(*results: Any) -> list[str]:
    warnings: list[str] = []
    for result in results:
        warnings.extend(result.provenance.warnings)
        if result.error is not None:
            warnings.append(f"{result.error.code}: {result.error.message}")
    return warnings


def _overall_confidence(tempo: TempoCandidateResult, beat_grid: BeatGridCandidateResult) -> float:
    values = []
    if tempo.ok:
        values.append(tempo.confidence)
    if beat_grid.ok:
        values.append(beat_grid.confidence)
    if not values:
        return 0.0
    return _round_float(sum(values) / len(values))


def _candidate_summary(case_results: list[dict[str, Any]], candidates: Sequence[str]) -> list[dict[str, Any]]:
    summaries = []
    for candidate in candidates:
        rows = [
            candidate_result
            for case_result in case_results
            for candidate_result in case_result["candidates"]
            if candidate_result["candidate"] == candidate
        ]
        summaries.append(
            {
                "candidate": candidate,
                "ok": sum(row["status"] == "ok" for row in rows),
                "failed": sum(row["status"] == "failed" for row in rows),
                "unavailable": sum(row["status"] == "unavailable" for row in rows),
                "medianAbsoluteErrorMilliseconds": _round_optional(
                    _median_optional([row["medianAbsoluteErrorMilliseconds"] for row in rows])
                ),
                "p95AbsoluteErrorMilliseconds": _round_optional(
                    _median_optional([row["p95AbsoluteErrorMilliseconds"] for row in rows])
                ),
                "bpmAbsoluteError": _round_optional(_median_optional([row["bpmAbsoluteError"] for row in rows])),
                "beatCoverageRatio": _round_optional(_median_optional([row["beatCoverageRatio"] for row in rows])),
                "referenceRecallWithin25Milliseconds": _round_optional(
                    _median_optional([row["referenceRecallWithin25Milliseconds"] for row in rows])
                ),
                "referenceRecallWithin50Milliseconds": _round_optional(
                    _median_optional([row["referenceRecallWithin50Milliseconds"] for row in rows])
                ),
                "processingSeconds": _round_float(sum(float(row["processingSeconds"]) for row in rows)),
            }
        )
    return summaries


def _load_json_object(path: str | Path) -> Any:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise TimingBenchmarkError("timing_benchmark_cases_read_error", f"Could not read benchmark cases: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise TimingBenchmarkError("timing_benchmark_cases_parse_error", f"Could not parse benchmark cases JSON: {exc}") from exc
    if not isinstance(payload, (dict, list)):
        raise TimingBenchmarkError("timing_benchmark_invalid_cases", "Benchmark cases root must be an object or list.")
    return payload


def _coerce_local_path(path: str | Path) -> Path:
    raw = str(path)
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", raw)
    if match and platform.system() != "Windows":
        drive = match.group(1).lower()
        remainder = match.group(2).replace("\\", "/")
        return Path(f"/mnt/{drive}/{remainder}")
    return Path(path)


def _safe_path_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return safe.strip(".-") or "candidate"


def _median(values: Sequence[float]) -> float:
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _median_optional(values: Sequence[Any]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return _median(numbers)


def _regularity_confidence(intervals: Sequence[float]) -> float:
    if not intervals:
        return 0.0
    median = _median(intervals)
    if median <= 0:
        return 0.0
    errors = [abs(interval - median) for interval in intervals]
    median_error = _median(errors)
    return max(0.0, min(1.0, 1.0 - median_error / (median * 0.10)))


def _round_optional(value: float | None) -> float | None:
    return None if value is None else _round_float(value)


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
