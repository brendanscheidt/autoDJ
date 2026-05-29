import json
from pathlib import Path
import random

from autodj_analysis.full_set_planner import (
    TrackRow,
    build_full_set_statistics,
    build_candidate_report,
    build_candidate_record,
    build_candidate_step_records,
    candidate_precheck_reasons,
    candidate_score,
    drop_switch_candidates,
    mark_candidate_rejected_after_attempt,
    mark_candidate_selected,
    merge_pair_plans,
    source_uri_resolvable,
    validate_full_set_plan,
    wash_out_setup_potential,
    wash_out_candidates,
)


def _track(
    track_id: str,
    *,
    bpm: float = 140.0,
    key: str = "6A",
    key_confidence: float = 0.95,
    builds: int = 2,
    drops: int = 2,
) -> TrackRow:
    return TrackRow(
        track_id=track_id,
        artifact_path=Path(f"{track_id}/analyzed-track.json"),
        source_uri=f"{track_id}.mp3",
        normalized_bpm=bpm,
        camelot_key=key,
        key_confidence=key_confidence,
        duration_seconds=180.0,
        build_count=builds,
        drop_count=drops,
    )


def test_drop_switch_candidate_precheck_reports_policy_reasons() -> None:
    outgoing = _track("outgoing", builds=1, drops=1)
    incoming = _track("incoming", bpm=170.0, key="11B", drops=0)

    reasons = candidate_precheck_reasons(
        "drop-switch",
        outgoing,
        incoming,
        max_tempo_adjustment_bpm=10.0,
    )

    assert {reason["code"] for reason in reasons} == {
        "missing_outgoing_second_build_drop",
        "missing_incoming_drop",
        "key_incompatible",
        "tempo_delta_exceeds_limit",
        "drop_switch_tempo_stretch_disabled",
    }


def test_drop_switch_key_policy_can_allow_unknown_keys_without_allowing_clashes() -> None:
    outgoing = _track("outgoing", key="6A", key_confidence=0.95)
    low_confidence = _track("low-confidence", key="7A", key_confidence=0.2)
    clash = _track("clash", key="11B", key_confidence=0.95)

    default_reasons = candidate_precheck_reasons(
        "drop-switch",
        outgoing,
        low_confidence,
        max_tempo_adjustment_bpm=10.0,
    )
    allow_unknown_reasons = candidate_precheck_reasons(
        "drop-switch",
        outgoing,
        low_confidence,
        max_tempo_adjustment_bpm=10.0,
        drop_switch_key_policy="allow-unknown",
    )
    clash_reasons = candidate_precheck_reasons(
        "drop-switch",
        outgoing,
        clash,
        max_tempo_adjustment_bpm=10.0,
        drop_switch_key_policy="allow-unknown",
    )

    assert any(reason["code"] == "key_incompatible" for reason in default_reasons)
    assert not any(reason["code"] == "key_incompatible" for reason in allow_unknown_reasons)
    assert any(reason["code"] == "key_incompatible" for reason in clash_reasons)


def test_drop_switch_candidate_score_rewards_exact_bpm_and_key_match() -> None:
    outgoing = _track("outgoing", bpm=150.0, key="8A")
    exact = _track("exact", bpm=150.0, key="8A")
    stretched = _track("stretched", bpm=158.0, key="8A")

    exact_score = candidate_score(
        "drop-switch",
        outgoing,
        exact,
        max_tempo_adjustment_bpm=10.0,
        recent_kinds=[],
    )
    stretched_score = candidate_score(
        "drop-switch",
        outgoing,
        stretched,
        max_tempo_adjustment_bpm=10.0,
        recent_kinds=[],
    )

    assert exact_score["score"] > stretched_score["score"]
    assert exact_score["components"]["tempo"]["requiresStretch"] is False
    assert stretched_score["components"]["tempo"]["requiresStretch"] is True


def test_candidate_step_records_include_both_transition_families() -> None:
    outgoing = _track("outgoing")
    incoming = _track("incoming", key="7A")

    records = build_candidate_step_records(
        step_index=3,
        outgoing=outgoing,
        candidates=[incoming],
        max_tempo_adjustment_bpm=10.0,
        recent_kinds=["wash-out", "wash-out"],
    )

    assert [record["kind"] for record in records] == ["drop-switch", "wash-out"]
    assert all(record["stepIndex"] == 3 for record in records)
    wash_record = next(record for record in records if record["kind"] == "wash-out")
    assert wash_record["scoreComponents"]["recentHistory"]["score"] < 1.0


def test_candidate_report_summarizes_selected_and_rejections() -> None:
    outgoing = _track("outgoing")
    incoming = _track("incoming")
    record = build_candidate_record(
        step_index=1,
        kind="drop-switch",
        outgoing=outgoing,
        incoming=incoming,
        max_tempo_adjustment_bpm=10.0,
        recent_kinds=[],
    )
    selected = {
        "kind": "drop-switch",
        "outgoing": outgoing,
        "incoming": incoming,
        "final_plan_path": Path("pair/mix-plan-final.json"),
        "nudge": {
            "ok": True,
            "confidence": 0.92,
            "nudgeMilliseconds": -3.5,
            "anchorNudges": [{"nudgeSeconds": -0.003}, {"nudgeSeconds": -0.004}],
        },
        "gain": {
            "ok": True,
            "verdict": "usable",
            "recommendedOutgoingTrimDb": -1.25,
            "outgoingOverlapGain": 0.86,
            "bDropVsPostGainLayeredDb": 1.4,
            "reportPath": "pair/energy-report.json",
        },
    }
    mark_candidate_selected(record, selected)
    rejected = build_candidate_record(
        step_index=1,
        kind="drop-switch",
        outgoing=outgoing,
        incoming=_track("bad", key="12B"),
        max_tempo_adjustment_bpm=10.0,
        recent_kinds=[],
    )
    mark_candidate_rejected_after_attempt(rejected)

    report = build_candidate_report(
        events=[record, rejected],
        run_name="test-run",
        seed="seed",
        selected=[selected],
        policy={"maxTempoAdjustmentBpm": 10.0},
    )

    assert report["selectedCount"] == 1
    assert report["statusSummary"]["selected"] == 1
    assert report["statusSummary"]["rejected_after_attempt"] == 1
    assert report["candidates"][0]["postPass"]["nudge"]["confidence"] == 0.92
    assert report["candidates"][0]["postPass"]["gain"]["verdict"] == "usable"


def test_candidate_search_width_limits_attemptable_drop_switches() -> None:
    outgoing = _track("alpha-track", bpm=150.0, key="8A")
    first = _track("bravo-first", bpm=150.0, key="8A")
    second = _track("charlie-second", bpm=150.0, key="8A")

    candidates = drop_switch_candidates(
        outgoing,
        [first, second],
        random.Random("seed"),
        max_tempo_adjustment_bpm=10.0,
        candidate_search_width=1,
    )

    assert len(candidates) == 1


def test_drop_switch_candidates_enforce_stretch_budget_and_artist_repeat_policy() -> None:
    outgoing = _track("same-artist-original", bpm=150.0, key="8A")
    same_artist = _track("same-artist-remix", bpm=150.0, key="8A")
    over_budget = _track("other-over-budget", bpm=158.0, key="8A")
    allowed = _track("other-allowed", bpm=151.0, key="8A")

    candidates = drop_switch_candidates(
        outgoing,
        [same_artist, over_budget, allowed],
        random.Random("seed"),
        max_tempo_adjustment_bpm=10.0,
        allow_tempo_stretch=True,
        max_total_stretch_bpm=5.0,
        used_stretch_bpm=4.0,
        avoid_repeated_artist=True,
    )

    assert candidates == [allowed]


def test_drop_switch_candidates_prefer_effective_outgoing_tempo() -> None:
    outgoing = _track("outgoing", bpm=150.0, key="8A")
    native_match = _track("native-match", bpm=150.0, key="8A")
    effective_match = _track("effective-match", bpm=145.0, key="8A")

    candidates = drop_switch_candidates(
        outgoing,
        [native_match, effective_match],
        random.Random("seed"),
        outgoing_effective_bpm=145.0,
        max_tempo_adjustment_bpm=10.0,
        allow_tempo_stretch=True,
    )

    assert candidates[0] == effective_match


def test_candidate_precheck_uses_effective_outgoing_tempo() -> None:
    outgoing = _track("outgoing", bpm=150.0, key="8A")
    incoming = _track("incoming", bpm=145.0, key="8A")

    reasons = candidate_precheck_reasons(
        "drop-switch",
        outgoing,
        incoming,
        outgoing_effective_bpm=145.0,
        max_tempo_adjustment_bpm=10.0,
        allow_drop_switch_tempo_stretch=True,
    )

    assert reasons == []


def test_candidate_precheck_reports_tempo_delta_against_effective_bpm() -> None:
    outgoing = _track("outgoing", bpm=150.0, key="8A")
    incoming = _track("incoming", bpm=160.5, key="8A")

    reasons = candidate_precheck_reasons(
        "drop-switch",
        outgoing,
        incoming,
        outgoing_effective_bpm=145.0,
        max_tempo_adjustment_bpm=10.0,
        allow_drop_switch_tempo_stretch=True,
    )

    reason = next(reason for reason in reasons if reason["code"] == "tempo_delta_exceeds_limit")
    assert reason["tempoDeltaBpm"] == 15.5
    assert reason["outgoingEffectiveBpm"] == 145.0


def test_wash_out_candidates_can_avoid_repeated_artist() -> None:
    outgoing = _track("same-artist-original", key="8A")
    same_artist = _track("same-artist-remix", key="8A")
    other = _track("other-track", key="8A")

    candidates = wash_out_candidates(
        outgoing,
        [same_artist, other],
        random.Random("seed"),
        avoid_repeated_artist=True,
    )

    assert candidates == [other]


def test_wash_out_candidates_prefer_tracks_that_set_up_future_drop_switches() -> None:
    outgoing = _track("outgoing", bpm=150.0, key="8A")
    poor_setup = _track("poor-setup", bpm=128.0, key="2A")
    strong_setup = _track("strong-setup", bpm=150.0, key="8A")
    future = _track("future-compatible", bpm=150.0, key="8A")

    candidates = wash_out_candidates(
        outgoing,
        [poor_setup, strong_setup, future],
        random.Random("seed"),
        max_tempo_adjustment_bpm=10.0,
        allow_drop_switch_tempo_stretch=True,
    )

    assert candidates[0] == strong_setup
    potential = wash_out_setup_potential(
        strong_setup,
        [poor_setup, future],
        max_tempo_adjustment_bpm=10.0,
        allow_drop_switch_tempo_stretch=True,
        max_total_stretch_bpm=999.0,
        used_stretch_bpm=0.0,
        avoid_repeated_artist=True,
    )
    assert potential["exactCount"] == 1


def _valid_full_set_plan() -> dict:
    return {
        "assets": [
            {"trackId": "outgoing", "sourceUri": "outgoing.wav"},
            {"trackId": "incoming", "sourceUri": "incoming.wav"},
        ],
        "tracks": [
            {
                "placementId": "place-out",
                "trackId": "outgoing",
                "deck": 1,
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 16.0,
                "sourceStartSeconds": 0.0,
            },
            {
                "placementId": "place-in",
                "trackId": "incoming",
                "deck": 2,
                "timelineStartSeconds": 8.0,
                "timelineEndSeconds": 32.0,
                "sourceStartSeconds": 0.0,
            },
        ],
        "transitions": [
            {
                "transitionId": "transition-001",
                "templateId": "second_build_drop_switch_v1",
                "fromPlacementId": "place-out",
                "toPlacementId": "place-in",
                "timelineStartSeconds": 8.0,
                "timelineEndSeconds": 16.0,
            }
        ],
        "commands": [
            {"type": "stop", "at": 16.0, "deck": 1},
            {
                "type": "automate",
                "at": 8.0,
                "deck": 2,
                "control": "reverbWet",
                "keyframes": [{"at": 8.0, "value": 0.0}],
            },
            {
                "type": "automate",
                "at": 8.0,
                "deck": 2,
                "control": "reverbTailGain",
                "keyframes": [{"at": 8.0, "value": 0.0}],
            },
            {
                "type": "automate",
                "at": 8.0,
                "deck": 2,
                "control": "echoWet",
                "keyframes": [{"at": 8.0, "value": 0.0}],
            },
        ],
    }


def test_validate_full_set_plan_accepts_valid_minimal_drop_switch() -> None:
    result = validate_full_set_plan(_valid_full_set_plan())

    assert result["ok"] is True


def test_merge_pair_plans_uses_configured_washout_sweep_uri(tmp_path: Path) -> None:
    pair_plan = {
        "assets": [
            {"trackId": "outgoing", "sourceUri": "outgoing.wav"},
            {"trackId": "incoming", "sourceUri": "incoming.wav"},
            {"trackId": "washout-sweep-fx", "sourceUri": "generated://autodj/fx/washout-sweep-v1.wav"},
        ],
        "tracks": [
            {
                "placementId": "place-out",
                "trackId": "outgoing",
                "deck": 1,
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 16.0,
                "sourceStartSeconds": 0.0,
            },
            {
                "placementId": "place-in",
                "trackId": "incoming",
                "deck": 2,
                "timelineStartSeconds": 16.0,
                "timelineEndSeconds": 48.0,
                "sourceStartSeconds": 0.0,
            },
            {
                "placementId": "place-sweep",
                "trackId": "washout-sweep-fx",
                "deck": 3,
                "timelineStartSeconds": 14.0,
                "timelineEndSeconds": 22.0,
                "sourceStartSeconds": 0.0,
            },
        ],
        "transitions": [
            {
                "transitionId": "transition-001",
                "templateId": "drop_end_wash_out_v1",
                "fromPlacementId": "place-out",
                "toPlacementId": "place-in",
                "timelineStartSeconds": 12.0,
                "timelineEndSeconds": 16.0,
                "handoffTimelineSeconds": 16.0,
            }
        ],
        "commands": [
            {"type": "stop", "at": 16.0, "deck": 1},
            {"type": "play", "at": 16.0, "deck": 2, "placementId": "place-in"},
        ],
        "annotations": [],
    }
    plan_path = tmp_path / "pair-plan.json"
    plan_path.write_text(json.dumps(pair_plan), encoding="utf-8")

    full_plan = merge_pair_plans(
        [{"kind": "wash-out", "final_plan_path": plan_path}],
        "test-run",
        washout_sweep_uri="C:/Users/Brendan/Desktop/sweep.wav",
    )

    sweep_asset = next(asset for asset in full_plan["assets"] if asset["trackId"] == "washout-sweep-fx")
    assert sweep_asset["sourceUri"] == "C:/Users/Brendan/Desktop/sweep.wav"


def test_merge_pair_plans_maps_later_pair_times_from_pair_timeline_origin(tmp_path: Path) -> None:
    pair_one = {
        "assets": [
            {"trackId": "track-a", "sourceUri": "track-a.wav"},
            {"trackId": "track-b", "sourceUri": "track-b.wav"},
        ],
        "tracks": [
            {
                "placementId": "pair1-a",
                "trackId": "track-a",
                "deck": 1,
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 8.0,
                "sourceStartSeconds": 0.0,
            },
            {
                "placementId": "pair1-b",
                "trackId": "track-b",
                "deck": 2,
                "timelineStartSeconds": 8.0,
                "timelineEndSeconds": 40.0,
                "sourceStartSeconds": 32.0,
            },
        ],
        "transitions": [
            {
                "transitionId": "transition-001",
                "templateId": "drop_end_wash_out_v1",
                "fromPlacementId": "pair1-a",
                "toPlacementId": "pair1-b",
                "timelineStartSeconds": 4.0,
                "timelineEndSeconds": 8.0,
                "handoffTimelineSeconds": 8.0,
            }
        ],
        "commands": [
            {"type": "stop", "at": 8.0, "deck": 1},
            {"type": "play", "at": 8.0, "deck": 2, "placementId": "pair1-b"},
        ],
        "annotations": [{"at": 4.0, "text": "pair-one", "placementId": "pair1-a"}],
    }
    pair_two = {
        "assets": [
            {"trackId": "track-b", "sourceUri": "track-b.wav"},
            {"trackId": "track-c", "sourceUri": "track-c.wav"},
        ],
        "tracks": [
            {
                "placementId": "pair2-b",
                "trackId": "track-b",
                "deck": 2,
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 16.0,
                "sourceStartSeconds": 32.0,
            },
            {
                "placementId": "pair2-c",
                "trackId": "track-c",
                "deck": 1,
                "timelineStartSeconds": 12.0,
                "timelineEndSeconds": 44.0,
                "sourceStartSeconds": 0.0,
            },
        ],
        "transitions": [
            {
                "transitionId": "transition-002",
                "templateId": "drop_end_wash_out_v1",
                "fromPlacementId": "pair2-b",
                "toPlacementId": "pair2-c",
                "timelineStartSeconds": 12.0,
                "timelineEndSeconds": 16.0,
                "handoffTimelineSeconds": 16.0,
            }
        ],
        "commands": [
            {"type": "stop", "at": 16.0, "deck": 2},
            {"type": "play", "at": 12.0, "deck": 1, "placementId": "pair2-c"},
        ],
        "annotations": [{"at": 12.0, "text": "pair-two", "placementId": "pair2-c"}],
    }
    pair_one_path = tmp_path / "pair-one.json"
    pair_two_path = tmp_path / "pair-two.json"
    pair_one_path.write_text(json.dumps(pair_one), encoding="utf-8")
    pair_two_path.write_text(json.dumps(pair_two), encoding="utf-8")

    full_plan = merge_pair_plans(
        [
            {"kind": "wash-out", "final_plan_path": pair_one_path},
            {"kind": "wash-out", "final_plan_path": pair_two_path},
        ],
        "test-run",
        washout_sweep_uri="generated://autodj/fx/washout-sweep-v1.wav",
    )

    second_transition = next(
        transition for transition in full_plan["transitions"] if transition["transitionId"] == "set-002-transition-002"
    )
    assert second_transition["timelineStartSeconds"] == 20.0
    assert second_transition["timelineEndSeconds"] == 24.0
    assert second_transition["handoffTimelineSeconds"] == 24.0

    incoming_placement = next(
        placement for placement in full_plan["tracks"] if placement["placementId"] == "set-002-pair2-c"
    )
    assert incoming_placement["timelineStartSeconds"] == 20.0

    pair_two_annotation = next(annotation for annotation in full_plan["annotations"] if annotation["text"] == "pair-two")
    assert pair_two_annotation["at"] == 20.0


def test_source_uri_resolvable_accepts_absolute_paths(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep.wav"
    sweep.write_bytes(b"RIFF")

    assert source_uri_resolvable(str(sweep), asset_root=tmp_path)


def test_validate_full_set_plan_rejects_wet_fx_inside_drop_switch() -> None:
    plan = _valid_full_set_plan()
    plan["commands"].append(
        {
            "type": "automate",
            "at": 12.0,
            "deck": 1,
            "control": "reverbWet",
            "keyframes": [{"at": 12.0, "value": 0.5}],
        }
    )

    result = validate_full_set_plan(plan)

    assert result["ok"] is False
    assert any(error["code"] == "drop_switch_wet_fx_automation" for error in result["errors"])


def test_validate_full_set_plan_rejects_duplicate_ids_and_bad_tempo_plan() -> None:
    plan = _valid_full_set_plan()
    plan["tracks"][1]["placementId"] = "place-out"
    plan["tracks"][0]["tempoPlan"] = {
        "sourceBpm": 140.0,
        "targetBpm": 150.0,
        "preservePitch": False,
    }

    result = validate_full_set_plan(plan)

    codes = {error["code"] for error in result["errors"]}
    assert "duplicate_placement_id" in codes
    assert "preserve_pitch_required" in codes


def test_build_full_set_statistics_reports_stretch_washout_and_nudge_ranges() -> None:
    outgoing = _track("outgoing", bpm=150.0, key="8A")
    stretched = _track("stretched", bpm=156.0, key="8A")
    wash = _track("wash", bpm=140.0, key="9A")
    selected = [
        {
            "kind": "drop-switch",
            "outgoing": outgoing,
            "incoming": stretched,
            "nudge": {"confidence": 0.8, "nudgeMilliseconds": -2.5},
            "gain": {"verdict": "usable"},
        },
        {
            "kind": "wash-out",
            "outgoing": stretched,
            "incoming": wash,
            "nudge": {"confidence": 0.6, "nudgeMilliseconds": 5.0},
            "gain": None,
        },
    ]

    stats = build_full_set_statistics(selected, {"ok": True, "errorCount": 0})

    assert stats["transitionCounts"] == {"drop-switch": 1, "wash-out": 1}
    assert stats["stretchedDropSwitchCount"] == 1
    assert stats["totalStretchDeltaBpm"] == 6.0
    assert stats["nudgeConfidenceRange"] == {"min": 0.6, "max": 0.8}
    assert stats["gainVerdicts"] == {"usable": 1}
