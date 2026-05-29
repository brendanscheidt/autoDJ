from __future__ import annotations

import json

import pytest

from autodj_analysis.transition_preview import (
    TransitionPreviewError,
    TransitionPreviewOptions,
    TransitionPreviewPackOptions,
    extract_transition_preview_plan,
    write_transition_preview_pack,
)


def _source_plan() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "planId": "full-set",
        "createdAtUtc": "2026-01-01T00:00:00Z",
        "strategy": {"strategyId": "test", "strategyVersion": "1.0.0"},
        "assets": [
            {"trackId": "track-a", "sourceUri": "a.wav", "formatHint": "wav"},
            {"trackId": "track-b", "sourceUri": "b.wav", "formatHint": "wav"},
            {"trackId": "unused", "sourceUri": "unused.wav", "formatHint": "wav"},
        ],
        "tracks": [
            {
                "placementId": "place-a",
                "trackId": "track-a",
                "deck": 1,
                "sourceStartSeconds": 10.0,
                "sourceEndSeconds": 90.0,
                "timelineStartSeconds": 100.0,
                "timelineEndSeconds": 180.0,
                "role": "primary",
            },
            {
                "placementId": "place-b",
                "trackId": "track-b",
                "deck": 2,
                "sourceStartSeconds": 20.0,
                "timelineStartSeconds": 130.0,
                "timelineEndSeconds": 190.0,
                "role": "incoming",
                "tempoPlan": {
                    "sourceBpm": 100.0,
                    "targetBpm": 50.0,
                    "targetBpmBias": 10.0,
                    "tempoRatio": 0.5,
                },
            },
        ],
        "transitions": [
            {
                "transitionId": "tx-1",
                "fromPlacementId": "place-a",
                "toPlacementId": "place-b",
                "technique": "build_to_drop_swap",
                "templateId": "second_build_drop_switch_v1",
                "timelineStartSeconds": 140.0,
                "timelineEndSeconds": 150.0,
                "handoffTimelineSeconds": 145.0,
                "score": 0.9,
                "reasons": ["fixture"],
            }
        ],
        "commands": [
            {
                "type": "automate",
                "deck": 1,
                "control": "volume",
                "keyframes": [
                    {"at": 110.0, "value": 0.2, "interpolation": "hold"},
                    {"at": 130.0, "value": 0.6, "interpolation": "linear"},
                    {"at": 160.0, "value": 0.4, "interpolation": "linear"},
                ],
            },
            {
                "type": "automate",
                "deck": 2,
                "control": "reverbWet",
                "effectParameters": {"reverbDecaySeconds": 12.0},
                "keyframes": [
                    {"at": 155.0, "value": 0.3, "interpolation": "linear"},
                    {"at": 170.0, "value": 0.0, "interpolation": "linear"},
                ],
            },
        ],
        "annotations": [{"at": 145.0, "transitionId": "tx-1", "message": "handoff"}],
    }


def test_extract_transition_preview_clips_and_shifts_tempo_aware_placements() -> None:
    preview = extract_transition_preview_plan(
        _source_plan(),
        "tx-1",
        options=TransitionPreviewOptions(pre_seconds=20.0, post_seconds=10.0, fx_preroll_seconds=0.0),
    )

    assert preview["preview"]["sourceWindowStartSeconds"] == 120.0
    assert preview["preview"]["durationSeconds"] == 40.0
    assert [asset["trackId"] for asset in preview["assets"]] == ["track-a", "track-b"]

    place_a = next(placement for placement in preview["tracks"] if placement["trackId"] == "track-a")
    place_b = next(placement for placement in preview["tracks"] if placement["trackId"] == "track-b")
    assert place_a["timelineStartSeconds"] == 0.0
    assert place_a["timelineEndSeconds"] == 40.0
    assert place_a["sourceStartSeconds"] == 30.0
    assert place_a["sourceEndSeconds"] == 70.0
    assert place_b["timelineStartSeconds"] == 10.0
    assert place_b["timelineEndSeconds"] == 40.0
    assert place_b["sourceStartSeconds"] == 20.0
    assert place_b["sourceEndSeconds"] == 38.0

    transition = preview["transitions"][0]
    assert transition["timelineStartSeconds"] == 20.0
    assert transition["timelineEndSeconds"] == 30.0
    assert transition["handoffTimelineSeconds"] == 25.0


def test_extract_transition_preview_preserves_automation_state_at_window_start() -> None:
    preview = extract_transition_preview_plan(
        _source_plan(),
        "tx-1",
        options=TransitionPreviewOptions(pre_seconds=20.0, post_seconds=10.0, fx_preroll_seconds=0.0),
    )

    volume = next(command for command in preview["commands"] if command.get("control") == "volume")
    assert volume["at"] == 0.0
    assert volume["keyframes"] == [
        {"at": 0.0, "value": 0.4, "interpolation": "hold"},
        {"at": 10.0, "value": 0.6, "interpolation": "linear"},
        {"at": 40.0, "value": 0.4, "interpolation": "linear"},
    ]

    reverb = next(command for command in preview["commands"] if command.get("control") == "reverbWet")
    assert reverb["effectParameters"] == {"reverbDecaySeconds": 12.0}
    assert reverb["keyframes"] == [{"at": 35.0, "value": 0.3, "interpolation": "linear"}]


def test_extract_transition_preview_adds_transport_commands_for_cropped_placements() -> None:
    preview = extract_transition_preview_plan(
        _source_plan(),
        "tx-1",
        options=TransitionPreviewOptions(pre_seconds=20.0, post_seconds=10.0, fx_preroll_seconds=0.0),
    )

    loads = [command for command in preview["commands"] if command["type"] == "load"]
    stops = [command for command in preview["commands"] if command["type"] == "stop"]
    assert {"type": "load", "at": 0.0, "deck": 1, "trackId": "track-a", "cueSeconds": 30.0} in loads
    assert {"type": "load", "at": 10.0, "deck": 2, "trackId": "track-b", "cueSeconds": 20.0} in loads
    assert {"type": "stop", "at": 40.0, "deck": 1} in stops
    assert {"type": "stop", "at": 40.0, "deck": 2} in stops


def test_extract_transition_preview_extends_window_for_fx_preroll() -> None:
    preview = extract_transition_preview_plan(
        _source_plan(),
        "tx-1",
        options=TransitionPreviewOptions(pre_seconds=20.0, post_seconds=10.0, fx_preroll_seconds=5.0),
    )

    assert preview["preview"]["sourceWindowStartSeconds"] == 115.0
    assert preview["preview"]["sourceAuditionStartSeconds"] == 120.0
    assert preview["transitions"][0]["timelineStartSeconds"] == 25.0


def test_extract_transition_preview_rejects_unknown_transition() -> None:
    with pytest.raises(TransitionPreviewError) as exc_info:
        extract_transition_preview_plan(_source_plan(), "missing")

    assert exc_info.value.code == "transition_not_found"


def test_write_transition_preview_pack_writes_index_and_preview_mixplans(tmp_path) -> None:
    plan_path = tmp_path / "mix-plan-full-set.json"
    plan_path.write_text(json.dumps(_source_plan(), indent=2), encoding="utf-8")

    summary = write_transition_preview_pack(
        plan_path,
        tmp_path / "previews",
        options=TransitionPreviewPackOptions(
            preview=TransitionPreviewOptions(pre_seconds=20.0, post_seconds=10.0, fx_preroll_seconds=0.0)
        ),
    )

    index_path = tmp_path / "previews" / "index.json"
    preview_plan_path = tmp_path / "previews" / "001-tx-1" / "mix-plan-preview.json"
    assert summary["total"] == 1
    assert summary["planned"] == 1
    assert summary["failed"] == 0
    assert index_path.exists()
    assert preview_plan_path.exists()
