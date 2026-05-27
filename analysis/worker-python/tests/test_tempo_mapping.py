from __future__ import annotations

import pytest

from autodj_analysis.tempo_mapping import (
    source_beatgrid_to_timeline_seconds,
    source_nudge_for_rendered_alignment,
    source_seconds_to_stretched_seconds,
    stretched_seconds_to_source_seconds,
)


def test_constant_tempo_mapping_round_trips_source_and_stretched_seconds() -> None:
    stretched = source_seconds_to_stretched_seconds(12.0, tempo_ratio=0.75)
    assert stretched == 16.0
    assert stretched_seconds_to_source_seconds(stretched, tempo_ratio=0.75) == 12.0


def test_source_beatgrid_to_timeline_seconds_maps_constant_ratio() -> None:
    mapped = source_beatgrid_to_timeline_seconds(
        [{"timeSeconds": 10.0}, {"timeSeconds": 11.5}, 13.0],
        source_start_seconds=10.0,
        timeline_start_seconds=40.0,
        tempo_ratio=0.5,
    )

    assert mapped == [40.0, 43.0, 46.0]


def test_source_nudge_for_rendered_alignment_accounts_for_both_ratios() -> None:
    nudge = source_nudge_for_rendered_alignment(
        outgoing_source_offset_seconds=0.005,
        outgoing_tempo_ratio=1.0,
        incoming_source_offset_seconds=0.025,
        incoming_tempo_ratio=0.5,
    )

    assert abs(nudge - 0.0225) < 0.000001


def test_tempo_mapping_rejects_invalid_ratios() -> None:
    with pytest.raises(ValueError):
        source_seconds_to_stretched_seconds(1.0, tempo_ratio=0.0)
