"""Compare analyzed-track artifacts against Rekordbox XML ground truth."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Literal

from ..cache import SCHEMA_VERSION, write_json_atomic
from ..rekordbox_xml import RekordboxCue, RekordboxTrack, RekordboxXmlError, load_rekordbox_track
from ..tempo import normalize_dubstep_bpm


REKORDBOX_EVALUATION_REPORT_TYPE = "rekordbox-ground-truth-evaluation"
EVALUATION_STATUS_VALUES = frozenset({"ok", "unavailable", "failed", "deferred"})
DEFAULT_TIMELINE_OFFSET_POLICY = "none"

CandidateStatus = Literal["ok", "unavailable", "failed", "deferred"]


class EvaluationError(ValueError):
    """Expected evaluation harness failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class RekordboxEvaluationOptions:
    candidate_name: str | None = None
    candidate_status: CandidateStatus = "ok"
    processing_seconds: float | None = None
    timeline_offset_seconds: float = 0.0
    timeline_offset_policy: str = DEFAULT_TIMELINE_OFFSET_POLICY

    def __post_init__(self) -> None:
        if self.candidate_status not in EVALUATION_STATUS_VALUES:
            raise EvaluationError(
                "evaluation_invalid_candidate_status",
                f"Unsupported candidate status: {self.candidate_status}",
            )
        if self.processing_seconds is not None and self.processing_seconds < 0:
            raise EvaluationError(
                "evaluation_invalid_processing_seconds",
                "processing_seconds must be greater than or equal to zero",
            )
        if not self.timeline_offset_policy:
            raise EvaluationError(
                "evaluation_invalid_timeline_offset_policy",
                "timeline_offset_policy must not be empty",
            )


def evaluate_analyzed_artifact_against_rekordbox(
    analyzed_artifact: dict[str, Any],
    rekordbox_track: RekordboxTrack,
    *,
    options: RekordboxEvaluationOptions | None = None,
) -> dict[str, Any]:
    """Build a benchmark report comparing an analyzed artifact to Rekordbox XML."""

    if not isinstance(analyzed_artifact, dict):
        raise EvaluationError("evaluation_invalid_artifact", "Analyzed artifact root must be a JSON object")
    if not rekordbox_track.tempos:
        raise EvaluationError("evaluation_no_rekordbox_tempo", "Rekordbox track has no tempo marker")
    reference_tempo = rekordbox_track.tempos[0]
    if reference_tempo.bpm <= 0:
        raise EvaluationError("evaluation_invalid_rekordbox_tempo", "Rekordbox tempo BPM must be greater than zero")

    options = options or RekordboxEvaluationOptions()
    duration_seconds = _comparison_duration(analyzed_artifact, rekordbox_track)
    reference_beats = _reference_beats(rekordbox_track, duration_seconds)
    candidate_beats = _candidate_markers(
        analyzed_artifact.get("beatGrid", {}).get("beats", ()),
        timeline_offset_seconds=options.timeline_offset_seconds,
    )
    candidate_downbeats = _candidate_markers(
        analyzed_artifact.get("beatGrid", {}).get("downbeats", ()),
        timeline_offset_seconds=options.timeline_offset_seconds,
    )
    reference_cues = _reference_cues(rekordbox_track)
    reference_sections = _reference_sections(rekordbox_track)

    warnings: list[str] = []
    if options.timeline_offset_seconds:
        warnings.append(
            "Candidate timeline was shifted by "
            f"{options.timeline_offset_seconds:.6f} seconds using policy "
            f"{options.timeline_offset_policy!r} before comparison."
        )
    if not candidate_beats:
        warnings.append("Candidate artifact has no beat markers; beat-grid error metrics are unavailable.")
    if not analyzed_artifact.get("cuePoints"):
        warnings.append("Candidate artifact has no cue points; cue boundary metrics are unavailable.")
    if not analyzed_artifact.get("sections"):
        warnings.append("Candidate artifact has no sections; section boundary metrics are unavailable.")

    report = {
        "schemaVersion": SCHEMA_VERSION,
        "reportType": REKORDBOX_EVALUATION_REPORT_TYPE,
        "candidate": _candidate_summary(analyzed_artifact, options),
        "track": {
            "trackId": str(analyzed_artifact.get("trackId") or ""),
            "rekordboxTrackName": rekordbox_track.name,
            "rekordboxLocation": rekordbox_track.location,
            "durationSeconds": _round_float(duration_seconds),
        },
        "reference": _reference_summary(rekordbox_track, reference_beats, reference_sections),
        "metrics": {
            "tempo": _tempo_metrics(analyzed_artifact, reference_tempo),
            "beatGrid": _beat_grid_metrics(candidate_beats, candidate_downbeats, reference_beats),
            "cueAdjacentDrift": _cue_adjacent_drift(reference_cues, candidate_beats),
            "cueBoundaryErrors": _cue_boundary_errors(
                analyzed_artifact.get("cuePoints", ()),
                reference_cues,
                timeline_offset_seconds=options.timeline_offset_seconds,
            ),
            "sectionBoundaryErrors": _section_boundary_errors(
                analyzed_artifact.get("sections", ()),
                reference_sections,
                timeline_offset_seconds=options.timeline_offset_seconds,
            ),
        },
        "warnings": warnings,
    }
    return report


def write_rekordbox_evaluation_report(
    analyzed_path: str | Path,
    rekordbox_xml_path: str | Path,
    output_path: str | Path,
    *,
    track_name: str | None = None,
    options: RekordboxEvaluationOptions | None = None,
) -> Path:
    """Load analyzed-track JSON and Rekordbox XML, then write a benchmark report."""

    analyzed = _load_json_object(analyzed_path)
    try:
        rekordbox_track = load_rekordbox_track(rekordbox_xml_path, track_name=track_name)
    except RekordboxXmlError as exc:
        raise EvaluationError(exc.code, exc.message) from exc
    report = evaluate_analyzed_artifact_against_rekordbox(
        analyzed,
        rekordbox_track,
        options=options,
    )
    return write_json_atomic(output_path, report)


def _candidate_summary(
    analyzed_artifact: dict[str, Any],
    options: RekordboxEvaluationOptions,
) -> dict[str, Any]:
    analyzer = analyzed_artifact.get("analyzer") if isinstance(analyzed_artifact.get("analyzer"), dict) else {}
    payload: dict[str, Any] = {
        "name": options.candidate_name or _candidate_name(analyzed_artifact),
        "status": options.candidate_status,
        "timelineOffsetSeconds": _round_float(options.timeline_offset_seconds),
        "timelineOffsetPolicy": options.timeline_offset_policy,
        "analyzer": {
            "producer": analyzer.get("producer"),
            "producerVersion": analyzer.get("producerVersion"),
            "parametersHash": analyzer.get("parametersHash"),
        },
    }
    if options.processing_seconds is not None:
        payload["processingSeconds"] = _round_float(options.processing_seconds)
    return payload


def _candidate_name(analyzed_artifact: dict[str, Any]) -> str:
    analyzer = analyzed_artifact.get("analyzer")
    if isinstance(analyzer, dict) and analyzer.get("producer"):
        return str(analyzer["producer"])
    candidates = analyzed_artifact.get("tempo", {}).get("candidates", ())
    if isinstance(candidates, list) and candidates:
        backend = candidates[0].get("backend") if isinstance(candidates[0], dict) else None
        if backend:
            return str(backend)
    return "analyzed-track"


def _reference_summary(
    rekordbox_track: RekordboxTrack,
    reference_beats: list[dict[str, float | int]],
    reference_sections: list[dict[str, Any]],
) -> dict[str, Any]:
    tempo = rekordbox_track.tempos[0]
    normalized = normalize_dubstep_bpm(tempo.bpm)
    return {
        "backend": "rekordbox.xml",
        "bpm": _round_float(tempo.bpm),
        "normalizedBpm": normalized.normalized_bpm,
        "tempoStartSeconds": _round_float(tempo.start_seconds),
        "averageBpm": rekordbox_track.average_bpm,
        "beatCount": len(reference_beats),
        "cueCount": len(rekordbox_track.cues),
        "sectionCount": len(reference_sections),
    }


def _tempo_metrics(analyzed_artifact: dict[str, Any], reference_tempo: Any) -> dict[str, Any]:
    candidate_bpm = _optional_float(analyzed_artifact.get("tempo", {}).get("bpm"))
    candidate_normalized_bpm = _optional_float(analyzed_artifact.get("tempo", {}).get("normalizedBpm"))
    reference_normalized = normalize_dubstep_bpm(reference_tempo.bpm).normalized_bpm
    return {
        "candidateBpm": _round_optional(candidate_bpm),
        "referenceBpm": _round_float(reference_tempo.bpm),
        "bpmAbsoluteError": _round_optional_abs_error(candidate_bpm, reference_tempo.bpm),
        "candidateNormalizedBpm": _round_optional(candidate_normalized_bpm),
        "referenceNormalizedBpm": reference_normalized,
        "normalizedBpmAbsoluteError": _round_optional_abs_error(candidate_normalized_bpm, reference_normalized),
    }


def _beat_grid_metrics(
    candidate_beats: list[dict[str, float | int]],
    candidate_downbeats: list[dict[str, float | int]],
    reference_beats: list[dict[str, float | int]],
) -> dict[str, Any]:
    reference_times = [float(beat["timeSeconds"]) for beat in reference_beats]
    candidate_times = [float(beat["timeSeconds"]) for beat in candidate_beats]
    signed_errors_seconds = _nearest_signed_errors(candidate_times, reference_times)
    absolute_errors_ms = [abs(error) * 1000.0 for error in signed_errors_seconds]
    reference_errors_ms = _nearest_absolute_errors_ms(reference_times, candidate_times)
    candidate_errors_ms = _nearest_absolute_errors_ms(candidate_times, reference_times)
    first_offset_ms = None
    if candidate_times and reference_times:
        first_offset_ms = (candidate_times[0] - reference_times[0]) * 1000.0

    payload: dict[str, Any] = {
        "candidateBeatCount": len(candidate_beats),
        "referenceBeatCount": len(reference_beats),
        "beatCoverageRatio": _round_optional(_ratio(len(candidate_beats), len(reference_beats))),
        "firstBeatOffsetMilliseconds": _round_optional(first_offset_ms),
        "medianAbsoluteErrorMilliseconds": _round_optional(_percentile(absolute_errors_ms, 50.0)),
        "p95AbsoluteErrorMilliseconds": _round_optional(_percentile(absolute_errors_ms, 95.0)),
        "maxAbsoluteErrorMilliseconds": _round_optional(max(absolute_errors_ms) if absolute_errors_ms else None),
        "referenceMedianAbsoluteErrorMilliseconds": _round_optional(_percentile(reference_errors_ms, 50.0)),
        "referenceP95AbsoluteErrorMilliseconds": _round_optional(_percentile(reference_errors_ms, 95.0)),
        "referenceMaxAbsoluteErrorMilliseconds": _round_optional(max(reference_errors_ms) if reference_errors_ms else None),
        "referenceRecallWithin25Milliseconds": _round_optional(_within_threshold_ratio(reference_errors_ms, 25.0)),
        "referenceRecallWithin50Milliseconds": _round_optional(_within_threshold_ratio(reference_errors_ms, 50.0)),
        "candidatePrecisionWithin25Milliseconds": _round_optional(_within_threshold_ratio(candidate_errors_ms, 25.0)),
        "candidatePrecisionWithin50Milliseconds": _round_optional(_within_threshold_ratio(candidate_errors_ms, 50.0)),
        "candidateDownbeatCount": len(candidate_downbeats),
        "candidateDownbeats": [dict(downbeat) for downbeat in candidate_downbeats],
    }
    return payload


def _cue_adjacent_drift(
    reference_cues: list[dict[str, Any]],
    candidate_beats: list[dict[str, float | int]],
) -> list[dict[str, Any]]:
    candidate_times = [float(beat["timeSeconds"]) for beat in candidate_beats]
    drift: list[dict[str, Any]] = []
    for cue in reference_cues:
        nearest = _nearest_time(float(cue["timeSeconds"]), candidate_times)
        payload = {
            "cueLabel": cue["label"],
            "cueType": cue["type"],
            "referenceTimeSeconds": cue["timeSeconds"],
            "nearestCandidateBeatTimeSeconds": _round_optional(nearest),
            "signedErrorMilliseconds": _round_optional((nearest - cue["timeSeconds"]) * 1000.0 if nearest is not None else None),
            "absoluteErrorMilliseconds": _round_optional(abs(nearest - cue["timeSeconds"]) * 1000.0 if nearest is not None else None),
        }
        drift.append(payload)
    return drift


def _cue_boundary_errors(
    candidate_cues: Any,
    reference_cues: list[dict[str, Any]],
    *,
    timeline_offset_seconds: float,
) -> list[dict[str, Any]]:
    candidate_by_type: dict[str, list[dict[str, Any]]] = {}
    for cue in _iter_dicts(candidate_cues):
        cue_type = str(cue.get("type") or "")
        time_seconds = _optional_float(cue.get("timeSeconds"))
        if not cue_type or time_seconds is None:
            continue
        candidate = dict(cue)
        candidate["timeSeconds"] = _round_float(time_seconds + timeline_offset_seconds)
        candidate_by_type.setdefault(cue_type, []).append(candidate)

    results: list[dict[str, Any]] = []
    used_by_type: dict[str, set[int]] = {}
    for reference in reference_cues:
        cue_type = str(reference["type"])
        candidates = candidate_by_type.get(cue_type, [])
        match_index, match = _nearest_unused_dict(
            float(reference["timeSeconds"]),
            candidates,
            used_by_type.setdefault(cue_type, set()),
        )
        if match is None:
            results.append(
                {
                    "cueLabel": reference["label"],
                    "cueType": cue_type,
                    "referenceTimeSeconds": reference["timeSeconds"],
                    "status": "missing_candidate",
                    "candidateCueId": None,
                    "signedErrorMilliseconds": None,
                    "absoluteErrorMilliseconds": None,
                }
            )
            continue

        used_by_type[cue_type].add(match_index)
        error_ms = (float(match["timeSeconds"]) - float(reference["timeSeconds"])) * 1000.0
        results.append(
            {
                "cueLabel": reference["label"],
                "cueType": cue_type,
                "referenceTimeSeconds": reference["timeSeconds"],
                "candidateCueId": match.get("id"),
                "candidateTimeSeconds": match["timeSeconds"],
                "status": "ok",
                "signedErrorMilliseconds": _round_float(error_ms),
                "absoluteErrorMilliseconds": _round_float(abs(error_ms)),
            }
        )
    return results


def _section_boundary_errors(
    candidate_sections: Any,
    reference_sections: list[dict[str, Any]],
    *,
    timeline_offset_seconds: float,
) -> list[dict[str, Any]]:
    candidate_drops = [
        section
        for section in _iter_dicts(candidate_sections)
        if section.get("type") == "drop"
        and _optional_float(section.get("startSeconds")) is not None
        and _optional_float(section.get("endSeconds")) is not None
    ]
    results: list[dict[str, Any]] = []
    for index, reference in enumerate(reference_sections):
        candidate = candidate_drops[index] if index < len(candidate_drops) else None
        if candidate is None:
            results.append(
                {
                    "referenceSectionId": reference["id"],
                    "sectionType": reference["type"],
                    "status": "missing_candidate",
                    "candidateSectionId": None,
                    "startErrorMilliseconds": None,
                    "endErrorMilliseconds": None,
                }
            )
            continue

        candidate_start = float(candidate["startSeconds"]) + timeline_offset_seconds
        candidate_end = float(candidate["endSeconds"]) + timeline_offset_seconds
        start_error = (candidate_start - float(reference["startSeconds"])) * 1000.0
        end_error = (candidate_end - float(reference["endSeconds"])) * 1000.0
        results.append(
            {
                "referenceSectionId": reference["id"],
                "sectionType": reference["type"],
                "candidateSectionId": candidate.get("id"),
                "status": "ok",
                "referenceStartSeconds": reference["startSeconds"],
                "referenceEndSeconds": reference["endSeconds"],
                "candidateStartSeconds": _round_float(candidate_start),
                "candidateEndSeconds": _round_float(candidate_end),
                "startErrorMilliseconds": _round_float(start_error),
                "endErrorMilliseconds": _round_float(end_error),
                "maxAbsoluteErrorMilliseconds": _round_float(max(abs(start_error), abs(end_error))),
            }
        )
    return results


def _comparison_duration(analyzed_artifact: dict[str, Any], rekordbox_track: RekordboxTrack) -> float:
    duration = _optional_float(analyzed_artifact.get("durationSeconds")) or 0.0
    cue_end = max((cue.start_seconds for cue in rekordbox_track.cues), default=0.0)
    tempo_start = rekordbox_track.tempos[0].start_seconds
    beat_end = max(
        (
            _optional_float(beat.get("timeSeconds")) or 0.0
            for beat in _iter_dicts(analyzed_artifact.get("beatGrid", {}).get("beats", ()))
        ),
        default=0.0,
    )
    return max(duration, cue_end, tempo_start, beat_end)


def _reference_beats(rekordbox_track: RekordboxTrack, duration_seconds: float) -> list[dict[str, float | int]]:
    tempo = rekordbox_track.tempos[0]
    period_seconds = 60.0 / tempo.bpm
    beat_count = max(0, int(math.floor((duration_seconds - tempo.start_seconds + 1e-9) / period_seconds)) + 1)
    return [
        {
            "index": index,
            "timeSeconds": _round_float(tempo.start_seconds + index * period_seconds),
        }
        for index in range(beat_count)
        if tempo.start_seconds + index * period_seconds <= duration_seconds + 1e-6
    ]


def _reference_cues(rekordbox_track: RekordboxTrack) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    for index, cue in enumerate(rekordbox_track.cues):
        cues.append(
            {
                "label": _cue_label(cue),
                "type": "drop" if index % 2 == 0 else "mix_out",
                "timeSeconds": _round_float(cue.start_seconds),
                "rekordboxNum": cue.num,
            }
        )
    return cues


def _reference_sections(rekordbox_track: RekordboxTrack) -> list[dict[str, Any]]:
    cues = list(rekordbox_track.cues)
    sections: list[dict[str, Any]] = []
    for pair_index in range(0, len(cues), 2):
        start_cue = cues[pair_index]
        if pair_index + 1 >= len(cues):
            continue
        end_cue = cues[pair_index + 1]
        if end_cue.start_seconds <= start_cue.start_seconds:
            continue
        sections.append(
            {
                "id": f"section-rekordbox-drop-{len(sections) + 1:03d}",
                "type": "drop",
                "startSeconds": _round_float(start_cue.start_seconds),
                "endSeconds": _round_float(end_cue.start_seconds),
            }
        )
    return sections


def _candidate_markers(
    markers: Any,
    *,
    timeline_offset_seconds: float,
) -> list[dict[str, float | int]]:
    results: list[dict[str, float | int]] = []
    for marker in _iter_dicts(markers):
        time_seconds = _optional_float(marker.get("timeSeconds"))
        if time_seconds is None:
            continue
        result: dict[str, float | int] = {
            "index": int(marker.get("index") or len(results)),
            "timeSeconds": _round_float(time_seconds + timeline_offset_seconds),
            "rawTimeSeconds": _round_float(time_seconds),
        }
        if "beatInBar" in marker:
            result["beatInBar"] = int(marker["beatInBar"])
        confidence = _optional_float(marker.get("confidence"))
        if confidence is not None:
            result["confidence"] = _round_float(confidence)
        results.append(result)
    results.sort(key=lambda item: float(item["timeSeconds"]))
    return results


def _nearest_signed_errors(candidate_times: list[float], reference_times: list[float]) -> list[float]:
    if not candidate_times or not reference_times:
        return []
    return [
        candidate_time - nearest
        for candidate_time in candidate_times
        if (nearest := _nearest_time(candidate_time, reference_times)) is not None
    ]


def _nearest_absolute_errors_ms(target_times: list[float], comparison_times: list[float]) -> list[float]:
    if not target_times or not comparison_times:
        return []
    return [
        abs(target_time - nearest) * 1000.0
        for target_time in target_times
        if (nearest := _nearest_time(target_time, comparison_times)) is not None
    ]


def _nearest_time(target: float, sorted_times: list[float]) -> float | None:
    if not sorted_times:
        return None
    index = bisect_left(sorted_times, target)
    candidates: list[float] = []
    if index < len(sorted_times):
        candidates.append(sorted_times[index])
    if index > 0:
        candidates.append(sorted_times[index - 1])
    return min(candidates, key=lambda time_seconds: abs(time_seconds - target))


def _nearest_unused_dict(
    target: float,
    candidates: list[dict[str, Any]],
    used_indexes: set[int],
) -> tuple[int, dict[str, Any] | None]:
    best_index = -1
    best: dict[str, Any] | None = None
    best_distance = math.inf
    for index, candidate in enumerate(candidates):
        if index in used_indexes:
            continue
        distance = abs(float(candidate["timeSeconds"]) - target)
        if distance < best_distance:
            best_index = index
            best = candidate
            best_distance = distance
    return best_index, best


def _load_json_object(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationError("evaluation_artifact_read_error", f"Could not read analyzed artifact: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationError("evaluation_artifact_parse_error", f"Could not parse analyzed artifact JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvaluationError("evaluation_invalid_artifact", "Analyzed artifact root must be a JSON object")
    return payload


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _iter_dicts(values: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(value for value in values if isinstance(value, dict))


def _cue_label(cue: RekordboxCue) -> str:
    if cue.num is None or cue.num < 0:
        return "unknown"
    return chr(ord("A") + cue.num) if cue.num < 26 else str(cue.num)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _round_optional(value: float | None) -> float | None:
    return None if value is None else _round_float(value)


def _round_optional_abs_error(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return _round_float(abs(left - right))


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _within_threshold_ratio(values: list[float], threshold: float) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value <= threshold) / len(values)


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded
