"""Explainable drop-start candidate ranking from analyzed-track artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .cache import SCHEMA_VERSION, write_json_atomic


DROP_ANCHOR_RANKER_NAME = "autodj-drop-anchor-ranker"
DROP_ANCHOR_RANKER_VERSION = "weighted-features-v2"


class DropAnchorRankerError(ValueError):
    """Expected drop-anchor ranking failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class DropAnchorRankerOptions:
    max_candidates: int = 16
    beats_per_bar: int = 4
    min_start_bars: float = 2.0
    end_guard_bars: float = 8.0
    boundary_tolerance_seconds: float = 0.75


@dataclass(frozen=True)
class DropAnchorCandidate:
    rank: int
    time_seconds: float
    beat_index: int
    bar_beat: str
    score: float
    features: dict[str, float]
    reasons: tuple[str, ...]
    nearby_sections: tuple[str, ...]
    nearby_cues: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "timeSeconds": _round_float(self.time_seconds),
            "beatIndex": self.beat_index,
            "barBeat": self.bar_beat,
            "score": _round_float(self.score),
            "features": {key: _round_float(value) for key, value in self.features.items()},
            "reasons": list(self.reasons),
            "nearbySections": list(self.nearby_sections),
            "nearbyCues": list(self.nearby_cues),
        }


def rank_drop_anchors_file(
    analyzed_track_path: str | Path,
    output_path: str | Path,
    *,
    options: DropAnchorRankerOptions | None = None,
) -> Path:
    """Rank likely drop-start anchors for an analyzed-track JSON file."""

    analyzed_track_path = Path(analyzed_track_path)
    try:
        artifact = json.loads(analyzed_track_path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise DropAnchorRankerError("analyzed_track_read_error", f"Could not read analyzed track: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DropAnchorRankerError("analyzed_track_parse_error", f"Could not parse analyzed-track JSON: {exc}") from exc
    if not isinstance(artifact, dict):
        raise DropAnchorRankerError("analyzed_track_invalid", "Analyzed-track root must be an object")

    ranking = rank_drop_anchors(artifact, options=options)
    return write_json_atomic(output_path, ranking)


def rank_drop_anchors(
    artifact: dict[str, Any],
    *,
    options: DropAnchorRankerOptions | None = None,
) -> dict[str, Any]:
    """Return an explainable ranked list of likely drop-start anchors."""

    options = options or DropAnchorRankerOptions()
    if options.max_candidates <= 0:
        raise DropAnchorRankerError("invalid_options", "max_candidates must be greater than zero")
    if options.beats_per_bar <= 0:
        raise DropAnchorRankerError("invalid_options", "beats_per_bar must be greater than zero")

    beats = _beats_from_artifact(artifact)
    if len(beats) < options.beats_per_bar * 4:
        raise DropAnchorRankerError("missing_beatgrid", "Analyzed track must contain a usable beat grid")

    beat_seconds = _median([beats[index + 1][1] - beats[index][1] for index in range(len(beats) - 1)])
    if beat_seconds <= 0:
        raise DropAnchorRankerError("invalid_beatgrid", "Beat grid has a non-positive beat period")
    bar_seconds = beat_seconds * options.beats_per_bar
    duration_seconds = _duration_seconds(artifact, beats)
    curves = _curves_from_artifact(artifact)

    scored: list[DropAnchorCandidate] = []
    for beat_index, beat_time in beats:
        if beat_time < options.min_start_bars * bar_seconds:
            continue
        if beat_time > max(0.0, duration_seconds - options.end_guard_bars * bar_seconds):
            continue
        features = _candidate_features(
            beat_time,
            beat_index=beat_index,
            beats_per_bar=options.beats_per_bar,
            bar_seconds=bar_seconds,
            curves=curves,
            artifact=artifact,
            boundary_tolerance_seconds=options.boundary_tolerance_seconds,
        )
        score = _candidate_score(features)
        sections = _nearby_section_labels(
            artifact,
            beat_time,
            tolerance_seconds=options.boundary_tolerance_seconds,
        )
        cues = _nearby_cue_labels(
            artifact,
            beat_time,
            tolerance_seconds=options.boundary_tolerance_seconds,
        )
        scored.append(
            DropAnchorCandidate(
                rank=0,
                time_seconds=beat_time,
                beat_index=beat_index,
                bar_beat=_bar_beat_label(beat_index, options.beats_per_bar),
                score=score,
                features=features,
                reasons=_candidate_reasons(features),
                nearby_sections=sections,
                nearby_cues=cues,
            )
        )

    deduped = _dedupe_close_candidates(
        sorted(scored, key=lambda candidate: (-candidate.score, candidate.time_seconds)),
        min_gap_seconds=max(1.0, 4.0 * bar_seconds),
    )
    ranked = [
        DropAnchorCandidate(
            rank=index + 1,
            time_seconds=candidate.time_seconds,
            beat_index=candidate.beat_index,
            bar_beat=candidate.bar_beat,
            score=candidate.score,
            features=candidate.features,
            reasons=candidate.reasons,
            nearby_sections=candidate.nearby_sections,
            nearby_cues=candidate.nearby_cues,
        )
        for index, candidate in enumerate(deduped[: options.max_candidates])
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "artifact": "drop-anchor-ranking",
        "ranker": {
            "name": DROP_ANCHOR_RANKER_NAME,
            "version": DROP_ANCHOR_RANKER_VERSION,
            "producerVersion": __version__,
        },
        "trackId": str(artifact.get("trackId") or ""),
        "parameters": {
            "maxCandidates": options.max_candidates,
            "beatsPerBar": options.beats_per_bar,
            "minStartBars": options.min_start_bars,
            "endGuardBars": options.end_guard_bars,
            "boundaryToleranceSeconds": options.boundary_tolerance_seconds,
        },
        "beatSeconds": _round_float(beat_seconds),
        "barSeconds": _round_float(bar_seconds),
        "candidateCount": len(scored),
        "candidates": [candidate.to_dict() for candidate in ranked],
    }


def _candidate_features(
    time_seconds: float,
    *,
    beat_index: int,
    beats_per_bar: int,
    bar_seconds: float,
    curves: dict[str, tuple[tuple[float, float], ...]],
    artifact: dict[str, Any],
    boundary_tolerance_seconds: float,
) -> dict[str, float]:
    pre_close_start = max(0.0, time_seconds - 4.0 * bar_seconds)
    pre_far_start = max(0.0, time_seconds - 16.0 * bar_seconds)
    pre_far_end = max(pre_far_start, time_seconds - 8.0 * bar_seconds)
    post_short_end = time_seconds + 4.0 * bar_seconds
    post_long_end = time_seconds + 8.0 * bar_seconds

    before_energy = _mean_curve(curves["energy"], pre_close_start, time_seconds)
    after_energy = _mean_curve(curves["energy"], time_seconds, post_short_end)
    after_energy_long = _mean_curve(curves["energy"], time_seconds, post_long_end)
    far_energy = _mean_curve(curves["energy"], pre_far_start, pre_far_end)
    before_bass = _mean_curve(curves["bass"], pre_close_start, time_seconds)
    after_bass = _mean_curve(curves["bass"], time_seconds, post_long_end)
    onset_peak = _max_curve(curves["onset"], time_seconds - 0.25, time_seconds + 0.45)

    energy_jump = after_energy - before_energy
    bass_jump = after_bass - before_bass
    build_slope = max(0.0, before_energy - far_energy)
    section_support = _section_support(artifact, time_seconds, boundary_tolerance_seconds)
    cue_support = _cue_support(artifact, time_seconds, boundary_tolerance_seconds)
    phrase_support = _phrase_support(beat_index, beats_per_bar)
    brick_wall_support = 1.0 if after_energy_long >= 0.68 and after_bass >= 0.52 and onset_peak >= 0.48 else 0.0

    return {
        "beforeEnergy": before_energy,
        "afterEnergy": after_energy,
        "afterEnergySustain": after_energy_long,
        "farPreEnergy": far_energy,
        "energyJump": energy_jump,
        "beforeBassEnergy": before_bass,
        "afterBassEnergy": after_bass,
        "bassJump": bass_jump,
        "onsetPeak": onset_peak,
        "buildSlope": build_slope,
        "phraseSupport": phrase_support,
        "sectionSupport": section_support,
        "cueSupport": cue_support,
        "brickWallSupport": brick_wall_support,
    }


def _candidate_score(features: dict[str, float]) -> float:
    score = (
        0.196 * _positive(features["energyJump"])
        + 0.281 * _positive(features["bassJump"])
        + 0.137 * features["afterBassEnergy"]
        + 0.095 * features["afterEnergySustain"]
        + 0.129 * features["onsetPeak"]
        + 0.086 * features["buildSlope"]
        + 0.152 * features["phraseSupport"]
        + 0.037 * features["sectionSupport"]
        + 0.003 * features["cueSupport"]
        + 0.008 * features["brickWallSupport"]
    )
    energy_collapse_penalty = 0.051 if features["afterEnergySustain"] < 0.32 and features["afterBassEnergy"] < 0.28 else 0.0
    intro_like_penalty = 0.06 if features["beforeEnergy"] < 0.08 and features["afterEnergySustain"] < 0.42 else 0.0
    return max(0.0, min(1.0, score - energy_collapse_penalty - intro_like_penalty))


def _candidate_reasons(features: dict[str, float]) -> tuple[str, ...]:
    reasons: list[str] = []
    if features["energyJump"] >= 0.12:
        reasons.append("energy_jump")
    if features["bassJump"] >= 0.10 or features["afterBassEnergy"] >= 0.50:
        reasons.append("bass_impact")
    if features["onsetPeak"] >= 0.55:
        reasons.append("strong_transient")
    if features["buildSlope"] >= 0.08:
        reasons.append("pre_drop_build_slope")
    if features["phraseSupport"] >= 0.85:
        reasons.append("phrase_aligned")
    if features["sectionSupport"] > 0.0:
        reasons.append("section_boundary_support")
    if features["brickWallSupport"] > 0.0:
        reasons.append("brick_wall_drop_support")
    return tuple(reasons or ["weak_signal_candidate"])


def _dedupe_close_candidates(candidates: Sequence[DropAnchorCandidate], *, min_gap_seconds: float) -> list[DropAnchorCandidate]:
    selected: list[DropAnchorCandidate] = []
    for candidate in candidates:
        if all(abs(candidate.time_seconds - existing.time_seconds) >= min_gap_seconds for existing in selected):
            selected.append(candidate)
    return selected


def _beats_from_artifact(artifact: dict[str, Any]) -> tuple[tuple[int, float], ...]:
    beat_grid = artifact.get("beatGrid") if isinstance(artifact.get("beatGrid"), dict) else {}
    beats = []
    for raw in beat_grid.get("beats") if isinstance(beat_grid.get("beats"), list) else []:
        if not isinstance(raw, dict):
            continue
        index = _optional_int(raw.get("index"))
        seconds = _optional_float(raw.get("timeSeconds"))
        if index is None or seconds is None or seconds < 0:
            continue
        beats.append((index, seconds))
    return tuple(sorted(beats, key=lambda item: item[0]))


def _curves_from_artifact(artifact: dict[str, Any]) -> dict[str, tuple[tuple[float, float], ...]]:
    energy = artifact.get("energy") if isinstance(artifact.get("energy"), dict) else {}
    return {
        "energy": _curve_points(energy.get("curve")),
        "bass": _curve_points(energy.get("bassEnergyCurve")),
        "onset": _curve_points(energy.get("onsetDensityCurve")),
    }


def _curve_points(raw_curve: Any) -> tuple[tuple[float, float], ...]:
    points = []
    if not isinstance(raw_curve, list):
        return ()
    for raw in raw_curve:
        if not isinstance(raw, dict):
            continue
        time_seconds = _optional_float(raw.get("timeSeconds"))
        value = _optional_float(raw.get("value"))
        if time_seconds is None or value is None:
            continue
        points.append((time_seconds, max(0.0, min(1.0, value))))
    return tuple(sorted(points))


def _mean_curve(points: Sequence[tuple[float, float]], start: float, end: float) -> float:
    values = [value for time_seconds, value in points if start <= time_seconds < end]
    if not values and points:
        midpoint = (start + end) / 2.0
        nearest = min(points, key=lambda point: abs(point[0] - midpoint))
        values = [nearest[1]]
    return sum(values) / len(values) if values else 0.0


def _max_curve(points: Sequence[tuple[float, float]], start: float, end: float) -> float:
    values = [value for time_seconds, value in points if start <= time_seconds <= end]
    return max(values) if values else 0.0


def _section_support(artifact: dict[str, Any], time_seconds: float, tolerance_seconds: float) -> float:
    support = 0.0
    for section in artifact.get("sections", []):
        if not isinstance(section, dict):
            continue
        section_type = str(section.get("type") or "")
        start = _optional_float(section.get("startSeconds"))
        end = _optional_float(section.get("endSeconds"))
        if start is not None and abs(start - time_seconds) <= tolerance_seconds:
            support = max(support, 1.0 if section_type == "drop" else 0.45)
        if end is not None and abs(end - time_seconds) <= tolerance_seconds:
            support = max(support, 0.35)
    return support


def _cue_support(artifact: dict[str, Any], time_seconds: float, tolerance_seconds: float) -> float:
    support = 0.0
    for cue in artifact.get("cuePoints", []):
        if not isinstance(cue, dict):
            continue
        cue_type = str(cue.get("type") or "")
        cue_time = _optional_float(cue.get("timeSeconds"))
        if cue_time is not None and abs(cue_time - time_seconds) <= tolerance_seconds:
            support = max(support, 1.0 if cue_type == "drop" else 0.35)
    return support


def _nearby_section_labels(artifact: dict[str, Any], time_seconds: float, *, tolerance_seconds: float) -> tuple[str, ...]:
    labels = []
    for section in artifact.get("sections", []):
        if not isinstance(section, dict):
            continue
        section_type = str(section.get("type") or "")
        start = _optional_float(section.get("startSeconds"))
        if section_type and start is not None and abs(start - time_seconds) <= tolerance_seconds:
            labels.append(f"{section.get('id', section_type)}:{section_type}")
    return tuple(labels)


def _nearby_cue_labels(artifact: dict[str, Any], time_seconds: float, *, tolerance_seconds: float) -> tuple[str, ...]:
    labels = []
    for cue in artifact.get("cuePoints", []):
        if not isinstance(cue, dict):
            continue
        cue_type = str(cue.get("type") or "")
        cue_time = _optional_float(cue.get("timeSeconds"))
        if cue_type and cue_time is not None and abs(cue_time - time_seconds) <= tolerance_seconds:
            labels.append(f"{cue.get('id', cue_type)}:{cue_type}")
    return tuple(labels)


def _phrase_support(beat_index: int, beats_per_bar: int) -> float:
    beat_position = beat_index % beats_per_bar
    if beat_position != 0:
        if beats_per_bar % 2 == 0 and beat_position == beats_per_bar // 2:
            return 0.42
        return 0.08
    bar_index = beat_index // beats_per_bar
    if bar_index % 16 == 0:
        return 1.0
    if bar_index % 8 == 0:
        return 0.86
    if bar_index % 4 == 0:
        return 0.68
    return 0.35


def _bar_beat_label(beat_index: int, beats_per_bar: int) -> str:
    return f"{beat_index // beats_per_bar + 1}.{beat_index % beats_per_bar + 1}"


def _duration_seconds(artifact: dict[str, Any], beats: Sequence[tuple[int, float]]) -> float:
    duration = _optional_float(artifact.get("durationSeconds"))
    if duration is not None and duration > 0:
        return duration
    return max((time_seconds for _index, time_seconds in beats), default=0.0)


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return float((ordered[middle - 1] + ordered[middle]) / 2.0)


def _positive(value: float) -> float:
    return max(0.0, min(1.0, value))


def _optional_float(value: Any) -> float | None:
    if isinstance(value, int | float):
        result = float(value)
        return result if math.isfinite(result) else None
    return None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int):
        return int(value)
    return None


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded
