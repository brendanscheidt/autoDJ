"""Key benchmark truth loading, candidate execution, and scoring helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import platform
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urlparse

from . import __version__
from .audio_io import DecodedAudio, load_audio
from .backends import (
    AUTODJ_CHROMA_KEY_BACKEND,
    ESSENTIA_KEY_BACKEND,
    KEYFINDER_KEY_BACKEND,
    MADMOM_KEY_BACKEND,
    SELECTED_KEY_BACKEND,
    AnalysisContext,
    BackendExecutionError,
    BackendRegistry,
    CandidateProvenance,
    KeyCandidateResult,
    KeyDetectorBackend,
    register_chroma_key_backends,
    register_essentia_key_backends,
    register_keyfinder_key_backends,
    register_madmom_key_backends,
    register_selected_key_backends,
)
from .cache import SCHEMA_VERSION, write_json_atomic
from .key_camelot import CamelotKey, CamelotKeyError, classify_camelot_compatibility, parse_camelot
from .rekordbox_xml import RekordboxTrack, load_rekordbox_tracks


KEY_BENCHMARK_REPORT_TYPE = "key-candidate-benchmark"
DEFAULT_KEY_CANDIDATES = (
    AUTODJ_CHROMA_KEY_BACKEND,
    ESSENTIA_KEY_BACKEND,
    MADMOM_KEY_BACKEND,
    KEYFINDER_KEY_BACKEND,
    SELECTED_KEY_BACKEND,
)
DEFAULT_KEY_ANALYSIS_SAMPLE_RATE = 44_100

AudioLoader = Callable[..., DecodedAudio]


class KeyBenchmarkError(ValueError):
    """Expected key benchmark failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class RekordboxKeyTruthRow:
    track_name: str
    location: str
    average_bpm: float | None
    camelot: CamelotKey | None
    status: str
    warnings: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trackName": self.track_name,
            "location": self.location,
            "averageBpm": self.average_bpm,
            "truth": self.camelot.to_dict() if self.camelot is not None else None,
            "status": self.status,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class RekordboxKeyTruthTable:
    rekordbox_xml_path: str
    rows: tuple[RekordboxKeyTruthRow, ...]

    @property
    def scored_count(self) -> int:
        return sum(1 for row in self.rows if row.camelot is not None)

    @property
    def unscored_count(self) -> int:
        return len(self.rows) - self.scored_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "1.0.0",
            "reportType": "rekordbox-key-truth-table",
            "rekordboxXmlPath": self.rekordbox_xml_path,
            "totalTracks": len(self.rows),
            "scoredTracks": self.scored_count,
            "unscoredTracks": self.unscored_count,
            "tracks": [row.to_dict() for row in self.rows],
        }


def load_rekordbox_key_truth(xml_path: str | Path) -> RekordboxKeyTruthTable:
    """Load Rekordbox Tonality labels as benchmark truth only."""

    path = Path(xml_path)
    rows = tuple(_truth_row_from_track(track) for track in load_rekordbox_tracks(path))
    return RekordboxKeyTruthTable(rekordbox_xml_path=str(path), rows=rows)


@dataclass(frozen=True)
class KeyBenchmarkCase:
    track_id: str
    track_name: str
    audio_path: Path
    rekordbox_track: RekordboxTrack
    truth: RekordboxKeyTruthRow

    def to_dict(self) -> dict[str, Any]:
        return {
            "trackId": self.track_id,
            "trackName": self.track_name,
            "audioPath": str(self.audio_path),
            "truth": self.truth.to_dict(),
        }


def default_key_backend_registry() -> BackendRegistry:
    """Return the key detector candidate registry."""

    registry = BackendRegistry()
    register_chroma_key_backends(registry)
    register_essentia_key_backends(registry)
    register_madmom_key_backends(registry)
    register_keyfinder_key_backends(registry)
    register_selected_key_backends(registry)
    return registry


def load_key_benchmark_cases(xml_path: str | Path) -> tuple[KeyBenchmarkCase, ...]:
    """Create key benchmark cases from every TRACK in a Rekordbox XML export."""

    tracks = load_rekordbox_tracks(xml_path)
    cases: list[KeyBenchmarkCase] = []
    for track in tracks:
        audio_path = _coerce_local_path(_path_from_rekordbox_location(track.location))
        cases.append(
            KeyBenchmarkCase(
                track_id=_safe_path_name(Path(audio_path).stem or track.name or "track"),
                track_name=track.name,
                audio_path=audio_path,
                rekordbox_track=track,
                truth=_truth_row_from_track(track),
            )
        )
    return tuple(cases)


def run_key_benchmark(
    cases: Sequence[KeyBenchmarkCase],
    output_root: str | Path,
    *,
    candidates: Sequence[str] = DEFAULT_KEY_CANDIDATES,
    registry: BackendRegistry | None = None,
    audio_loader: AudioLoader = load_audio,
    analysis_sample_rate: int = DEFAULT_KEY_ANALYSIS_SAMPLE_RATE,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    """Run key candidates and compare them to Rekordbox Tonality truth."""

    if not cases:
        raise KeyBenchmarkError("key_benchmark_no_cases", "At least one key benchmark case is required.")
    if not candidates:
        raise KeyBenchmarkError("key_benchmark_no_candidates", "At least one key candidate is required.")
    if analysis_sample_rate <= 0:
        raise KeyBenchmarkError(
            "key_benchmark_invalid_sample_rate",
            "analysis_sample_rate must be greater than zero.",
        )

    registry = registry or default_key_backend_registry()
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    created = created_at_utc or _utc_now_iso()
    candidate_names = tuple(candidates)
    case_results = [
        _run_case(
            case,
            output_root_path,
            candidates=candidate_names,
            registry=registry,
            audio_loader=audio_loader,
            analysis_sample_rate=analysis_sample_rate,
        )
        for case in cases
    ]
    summary = {
        "schemaVersion": SCHEMA_VERSION,
        "reportType": KEY_BENCHMARK_REPORT_TYPE,
        "createdAtUtc": created,
        "outputRoot": str(output_root_path),
        "parameters": {
            "candidates": list(candidate_names),
            "analysisSampleRate": analysis_sample_rate,
            "referenceSource": "rekordbox-track-tonality",
            "truthUsage": "benchmark-only",
        },
        "truthSummary": {
            "totalTracks": len(cases),
            "scoredTracks": sum(case.truth.camelot is not None for case in cases),
            "unscoredTracks": sum(case.truth.camelot is None for case in cases),
        },
        "cases": case_results,
        "candidateSummary": _candidate_summary(case_results, candidate_names),
    }
    write_json_atomic(output_root_path / "key-benchmark-summary.json", summary)
    return summary


def _run_case(
    case: KeyBenchmarkCase,
    output_root: Path,
    *,
    candidates: tuple[str, ...],
    registry: BackendRegistry,
    audio_loader: AudioLoader,
    analysis_sample_rate: int,
) -> dict[str, Any]:
    case_dir = output_root / _safe_path_name(case.track_id)
    case_dir.mkdir(parents=True, exist_ok=True)
    audio = audio_loader(case.audio_path, target_sample_rate=analysis_sample_rate)
    context = AnalysisContext(
        track_id=case.track_id,
        source_path=case.audio_path,
        analysis_audio_path=case.audio_path,
        duration_seconds=audio.duration_seconds,
        temp_dir=case_dir / "candidate-work",
    )
    candidate_results = [
        _run_candidate(
            candidate,
            case,
            case_dir,
            audio,
            context,
            registry=registry,
        )
        for candidate in candidates
    ]
    return {
        "trackId": case.track_id,
        "trackName": case.track_name,
        "audioPath": str(case.audio_path),
        "caseDir": str(case_dir),
        "durationSeconds": _round_float(audio.duration_seconds),
        "truth": case.truth.to_dict(),
        "candidates": candidate_results,
    }


def _run_candidate(
    candidate: str,
    case: KeyBenchmarkCase,
    case_dir: Path,
    audio: DecodedAudio,
    context: AnalysisContext,
    *,
    registry: BackendRegistry,
) -> dict[str, Any]:
    candidate_dir = case_dir / _safe_path_name(candidate)
    candidate_dir.mkdir(parents=True, exist_ok=True)
    result = _execute_key_candidate(candidate, audio, context, registry=registry)
    result_path = write_json_atomic(candidate_dir / "key-candidate.json", result.to_dict())
    score = _score_candidate_result(case.truth, result)
    return {
        "candidate": candidate,
        "status": result.status,
        "keyCandidatePath": str(result_path),
        "processingSeconds": result.provenance.processing_seconds,
        "tonic": result.tonic,
        "mode": result.mode,
        "camelot": result.camelot,
        "confidence": result.confidence,
        "score": score,
        "provenance": result.provenance.to_dict(),
        "error": result.error.to_dict() if result.error is not None else None,
    }


def _execute_key_candidate(
    candidate: str,
    audio: DecodedAudio,
    context: AnalysisContext,
    *,
    registry: BackendRegistry,
) -> KeyCandidateResult:
    if candidate not in registry.key_names():
        return _missing_key_result(candidate, "No key backend is registered for this candidate.")
    try:
        backend = registry.create_key(candidate)
        if not isinstance(backend, KeyDetectorBackend):
            return _missing_key_result(candidate, "Registered candidate does not implement KeyDetectorBackend.")
        return backend.analyze_key(audio, context)
    except Exception as exc:
        return KeyCandidateResult(
            status="failed",
            provenance=CandidateProvenance(
                backend_name=candidate,
                backend_version=__version__,
                processing_seconds=0.0,
            ),
            error=BackendExecutionError(
                code="key_candidate_failed",
                message=str(exc),
                backend_name=candidate,
                details={"exceptionType": exc.__class__.__name__},
            ),
        )


def _score_candidate_result(
    truth: RekordboxKeyTruthRow,
    result: KeyCandidateResult,
) -> dict[str, Any]:
    if truth.camelot is None:
        return {
            "status": "unscored_truth",
            "exactCamelotMatch": None,
            "compatibility": None,
            "score": None,
        }
    if not result.ok or result.camelot is None:
        return {
            "status": "candidate_unavailable" if result.status == "unavailable" else "candidate_failed",
            "truthCamelot": truth.camelot.camelot,
            "predictedCamelot": result.camelot,
            "exactCamelotMatch": False,
            "compatibility": None,
            "score": 0.0,
        }

    compatibility = classify_camelot_compatibility(truth.camelot.camelot, result.camelot)
    exact = truth.camelot.camelot == result.camelot
    return {
        "status": "scored",
        "truthCamelot": truth.camelot.camelot,
        "predictedCamelot": result.camelot,
        "truthTonic": truth.camelot.tonic,
        "truthMode": truth.camelot.mode,
        "predictedTonic": result.tonic,
        "predictedMode": result.mode,
        "exactCamelotMatch": exact,
        "compatibility": compatibility.to_dict(),
        "score": 1.0 if exact else compatibility.score,
    }


def _candidate_summary(case_results: list[dict[str, Any]], candidates: Sequence[str]) -> list[dict[str, Any]]:
    summaries = []
    for candidate in candidates:
        rows = [
            candidate_result
            for case_result in case_results
            for candidate_result in case_result["candidates"]
            if candidate_result["candidate"] == candidate
        ]
        scored = [row for row in rows if row["score"]["status"] == "scored"]
        exact = [row for row in scored if row["score"]["exactCamelotMatch"] is True]
        compatible = [
            row
            for row in scored
            if row["score"].get("compatibility", {}).get("classification")
            in {"perfect", "relative", "adjacent", "parallel"}
        ]
        summaries.append(
            {
                "candidate": candidate,
                "ok": sum(row["status"] == "ok" for row in rows),
                "failed": sum(row["status"] == "failed" for row in rows),
                "unavailable": sum(row["status"] == "unavailable" for row in rows),
                "scoredTracks": len(scored),
                "exactCamelotMatches": len(exact),
                "exactCamelotAccuracy": _ratio(len(exact), len(scored)),
                "compatibleMatches": len(compatible),
                "compatibleAccuracy": _ratio(len(compatible), len(scored)),
                "averageCompatibilityScore": _round_optional(
                    _mean_optional([row["score"].get("score") for row in scored])
                ),
                "medianConfidence": _round_optional(_median_optional([row["confidence"] for row in scored])),
                "processingSeconds": _round_float(sum(float(row["processingSeconds"]) for row in rows)),
                "mismatches": [
                    {
                        "trackId": case_result["trackId"],
                        "trackName": case_result["trackName"],
                        "truthCamelot": row["score"].get("truthCamelot"),
                        "predictedCamelot": row["score"].get("predictedCamelot"),
                        "compatibility": (
                            row["score"].get("compatibility", {}).get("classification")
                            if row["score"].get("compatibility") is not None
                            else None
                        ),
                    }
                    for case_result in case_results
                    for row in case_result["candidates"]
                    if row["candidate"] == candidate and row["score"].get("exactCamelotMatch") is False
                ],
            }
        )
    return summaries


def _missing_key_result(candidate: str, message: str) -> KeyCandidateResult:
    return KeyCandidateResult(
        status="unavailable",
        provenance=CandidateProvenance(
            backend_name=candidate,
            backend_version=__version__,
            processing_seconds=0.0,
        ),
        error=BackendExecutionError(
            code="key_backend_unavailable",
            message=message,
            backend_name=candidate,
        ),
    )


def _truth_row_from_track(track: RekordboxTrack) -> RekordboxKeyTruthRow:
    if track.tonality is None or not track.tonality.strip():
        return RekordboxKeyTruthRow(
            track_name=track.name,
            location=track.location,
            average_bpm=track.average_bpm,
            camelot=None,
            status="unscored",
            warnings=(
                {
                    "code": "rekordbox_tonality_missing",
                    "message": "Rekordbox TRACK Tonality is missing or empty",
                },
            ),
        )

    try:
        camelot = parse_camelot(track.tonality)
    except CamelotKeyError as exc:
        return RekordboxKeyTruthRow(
            track_name=track.name,
            location=track.location,
            average_bpm=track.average_bpm,
            camelot=None,
            status="unscored",
            warnings=(exc.to_dict(),),
        )

    return RekordboxKeyTruthRow(
        track_name=track.name,
        location=track.location,
        average_bpm=track.average_bpm,
        camelot=camelot,
        status="scored",
    )


def _path_from_rekordbox_location(location: str) -> Path:
    parsed = urlparse(location)
    if parsed.scheme != "file":
        raise KeyBenchmarkError(
            "key_benchmark_unsupported_location",
            f"Only file:// Rekordbox locations are supported: {location}",
        )
    path = unquote(parsed.path)
    if re.match(r"^/[A-Za-z]:/", path):
        path = path[1:]
    return Path(path)


def _coerce_local_path(path: str | Path) -> Path:
    raw = str(path)
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", raw)
    if match and platform.system() != "Windows":
        drive = match.group(1).lower()
        remainder = match.group(2).replace("\\", "/")
        return Path(f"/mnt/{drive}/{remainder}")
    return Path(path)


def _safe_path_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return normalized.lower() or "track"


def _load_json_object(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise KeyBenchmarkError("key_benchmark_read_error", f"Could not read key benchmark file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise KeyBenchmarkError("key_benchmark_parse_error", f"Could not parse key benchmark JSON: {exc}") from exc


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return _round_float(numerator / denominator)


def _mean_optional(values: Sequence[Any]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _median_optional(values: Sequence[Any]) -> float | None:
    numbers = sorted(float(value) for value in values if value is not None)
    if not numbers:
        return None
    middle = len(numbers) // 2
    if len(numbers) % 2:
        return numbers[middle]
    return (numbers[middle - 1] + numbers[middle]) / 2.0


def _round_optional(value: float | None) -> float | None:
    return None if value is None else _round_float(value)


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
