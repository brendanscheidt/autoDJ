"""Deterministic source-time mapping for constant tempo-stretched audio."""

from __future__ import annotations

import math
from typing import Any, Iterable


def validate_tempo_ratio(tempo_ratio: float) -> float:
    """Return a finite positive tempo ratio or raise ValueError."""

    if not math.isfinite(tempo_ratio) or tempo_ratio <= 0.0:
        raise ValueError("tempo_ratio must be finite and greater than zero")
    return float(tempo_ratio)


def source_seconds_to_stretched_seconds(source_seconds: float, *, tempo_ratio: float) -> float:
    """Map original source seconds onto a pre-rendered stretched audio file."""

    return float(source_seconds) / validate_tempo_ratio(tempo_ratio)


def stretched_seconds_to_source_seconds(stretched_seconds: float, *, tempo_ratio: float) -> float:
    """Map seconds in a stretched audio file back to original source seconds."""

    return float(stretched_seconds) * validate_tempo_ratio(tempo_ratio)


def source_offset_to_timeline_offset(source_offset_seconds: float, *, tempo_ratio: float) -> float:
    """Convert a source-time offset into audible timeline offset after stretching."""

    return source_seconds_to_stretched_seconds(source_offset_seconds, tempo_ratio=tempo_ratio)


def source_nudge_for_rendered_alignment(
    *,
    outgoing_source_offset_seconds: float,
    outgoing_tempo_ratio: float,
    incoming_source_offset_seconds: float,
    incoming_tempo_ratio: float,
) -> float:
    """Return the incoming source-start nudge needed to align rendered transients."""

    outgoing_timeline_offset = source_offset_to_timeline_offset(
        outgoing_source_offset_seconds,
        tempo_ratio=outgoing_tempo_ratio,
    )
    return float(incoming_source_offset_seconds) - outgoing_timeline_offset * validate_tempo_ratio(incoming_tempo_ratio)


def source_beatgrid_to_timeline_seconds(
    beats: Iterable[float | dict[str, Any]],
    *,
    source_start_seconds: float,
    timeline_start_seconds: float,
    tempo_ratio: float,
) -> list[float]:
    """Map source beat times to MixPlan timeline seconds for a constant tempo ratio."""

    ratio = validate_tempo_ratio(tempo_ratio)
    mapped: list[float] = []
    for beat in beats:
        if isinstance(beat, dict):
            raw_time = beat.get("timeSeconds")
        else:
            raw_time = beat
        if not isinstance(raw_time, int | float) or not math.isfinite(raw_time):
            continue
        mapped.append(float(timeline_start_seconds) + (float(raw_time) - float(source_start_seconds)) / ratio)
    return mapped
