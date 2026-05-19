"""Benchmark semantic section candidates against labeled Rekordbox cues."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import platform
from pathlib import Path
import re
import shutil
from typing import Any
from urllib.parse import unquote, urlparse

from .. import __version__
from ..audio_io import DecodedAudio, load_audio
from ..backends import (
    ALL_IN_ONE_BACKEND,
    CURRENT_SIGNAL_BACKEND,
    SONGFORMER_BACKEND,
    AnalysisContext,
    BackendExecutionError,
    BackendRegistry,
    CandidateProvenance,
    CurrentSignalBackend,
    FeatureBundle,
    SectionBackend,
    SectionCandidateResult,
    register_dubstep_phrase_hybrid_backends,
    register_all_in_one_backends,
    register_current_signal_backends,
    register_songformer_backends,
)
from ..cache import SCHEMA_VERSION, write_json_atomic
from ..debug_waveform import build_debug_waveform_artifact
from ..features import EnergyFeatures, build_energy_analysis
from ..rekordbox_xml import RekordboxCue, RekordboxTrack, RekordboxXmlError, load_rekordbox_tracks
from ..section_labels import PROJECT_SECTION_LABELS, SectionLabel, map_section_label
from ..tempo import normalize_dubstep_bpm
from .timing_benchmark import write_analysis_audio_wav


SEMANTIC_BENCHMARK_REPORT_TYPE = "semantic-section-candidate-benchmark"
DEFAULT_SEMANTIC_CANDIDATES = (CURRENT_SIGNAL_BACKEND, ALL_IN_ONE_BACKEND, SONGFORMER_BACKEND)
DEFAULT_SEMANTIC_ANALYSIS_SAMPLE_RATE = 44_100
DEFAULT_SEMANTIC_DEBUG_WAVEFORM_POINTS = 32_768
SECTION_MATCH_START_TOLERANCE_SECONDS = {
    "drop": 2.0,
    "build": 4.0,
    "intro": 8.0,
    "verse": 8.0,
    "break": 8.0,
    "outro": 8.0,
}

AudioLoader = Callable[..., DecodedAudio]
AnalysisAudioWriter = Callable[[Path, DecodedAudio], Path]
DebugWaveformBuilder = Callable[..., dict[str, Any]]


class SemanticBenchmarkError(ValueError):
    """Expected semantic benchmark failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class SemanticBenchmarkCase:
    track_id: str
    track_name: str
    audio_path: Path
    rekordbox_track: RekordboxTrack


@dataclass(frozen=True)
class ReferenceSection:
    id: str
    type: SectionLabel
    start_seconds: float
    end_seconds: float
    source_cue_name: str
    end_cue_name: str | None = None
    ordinal: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "startSeconds": _round_float(self.start_seconds),
            "endSeconds": _round_float(self.end_seconds),
            "sourceCueName": self.source_cue_name,
        }
        if self.end_cue_name is not None:
            payload["endCueName"] = self.end_cue_name
        if self.ordinal is not None:
            payload["ordinal"] = self.ordinal
        return payload


@dataclass(frozen=True)
class ParsedCueLabel:
    section_type: SectionLabel
    boundary: str
    ordinal: int | None


def default_semantic_backend_registry() -> BackendRegistry:
    registry = BackendRegistry()
    register_current_signal_backends(registry)
    register_all_in_one_backends(registry)
    register_songformer_backends(registry)
    register_dubstep_phrase_hybrid_backends(registry)
    return registry


def load_semantic_benchmark_cases(rekordbox_xml_path: str | Path) -> tuple[SemanticBenchmarkCase, ...]:
    """Create semantic benchmark cases from every TRACK in a Rekordbox XML export."""

    try:
        tracks = load_rekordbox_tracks(rekordbox_xml_path)
    except RekordboxXmlError as exc:
        raise SemanticBenchmarkError(exc.code, exc.message) from exc
    cases = []
    for track in tracks:
        audio_path = _coerce_local_path(_path_from_rekordbox_location(track.location))
        cases.append(
            SemanticBenchmarkCase(
                track_id=_safe_path_name(Path(audio_path).stem or track.name or "track"),
                track_name=track.name,
                audio_path=audio_path,
                rekordbox_track=track,
            )
        )
    return tuple(cases)


def run_semantic_section_benchmark(
    cases: Sequence[SemanticBenchmarkCase],
    output_root: str | Path,
    *,
    candidates: Sequence[str] = DEFAULT_SEMANTIC_CANDIDATES,
    registry: BackendRegistry | None = None,
    audio_loader: AudioLoader = load_audio,
    analysis_audio_writer: AnalysisAudioWriter = write_analysis_audio_wav,
    debug_waveform_builder: DebugWaveformBuilder = build_debug_waveform_artifact,
    current_backend_factory: Callable[[], CurrentSignalBackend] = CurrentSignalBackend,
    analysis_sample_rate: int = DEFAULT_SEMANTIC_ANALYSIS_SAMPLE_RATE,
    debug_waveform_points: int = DEFAULT_SEMANTIC_DEBUG_WAVEFORM_POINTS,
) -> dict[str, Any]:
    """Run semantic section candidates and compare them to labeled Rekordbox cues."""

    if analysis_sample_rate <= 0:
        raise SemanticBenchmarkError(
            "semantic_benchmark_invalid_sample_rate",
            "analysis_sample_rate must be greater than zero.",
        )
    if debug_waveform_points <= 0:
        raise SemanticBenchmarkError(
            "semantic_benchmark_invalid_debug_points",
            "debug_waveform_points must be greater than zero.",
        )
    registry = registry or default_semantic_backend_registry()
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    created_at_utc = _utc_now_iso()
    candidate_names = tuple(candidates)
    case_results = [
        _run_case(
            case,
            output_root,
            candidates=candidate_names,
            registry=registry,
            audio_loader=audio_loader,
            analysis_audio_writer=analysis_audio_writer,
            debug_waveform_builder=debug_waveform_builder,
            current_backend_factory=current_backend_factory,
            analysis_sample_rate=analysis_sample_rate,
            debug_waveform_points=debug_waveform_points,
            created_at_utc=created_at_utc,
        )
        for case in cases
    ]
    summary = {
        "schemaVersion": SCHEMA_VERSION,
        "reportType": SEMANTIC_BENCHMARK_REPORT_TYPE,
        "createdAtUtc": created_at_utc,
        "outputRoot": str(output_root),
        "parameters": {
            "candidates": list(candidate_names),
            "analysisSampleRate": analysis_sample_rate,
            "debugWaveformPoints": debug_waveform_points,
            "referenceSource": "rekordbox-position-mark-names",
            "sectionLabels": list(PROJECT_SECTION_LABELS),
        },
        "cases": case_results,
        "candidateSummary": _candidate_summary(case_results, candidate_names),
    }
    write_json_atomic(output_root / "semantic-section-benchmark-summary.json", summary)
    return summary


def _run_case(
    case: SemanticBenchmarkCase,
    output_root: Path,
    *,
    candidates: tuple[str, ...],
    registry: BackendRegistry,
    audio_loader: AudioLoader,
    analysis_audio_writer: AnalysisAudioWriter,
    debug_waveform_builder: DebugWaveformBuilder,
    current_backend_factory: Callable[[], CurrentSignalBackend],
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
        analyzer_producer="autodj_analysis.semantic_benchmark",
        analyzer_version=__version__,
        created_at_utc=created_at_utc,
        target_point_count=debug_waveform_points,
    )
    write_json_atomic(case_dir / "debug-waveform.json", debug_artifact)

    current_backend = current_backend_factory()
    current_results = current_backend.analyze_candidates(audio, context)
    reference_sections = reference_sections_from_rekordbox(
        case.rekordbox_track,
        duration_seconds=audio.duration_seconds,
    )
    candidate_results = [
        _run_candidate(
            candidate,
            case,
            case_dir,
            audio,
            context,
            current_results,
            reference_sections,
            registry=registry,
            debug_artifact=debug_artifact,
            created_at_utc=created_at_utc,
        )
        for candidate in candidates
    ]
    return {
        "trackId": case.track_id,
        "trackName": case.track_name,
        "audioPath": str(case.audio_path),
        "caseDir": str(case_dir),
        "durationSeconds": _round_float(audio.duration_seconds),
        "debugWaveformPath": str(case_dir / "debug-waveform.json"),
        "referenceSections": [section.to_dict() for section in reference_sections],
        "candidates": candidate_results,
    }


def _run_candidate(
    candidate: str,
    case: SemanticBenchmarkCase,
    case_dir: Path,
    audio: DecodedAudio,
    context: AnalysisContext,
    current_results: Any,
    reference_sections: tuple[ReferenceSection, ...],
    *,
    registry: BackendRegistry,
    debug_artifact: dict[str, Any],
    created_at_utc: str,
) -> dict[str, Any]:
    candidate_dir = case_dir / _safe_path_name(candidate)
    candidate_dir.mkdir(parents=True, exist_ok=True)
    section_result = _execute_section_candidate(candidate, audio, context, current_results, registry=registry)
    artifact = _candidate_artifact(
        candidate,
        case,
        audio,
        current_results,
        section_result,
        created_at_utc=created_at_utc,
    )
    analyzed_path = write_json_atomic(candidate_dir / "analyzed-track.json", artifact)
    write_json_atomic(candidate_dir / "debug-waveform.json", debug_artifact)
    audio_copy_path = _copy_source_audio_for_viewer(case.audio_path, candidate_dir)
    report = evaluate_sections_against_references(
        section_result,
        reference_sections,
        candidate_name=candidate,
        track_id=case.track_id,
        track_name=case.track_name,
    )
    report_path = write_json_atomic(candidate_dir / "section-evaluation.json", report)
    metrics = report["metrics"]
    return {
        "candidate": candidate,
        "status": section_result.status,
        "analyzedTrackPath": str(analyzed_path),
        "debugWaveformPath": str(candidate_dir / "debug-waveform.json"),
        "audioPath": str(audio_copy_path) if audio_copy_path is not None else None,
        "sectionEvaluationPath": str(report_path),
        "processingSeconds": section_result.provenance.processing_seconds,
        "sectionCount": len(section_result.sections),
        "cuePointCount": len(section_result.cue_points),
        "matchedSectionCount": metrics["matchedSectionCount"],
        "missingReferenceSectionCount": metrics["missingReferenceSectionCount"],
        "falsePositiveSectionCount": metrics["falsePositiveSectionCount"],
        "missedDropCount": metrics["missedByType"].get("drop", 0),
        "falsePositiveDropCount": metrics["falsePositiveByType"].get("drop", 0),
        "medianStartErrorMilliseconds": metrics["medianStartErrorMilliseconds"],
        "medianEndErrorMilliseconds": metrics["medianEndErrorMilliseconds"],
        "labelCounts": metrics["candidateLabelCounts"],
        "sectionProvenance": section_result.provenance.to_dict(),
        "error": section_result.error.to_dict() if section_result.error is not None else None,
    }


def _copy_source_audio_for_viewer(source_path: Path, candidate_dir: Path) -> Path | None:
    if not source_path.is_file():
        return None
    suffix = source_path.suffix.lower() or ".audio"
    destination = candidate_dir / f"source-audio{suffix}"
    if destination.resolve() == source_path.resolve():
        return destination
    shutil.copy2(source_path, destination)
    return destination


def _execute_section_candidate(
    candidate: str,
    audio: DecodedAudio,
    context: AnalysisContext,
    current_results: Any,
    *,
    registry: BackendRegistry,
) -> SectionCandidateResult:
    if candidate == CURRENT_SIGNAL_BACKEND:
        return current_results.sections
    if candidate not in registry.section_names():
        return _missing_section_result(candidate, "No section backend is registered for this candidate.")
    try:
        backend = registry.create_section(candidate)
        if not isinstance(backend, SectionBackend):
            return _missing_section_result(candidate, "Registered candidate does not implement SectionBackend.")
        energy_features = getattr(current_results, "energy_features", None)
        return backend.analyze_sections(
            audio,
            FeatureBundle(energy=energy_features if isinstance(energy_features, EnergyFeatures) else None),
            current_results.beat_grid,
            context,
        )
    except Exception as exc:
        return SectionCandidateResult(
            status="failed",
            provenance=CandidateProvenance(
                backend_name=candidate,
                backend_version=__version__,
                processing_seconds=0.0,
            ),
            error=BackendExecutionError(
                code="section_candidate_failed",
                message=str(exc),
                backend_name=candidate,
            ),
        )


def _candidate_artifact(
    candidate: str,
    case: SemanticBenchmarkCase,
    audio: DecodedAudio,
    current_results: Any,
    section_result: SectionCandidateResult,
    *,
    created_at_utc: str,
) -> dict[str, Any]:
    normalized = normalize_dubstep_bpm(current_results.tempo.bpm or 140.0)
    warnings = list(current_results.tempo.provenance.warnings)
    warnings.extend(current_results.beat_grid.provenance.warnings)
    warnings.extend(section_result.provenance.warnings)
    if section_result.status != "ok" and section_result.error is not None:
        warnings.append(section_result.error.message)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "trackId": case.track_id,
        "source": {
            "trackId": case.track_id,
            "repositoryId": "semantic-section-benchmark",
            "sourceUri": str(case.audio_path),
            "durationSeconds": _round_float(audio.duration_seconds),
            "title": case.track_name or case.audio_path.stem,
            "sampleRate": int(audio.sample_rate),
            "channels": audio.channels,
            "providerMetadata": {
                "rekordboxTrackName": case.rekordbox_track.name,
                "rekordboxLocation": case.rekordbox_track.location,
            },
        },
        "analyzer": {
            "producer": "autodj_analysis.semantic_benchmark",
            "producerVersion": __version__,
            "createdAtUtc": created_at_utc,
            "parametersHash": "sha256:semantic-section-candidate-benchmark-v1",
            "candidate": {
                "tempo": current_results.tempo.to_dict(),
                "beatGrid": current_results.beat_grid.to_dict(),
                "sections": section_result.to_dict(),
            },
        },
        "durationSeconds": _round_float(audio.duration_seconds),
        "tempo": {
            "bpm": current_results.tempo.bpm,
            "normalizedBpm": current_results.tempo.normalized_bpm or normalized.normalized_bpm,
            "confidence": current_results.tempo.confidence,
            "tempoClass": current_results.tempo.tempo_class or normalized.tempo_class,
            "candidates": [candidate.to_dict() for candidate in current_results.tempo.candidates],
        },
        "key": {
            "tonic": "unknown",
            "mode": "unknown",
            "confidence": 0.0,
            "candidates": [],
        },
        "beatGrid": {
            "beats": [beat.to_dict() for beat in current_results.beat_grid.beats],
            "downbeats": [downbeat.to_dict() for downbeat in current_results.beat_grid.downbeats],
            "confidence": current_results.beat_grid.confidence,
        },
        "sections": [section.to_dict() for section in section_result.sections],
        "energy": _energy_analysis(getattr(current_results, "energy_features", None)),
        "vocals": {
            "hasVocals": False,
            "confidence": 0.0,
            "regions": [],
        },
        "cuePoints": [dict(cue) for cue in section_result.cue_points],
        "quality": {
            "overallConfidence": _overall_confidence(current_results, section_result),
            "warnings": warnings,
        },
    }


def reference_sections_from_rekordbox(
    rekordbox_track: RekordboxTrack,
    *,
    duration_seconds: float,
) -> tuple[ReferenceSection, ...]:
    starts: list[tuple[RekordboxCue, ParsedCueLabel]] = []
    ends: dict[tuple[SectionLabel, int | None], RekordboxCue] = {}
    for cue in rekordbox_track.cues:
        parsed = _parse_cue_label(cue.name)
        if parsed is None or parsed.section_type == "unknown":
            continue
        key = (parsed.section_type, parsed.ordinal)
        if parsed.boundary == "start":
            starts.append((cue, parsed))
        elif parsed.boundary == "end":
            ends[key] = cue

    starts.sort(key=lambda item: item[0].start_seconds)
    counts: Counter[str] = Counter()
    sections: list[ReferenceSection] = []
    for index, (cue, parsed) in enumerate(starts):
        explicit_end = ends.get((parsed.section_type, parsed.ordinal))
        next_start = starts[index + 1][0] if index + 1 < len(starts) else None
        if explicit_end is not None and explicit_end.start_seconds > cue.start_seconds:
            end_seconds = explicit_end.start_seconds
            end_cue_name = explicit_end.name
        elif next_start is not None and next_start.start_seconds > cue.start_seconds:
            end_seconds = next_start.start_seconds
            end_cue_name = next_start.name
        else:
            end_seconds = duration_seconds
            end_cue_name = None
        if end_seconds <= cue.start_seconds:
            continue
        counts[parsed.section_type] += 1
        ordinal = parsed.ordinal or counts[parsed.section_type]
        sections.append(
            ReferenceSection(
                id=f"section-rekordbox-{parsed.section_type}-{ordinal:03d}",
                type=parsed.section_type,
                start_seconds=_round_float(cue.start_seconds),
                end_seconds=_round_float(end_seconds),
                source_cue_name=cue.name,
                end_cue_name=end_cue_name,
                ordinal=ordinal,
            )
        )
    return tuple(sections)


def evaluate_sections_against_references(
    section_result: SectionCandidateResult,
    reference_sections: Sequence[ReferenceSection],
    *,
    candidate_name: str,
    track_id: str,
    track_name: str,
) -> dict[str, Any]:
    candidate_sections = [section for section in section_result.sections if section.type != "unknown"]
    used_candidate_indexes: set[int] = set()
    matches: list[dict[str, Any]] = []
    missing_by_type: Counter[str] = Counter()

    for reference in reference_sections:
        match_index, candidate = _nearest_unused_section(reference, candidate_sections, used_candidate_indexes)
        if candidate is None:
            missing_by_type[reference.type] += 1
            matches.append(
                {
                    "referenceSectionId": reference.id,
                    "sectionType": reference.type,
                    "status": "missing_candidate",
                    "candidateSectionId": None,
                    "startErrorMilliseconds": None,
                    "endErrorMilliseconds": None,
                }
            )
            continue
        used_candidate_indexes.add(match_index)
        start_error_ms = (candidate.start_seconds - reference.start_seconds) * 1000.0
        end_error_ms = (candidate.end_seconds - reference.end_seconds) * 1000.0
        matches.append(
            {
                "referenceSectionId": reference.id,
                "sectionType": reference.type,
                "status": "matched",
                "candidateSectionId": candidate.id,
                "candidateSourceLabel": candidate.source_label,
                "referenceStartSeconds": reference.start_seconds,
                "candidateStartSeconds": _round_float(candidate.start_seconds),
                "referenceEndSeconds": reference.end_seconds,
                "candidateEndSeconds": _round_float(candidate.end_seconds),
                "startErrorMilliseconds": _round_float(start_error_ms),
                "endErrorMilliseconds": _round_float(end_error_ms),
                "absoluteStartErrorMilliseconds": _round_float(abs(start_error_ms)),
                "absoluteEndErrorMilliseconds": _round_float(abs(end_error_ms)),
                "candidateConfidence": candidate.confidence,
            }
        )

    false_positives = [
        {
            "candidateSectionId": section.id,
            "sectionType": section.type,
            "sourceLabel": section.source_label,
            "startSeconds": _round_float(section.start_seconds),
            "endSeconds": _round_float(section.end_seconds),
            "confidence": section.confidence,
        }
        for index, section in enumerate(candidate_sections)
        if index not in used_candidate_indexes
    ]
    false_positive_by_type = Counter(str(section["sectionType"]) for section in false_positives)
    start_errors = [
        float(match["absoluteStartErrorMilliseconds"])
        for match in matches
        if match["status"] == "matched" and match["absoluteStartErrorMilliseconds"] is not None
    ]
    end_errors = [
        float(match["absoluteEndErrorMilliseconds"])
        for match in matches
        if match["status"] == "matched" and match["absoluteEndErrorMilliseconds"] is not None
    ]
    label_counts = Counter(section.type for section in section_result.sections)
    reference_label_counts = Counter(section.type for section in reference_sections)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "reportType": "semantic-section-ground-truth-evaluation",
        "candidate": {
            "name": candidate_name,
            "status": section_result.status,
            "processingSeconds": section_result.provenance.processing_seconds,
            "provenance": section_result.provenance.to_dict(),
            "error": section_result.error.to_dict() if section_result.error is not None else None,
        },
        "track": {
            "trackId": track_id,
            "rekordboxTrackName": track_name,
        },
        "reference": {
            "sectionCount": len(reference_sections),
            "labelCounts": dict(reference_label_counts),
            "sections": [section.to_dict() for section in reference_sections],
        },
        "metrics": {
            "candidateSectionCount": len(section_result.sections),
            "candidateKnownSectionCount": len(candidate_sections),
            "candidateLabelCounts": dict(label_counts),
            "matchedSectionCount": sum(match["status"] == "matched" for match in matches),
            "missingReferenceSectionCount": sum(match["status"] == "missing_candidate" for match in matches),
            "falsePositiveSectionCount": len(false_positives),
            "missedByType": dict(missing_by_type),
            "falsePositiveByType": dict(false_positive_by_type),
            "medianStartErrorMilliseconds": _round_optional(_percentile(start_errors, 50.0)),
            "medianEndErrorMilliseconds": _round_optional(_percentile(end_errors, 50.0)),
            "p95StartErrorMilliseconds": _round_optional(_percentile(start_errors, 95.0)),
            "p95EndErrorMilliseconds": _round_optional(_percentile(end_errors, 95.0)),
            "sectionBoundaryErrors": matches,
            "falsePositiveSections": false_positives,
        },
    }


def _parse_cue_label(name: str) -> ParsedCueLabel | None:
    parts = [part for part in name.strip().lower().split("_") if part]
    if len(parts) < 2:
        return None
    boundary = parts[-1]
    if boundary not in {"start", "end"}:
        return None
    ordinal = None
    label_parts = parts[:-1]
    if label_parts and label_parts[-1].isdigit():
        ordinal = int(label_parts[-1])
        label_parts = label_parts[:-1]
    if not label_parts:
        return None
    source_label = "_".join(label_parts)
    mapping = map_section_label(source_label, provider_name="rekordbox")
    return ParsedCueLabel(mapping.label, boundary, ordinal)


def _nearest_unused_section(
    reference: ReferenceSection,
    candidate_sections: list[Any],
    used_indexes: set[int],
) -> tuple[int, Any | None]:
    best_index = -1
    best = None
    best_distance = float("inf")
    for index, candidate in enumerate(candidate_sections):
        if index in used_indexes or candidate.type != reference.type:
            continue
        distance = abs(candidate.start_seconds - reference.start_seconds)
        if distance < best_distance:
            best_index = index
            best = candidate
            best_distance = distance
    tolerance = SECTION_MATCH_START_TOLERANCE_SECONDS.get(reference.type, 8.0)
    if best is not None and best_distance > tolerance:
        return -1, None
    return best_index, best


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
                "matchedSectionCount": sum(int(row["matchedSectionCount"]) for row in rows),
                "missingReferenceSectionCount": sum(int(row["missingReferenceSectionCount"]) for row in rows),
                "falsePositiveSectionCount": sum(int(row["falsePositiveSectionCount"]) for row in rows),
                "missedDropCount": sum(int(row["missedDropCount"]) for row in rows),
                "falsePositiveDropCount": sum(int(row["falsePositiveDropCount"]) for row in rows),
                "medianStartErrorMilliseconds": _round_optional(
                    _median_optional([row["medianStartErrorMilliseconds"] for row in rows])
                ),
                "medianEndErrorMilliseconds": _round_optional(
                    _median_optional([row["medianEndErrorMilliseconds"] for row in rows])
                ),
                "processingSeconds": _round_float(sum(float(row["processingSeconds"]) for row in rows)),
            }
        )
    return summaries


def _missing_section_result(candidate: str, message: str) -> SectionCandidateResult:
    return SectionCandidateResult(
        status="unavailable",
        provenance=CandidateProvenance(
            backend_name=candidate,
            backend_version=__version__,
            processing_seconds=0.0,
        ),
        error=BackendExecutionError(
            code="section_backend_unavailable",
            message=message,
            backend_name=candidate,
        ),
    )


def _path_from_rekordbox_location(location: str) -> Path:
    parsed = urlparse(location)
    if parsed.scheme != "file":
        raise SemanticBenchmarkError(
            "semantic_benchmark_unsupported_location",
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


def _overall_confidence(current_results: Any, section_result: SectionCandidateResult) -> float:
    values = [current_results.tempo.confidence, current_results.beat_grid.confidence]
    if section_result.status == "ok" and section_result.sections:
        values.extend(section.confidence for section in section_result.sections)
    return _round_float(sum(float(value) for value in values) / len(values))


def _energy_analysis(features: Any) -> dict[str, Any]:
    if isinstance(features, EnergyFeatures):
        return build_energy_analysis(features)
    return {
        "globalEnergy": 0.0,
        "curve": [],
        "bassEnergyCurve": [],
        "onsetDensityCurve": [],
    }


def _median_optional(values: Sequence[Any]) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    return _percentile(numeric, 50.0)


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile / 100.0
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _round_optional(value: float | None) -> float | None:
    return None if value is None else _round_float(value)


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
