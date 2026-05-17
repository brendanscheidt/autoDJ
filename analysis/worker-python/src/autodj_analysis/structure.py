"""Conservative rough section and cue-candidate heuristics."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .features import EnergyFeatures
from .tempo import TempoFeatures


DEFAULT_HIGH_ENERGY_THRESHOLD = 0.65
DEFAULT_LOW_ENERGY_THRESHOLD = 0.35
DEFAULT_MIN_SECTION_SECONDS = 0.75
DEFAULT_CUE_SNAP_SECONDS = 0.25
DEFAULT_DROP_MERGE_GAP_SECONDS = 4.5
DEFAULT_MIN_DROP_SECONDS = 2.0
MIN_STRUCTURE_DYNAMIC_RANGE = 0.25
MIN_STRUCTURE_PEAK_ENERGY = 0.20
HEURISTIC_STRUCTURE_WARNING = (
    "Rough sections and cue candidates are heuristic energy/onset estimates, "
    "not production-grade structure detection."
)


class StructureExtractionError(ValueError):
    """Expected rough structure extraction failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class StructureFeatures:
    sections: tuple[dict[str, Any], ...]
    cue_points: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    backend: str
    high_energy_threshold: float
    low_energy_threshold: float


@dataclass(frozen=True)
class _CurveWindow:
    start_index: int
    end_index: int
    start_seconds: float
    end_seconds: float


def compute_structure_features(
    energy_features: EnergyFeatures,
    *,
    tempo_features: TempoFeatures | None = None,
    duration_seconds: float | None = None,
    high_energy_threshold: float = DEFAULT_HIGH_ENERGY_THRESHOLD,
    low_energy_threshold: float = DEFAULT_LOW_ENERGY_THRESHOLD,
    min_section_seconds: float = DEFAULT_MIN_SECTION_SECONDS,
    cue_snap_seconds: float = DEFAULT_CUE_SNAP_SECONDS,
) -> StructureFeatures:
    """Find conservative rough sections and cue candidates from extracted features."""

    _validate_structure_parameters(
        high_energy_threshold=high_energy_threshold,
        low_energy_threshold=low_energy_threshold,
        min_section_seconds=min_section_seconds,
        cue_snap_seconds=cue_snap_seconds,
    )

    curve = tuple(energy_features.curve)
    if not curve:
        return _weak_structure_features(
            high_energy_threshold=high_energy_threshold,
            low_energy_threshold=low_energy_threshold,
            warning="Rough section/cue analysis skipped because the energy curve is empty.",
        )

    values = [float(point["value"]) for point in curve]
    times = [float(point["timeSeconds"]) for point in curve]
    duration = _duration_seconds(times, duration_seconds)
    peak = max(values)
    floor = min(values)
    dynamic_range = peak - floor
    if peak < MIN_STRUCTURE_PEAK_ENERGY or dynamic_range < MIN_STRUCTURE_DYNAMIC_RANGE:
        return _weak_structure_features(
            high_energy_threshold=high_energy_threshold,
            low_energy_threshold=low_energy_threshold,
            warning=(
                "Rough section/cue analysis found weak energy contrast; "
                "leaving sections and cue points empty."
            ),
        )

    high_threshold = max(high_energy_threshold, floor + dynamic_range * 0.65)
    low_threshold = min(low_energy_threshold, floor + dynamic_range * 0.30)
    high_windows = _merge_close_windows(
        _runs(
            values,
            times,
            duration,
            predicate=lambda value: value >= high_threshold,
            min_duration_seconds=min_section_seconds,
        ),
        max_gap_seconds=DEFAULT_DROP_MERGE_GAP_SECONDS,
    )
    high_windows = [
        window
        for window in high_windows
        if window.end_seconds - window.start_seconds >= max(min_section_seconds, DEFAULT_MIN_DROP_SECONDS)
    ]
    if not high_windows:
        return _weak_structure_features(
            high_energy_threshold=high_energy_threshold,
            low_energy_threshold=low_energy_threshold,
            warning=(
                "Rough section/cue analysis found no sustained high-energy region; "
                "leaving sections and cue points empty."
            ),
        )

    first_high_window = min(high_windows, key=lambda window: window.start_seconds)
    last_high_window = max(high_windows, key=lambda window: window.end_seconds)
    warnings = [HEURISTIC_STRUCTURE_WARNING]
    sections: list[dict[str, Any]] = []
    cue_points: list[dict[str, Any]] = []

    intro_window = _initial_low_window(values, times, duration, low_threshold, min_section_seconds)
    if intro_window is not None and intro_window.end_seconds <= first_high_window.start_seconds:
        sections.append(
            _section(
                "section-intro-001",
                "intro",
                intro_window,
                values,
                tempo_features=tempo_features,
                confidence=0.50,
            )
        )
        cue_points.append(
            _cue_point(
                "cue-mix-in-001",
                "mix_in",
                intro_window.start_seconds,
                confidence=0.50,
                section_id="section-intro-001",
                tempo_features=tempo_features,
                cue_snap_seconds=cue_snap_seconds,
                tags=("rough", "low_energy_intro"),
            )
        )

    build_window = _build_window_before_drop(
        values,
        times,
        first_high_window,
        duration,
        low_threshold,
        min_section_seconds,
    )
    if build_window is not None:
        build_confidence = _build_confidence(values, build_window)
        sections.append(
            _section(
                "section-build-001",
                "build",
                build_window,
                values,
                tempo_features=tempo_features,
                confidence=build_confidence,
            )
        )
        cue_points.append(
            _cue_point(
                "cue-build-start-001",
                "build_start",
                build_window.start_seconds,
                confidence=build_confidence,
                section_id="section-build-001",
                tempo_features=tempo_features,
                cue_snap_seconds=cue_snap_seconds,
                tags=("rough", "rising_energy"),
            )
        )

    for drop_index, high_window in enumerate(high_windows, start=1):
        section_id = f"section-drop-{drop_index:03d}"
        drop_confidence = _drop_confidence(
            values,
            high_window,
            energy_features=energy_features,
        )
        sections.append(
            _section(
                section_id,
                "drop",
                high_window,
                values,
                tempo_features=tempo_features,
                confidence=drop_confidence,
            )
        )
        cue_points.append(
            _cue_point(
                f"cue-drop-{drop_index:03d}",
                "drop",
                high_window.start_seconds,
                confidence=drop_confidence,
                section_id=section_id,
                tempo_features=tempo_features,
                cue_snap_seconds=cue_snap_seconds,
                tags=("rough", "high_energy_plateau"),
            )
        )
        if high_window.end_seconds < duration - min_section_seconds:
            cue_points.append(
                _cue_point(
                    f"cue-drop-end-{drop_index:03d}",
                    "mix_out",
                    high_window.end_seconds,
                    confidence=max(0.45, drop_confidence - 0.08),
                    section_id=section_id,
                    tempo_features=tempo_features,
                    cue_snap_seconds=cue_snap_seconds,
                    tags=("rough", "drop_end"),
                    snap_direction="floor",
                )
            )

    outro_window = _final_low_window(values, times, duration, low_threshold, min_section_seconds)
    if outro_window is not None and outro_window.start_seconds >= last_high_window.end_seconds:
        sections.append(
            _section(
                "section-outro-001",
                "outro",
                outro_window,
                values,
                tempo_features=tempo_features,
                confidence=0.50,
            )
        )
        if not _has_nearby_cue(cue_points, cue_type="mix_out", time_seconds=outro_window.start_seconds):
            cue_points.append(
                _cue_point(
                    "cue-mix-out-001",
                    "mix_out",
                    outro_window.start_seconds,
                    confidence=0.50,
                    section_id="section-outro-001",
                    tempo_features=tempo_features,
                    cue_snap_seconds=cue_snap_seconds,
                    tags=("rough", "low_energy_outro"),
                )
            )

    sections.sort(key=lambda section: float(section["startSeconds"]))
    cue_points.sort(key=lambda cue: float(cue["timeSeconds"]))

    return StructureFeatures(
        sections=tuple(sections),
        cue_points=tuple(cue_points),
        warnings=tuple(warnings),
        backend="heuristic-energy-onset-v1",
        high_energy_threshold=_round_float(high_threshold),
        low_energy_threshold=_round_float(low_threshold),
    )


def build_sections(features: StructureFeatures) -> list[dict[str, Any]]:
    """Convert rough structure features to AnalyzedTrack sections."""

    return [dict(section) for section in features.sections]


def build_cue_points(features: StructureFeatures) -> list[dict[str, Any]]:
    """Convert rough structure features to AnalyzedTrack cue points."""

    return [dict(cue_point) for cue_point in features.cue_points]


def _validate_structure_parameters(
    *,
    high_energy_threshold: float,
    low_energy_threshold: float,
    min_section_seconds: float,
    cue_snap_seconds: float,
) -> None:
    if not 0.0 < high_energy_threshold <= 1.0:
        raise StructureExtractionError(
            "structure_invalid_parameters",
            "high_energy_threshold must be within (0.0, 1.0]",
        )
    if not 0.0 <= low_energy_threshold < 1.0:
        raise StructureExtractionError(
            "structure_invalid_parameters",
            "low_energy_threshold must be within [0.0, 1.0)",
        )
    if low_energy_threshold >= high_energy_threshold:
        raise StructureExtractionError(
            "structure_invalid_parameters",
            "low_energy_threshold must be less than high_energy_threshold",
        )
    if min_section_seconds <= 0:
        raise StructureExtractionError(
            "structure_invalid_parameters",
            "min_section_seconds must be greater than zero",
        )
    if cue_snap_seconds < 0:
        raise StructureExtractionError(
            "structure_invalid_parameters",
            "cue_snap_seconds must be greater than or equal to zero",
        )


def _weak_structure_features(
    *,
    high_energy_threshold: float,
    low_energy_threshold: float,
    warning: str,
) -> StructureFeatures:
    return StructureFeatures(
        sections=(),
        cue_points=(),
        warnings=(HEURISTIC_STRUCTURE_WARNING, warning),
        backend="heuristic-energy-onset-v1",
        high_energy_threshold=high_energy_threshold,
        low_energy_threshold=low_energy_threshold,
    )


def _duration_seconds(times: list[float], duration_seconds: float | None) -> float:
    if duration_seconds is not None and duration_seconds > 0:
        return duration_seconds
    if not times:
        return 0.0
    if len(times) == 1:
        return times[0]
    step = _median([later - earlier for earlier, later in zip(times, times[1:]) if later > earlier])
    return times[-1] + max(step, 0.0)


def _longest_run(
    values: list[float],
    times: list[float],
    duration_seconds: float,
    *,
    predicate,
    min_duration_seconds: float,
) -> _CurveWindow | None:
    best: _CurveWindow | None = None
    run_start: int | None = None

    for index, value in enumerate(values):
        if predicate(value):
            if run_start is None:
                run_start = index
            continue
        if run_start is not None:
            best = _select_better_window(
                best,
                _window(run_start, index, times, duration_seconds),
                min_duration_seconds,
            )
            run_start = None

    if run_start is not None:
        best = _select_better_window(
            best,
            _window(run_start, len(values), times, duration_seconds),
            min_duration_seconds,
        )
    return best


def _runs(
    values: list[float],
    times: list[float],
    duration_seconds: float,
    *,
    predicate,
    min_duration_seconds: float,
) -> list[_CurveWindow]:
    windows: list[_CurveWindow] = []
    run_start: int | None = None

    for index, value in enumerate(values):
        if predicate(value):
            if run_start is None:
                run_start = index
            continue
        if run_start is not None:
            candidate = _window(run_start, index, times, duration_seconds)
            if candidate.end_seconds - candidate.start_seconds >= min_duration_seconds:
                windows.append(candidate)
            run_start = None

    if run_start is not None:
        candidate = _window(run_start, len(values), times, duration_seconds)
        if candidate.end_seconds - candidate.start_seconds >= min_duration_seconds:
            windows.append(candidate)
    return windows


def _merge_close_windows(
    windows: list[_CurveWindow],
    *,
    max_gap_seconds: float,
) -> list[_CurveWindow]:
    if not windows:
        return []

    merged = [windows[0]]
    for window in windows[1:]:
        current = merged[-1]
        if window.start_seconds - current.end_seconds <= max_gap_seconds:
            merged[-1] = _CurveWindow(
                start_index=current.start_index,
                end_index=window.end_index,
                start_seconds=current.start_seconds,
                end_seconds=window.end_seconds,
            )
        else:
            merged.append(window)
    return merged


def _select_better_window(
    current: _CurveWindow | None,
    candidate: _CurveWindow,
    min_duration_seconds: float,
) -> _CurveWindow | None:
    if candidate.end_seconds - candidate.start_seconds < min_duration_seconds:
        return current
    if current is None:
        return candidate
    current_duration = current.end_seconds - current.start_seconds
    candidate_duration = candidate.end_seconds - candidate.start_seconds
    if candidate_duration > current_duration:
        return candidate
    return current


def _initial_low_window(
    values: list[float],
    times: list[float],
    duration_seconds: float,
    low_threshold: float,
    min_section_seconds: float,
) -> _CurveWindow | None:
    end_index = 0
    while end_index < len(values) and values[end_index] <= low_threshold:
        end_index += 1
    if end_index == 0:
        return None
    candidate = _window(0, end_index, times, duration_seconds)
    if candidate.end_seconds - candidate.start_seconds < min_section_seconds:
        return None
    return candidate


def _final_low_window(
    values: list[float],
    times: list[float],
    duration_seconds: float,
    low_threshold: float,
    min_section_seconds: float,
) -> _CurveWindow | None:
    start_index = len(values)
    while start_index > 0 and values[start_index - 1] <= low_threshold:
        start_index -= 1
    if start_index == len(values):
        return None
    candidate = _window(start_index, len(values), times, duration_seconds)
    if candidate.end_seconds - candidate.start_seconds < min_section_seconds:
        return None
    return candidate


def _build_window_before_drop(
    values: list[float],
    times: list[float],
    high_window: _CurveWindow,
    duration_seconds: float,
    low_threshold: float,
    min_section_seconds: float,
) -> _CurveWindow | None:
    if high_window.start_index <= 0:
        return None

    start_index = high_window.start_index - 1
    while start_index > 0 and values[start_index] > low_threshold:
        start_index -= 1
    if values[start_index] <= low_threshold and start_index < high_window.start_index - 1:
        start_index += 1

    candidate = _window(start_index, high_window.start_index, times, duration_seconds)
    if candidate.end_seconds - candidate.start_seconds < min_section_seconds:
        return None
    if values[high_window.start_index - 1] <= values[start_index]:
        return None
    return candidate


def _window(
    start_index: int,
    end_index: int,
    times: list[float],
    duration_seconds: float,
) -> _CurveWindow:
    end_index = max(start_index + 1, min(end_index, len(times)))
    start_seconds = times[start_index]
    end_seconds = duration_seconds if end_index >= len(times) else times[end_index]
    return _CurveWindow(
        start_index=start_index,
        end_index=end_index,
        start_seconds=_round_float(start_seconds),
        end_seconds=_round_float(max(end_seconds, start_seconds)),
    )


def _section(
    section_id: str,
    section_type: str,
    window: _CurveWindow,
    values: list[float],
    *,
    tempo_features: TempoFeatures | None,
    confidence: float,
) -> dict[str, Any]:
    window_values = values[window.start_index : window.end_index]
    section: dict[str, Any] = {
        "id": section_id,
        "type": section_type,
        "startSeconds": window.start_seconds,
        "endSeconds": window.end_seconds,
        "energyMean": _round_float(_mean(window_values)),
        "energyPeak": _round_float(max(window_values) if window_values else 0.0),
        "confidence": _round_float(_clamp(confidence)),
    }
    start_snap = _nearest_beat(window.start_seconds, tempo_features)
    end_snap = (
        _beat_at_or_before(window.end_seconds, tempo_features)
        if section_type == "drop"
        else _nearest_beat(window.end_seconds, tempo_features)
    )
    if start_snap is not None:
        section["startBeatIndex"] = start_snap[0]
        section["startSeconds"] = start_snap[1]
    if end_snap is not None:
        section["endBeatIndex"] = end_snap[0]
        section["endSeconds"] = end_snap[1]
    return section


def _cue_point(
    cue_id: str,
    cue_type: str,
    time_seconds: float,
    *,
    confidence: float,
    section_id: str,
    tempo_features: TempoFeatures | None,
    cue_snap_seconds: float,
    tags: tuple[str, ...],
    snap_direction: str = "nearest",
) -> dict[str, Any]:
    cue: dict[str, Any] = {
        "id": cue_id,
        "type": cue_type,
        "timeSeconds": _round_float(time_seconds),
        "sectionId": section_id,
        "confidence": _round_float(_clamp(confidence)),
        "tags": list(tags),
    }
    snap = (
        _beat_at_or_before(time_seconds, tempo_features, max_distance_seconds=cue_snap_seconds)
        if snap_direction == "floor"
        else _nearest_beat(time_seconds, tempo_features, max_distance_seconds=cue_snap_seconds)
    )
    if snap is not None:
        beat_index, beat_time = snap
        cue["timeSeconds"] = beat_time
        cue["beatIndex"] = beat_index
        cue["tags"].append("beat_snapped")
    return cue


def _nearest_beat(
    time_seconds: float,
    tempo_features: TempoFeatures | None,
    *,
    max_distance_seconds: float = DEFAULT_CUE_SNAP_SECONDS,
) -> tuple[int, float] | None:
    if tempo_features is None or tempo_features.beat_grid_confidence < 0.65:
        return None
    if not tempo_features.beats:
        return None

    nearest = min(
        tempo_features.beats,
        key=lambda beat: abs(float(beat["timeSeconds"]) - time_seconds),
    )
    distance = abs(float(nearest["timeSeconds"]) - time_seconds)
    if distance > max_distance_seconds:
        return None
    return int(nearest["index"]), _round_float(float(nearest["timeSeconds"]))


def _beat_at_or_before(
    time_seconds: float,
    tempo_features: TempoFeatures | None,
    *,
    max_distance_seconds: float = DEFAULT_CUE_SNAP_SECONDS,
) -> tuple[int, float] | None:
    if tempo_features is None or tempo_features.beat_grid_confidence < 0.65:
        return None
    candidates = [
        beat
        for beat in tempo_features.beats
        if float(beat["timeSeconds"]) <= time_seconds + 1e-9
    ]
    if not candidates:
        return None
    beat = max(candidates, key=lambda item: float(item["timeSeconds"]))
    distance = time_seconds - float(beat["timeSeconds"])
    if distance > max_distance_seconds:
        return None
    return int(beat["index"]), _round_float(float(beat["timeSeconds"]))


def _has_nearby_cue(
    cue_points: list[dict[str, Any]],
    *,
    cue_type: str,
    time_seconds: float,
    max_distance_seconds: float = 2.0,
) -> bool:
    return any(
        cue.get("type") == cue_type
        and abs(float(cue.get("timeSeconds", math.inf)) - time_seconds) <= max_distance_seconds
        for cue in cue_points
    )


def _drop_confidence(
    values: list[float],
    window: _CurveWindow,
    *,
    energy_features: EnergyFeatures,
) -> float:
    window_values = values[window.start_index : window.end_index]
    duration_score = min((window.end_seconds - window.start_seconds) / 8.0, 1.0)
    energy_score = _mean(window_values)
    bass_score = _mean_window_curve(energy_features.bass_energy_curve, window)
    onset_score = _max_window_curve(energy_features.onset_density_curve, window)
    confidence = 0.35 + 0.25 * energy_score + 0.15 * bass_score + 0.05 * onset_score + 0.05 * duration_score
    return min(0.80, _clamp(confidence))


def _build_confidence(values: list[float], window: _CurveWindow) -> float:
    window_values = values[window.start_index : window.end_index]
    if len(window_values) < 2:
        return 0.45
    rise = max(0.0, window_values[-1] - window_values[0])
    return _clamp(0.45 + 0.25 * rise + 0.10 * min(len(window_values) / 8.0, 1.0))


def _mean_window_curve(curve: tuple[dict[str, float], ...], window: _CurveWindow) -> float:
    values = [
        float(point["value"])
        for point in curve
        if window.start_seconds <= float(point["timeSeconds"]) <= window.end_seconds
    ]
    return _mean(values)


def _max_window_curve(curve: tuple[dict[str, float], ...], window: _CurveWindow) -> float:
    values = [
        float(point["value"])
        for point in curve
        if window.start_seconds <= float(point["timeSeconds"]) <= window.end_seconds
    ]
    return max(values) if values else 0.0


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded
