from __future__ import annotations

import json
from pathlib import Path
import wave

from autodj_analysis.mixplan_nudge import NudgeOptions, _micro_alignment_adjustment, nudge_mix_plan_file
from autodj_analysis.mixplan_renderer import LoadedAudio


def _write_impulse_wav(path: Path, *, sample_rate: int, duration_seconds: float, impulse_seconds: float) -> None:
    _write_impulses_wav(
        path,
        sample_rate=sample_rate,
        duration_seconds=duration_seconds,
        impulse_seconds=[impulse_seconds],
    )


def _write_impulses_wav(
    path: Path,
    *,
    sample_rate: int,
    duration_seconds: float,
    impulse_seconds: list[float],
) -> None:
    total_frames = round(duration_seconds * sample_rate)
    impulse_frames = {round(seconds * sample_rate) for seconds in impulse_seconds}
    frames = bytearray()
    for frame in range(total_frames):
        sample = 0.9 if frame in impulse_frames else 0.0
        frames.extend(round(sample * 32767).to_bytes(2, byteorder="little", signed=True))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def _write_weighted_impulses_wav(
    path: Path,
    *,
    sample_rate: int,
    duration_seconds: float,
    impulses: list[tuple[float, float]],
) -> None:
    total_frames = round(duration_seconds * sample_rate)
    impulse_frames = {round(seconds * sample_rate): amplitude for seconds, amplitude in impulses}
    frames = bytearray()
    for frame in range(total_frames):
        sample = impulse_frames.get(frame, 0.0)
        frames.extend(round(sample * 32767).to_bytes(2, byteorder="little", signed=True))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def _drop_switch_plan(tmp_path: Path) -> Path:
    plan = {
        "schemaVersion": "1.0.0",
        "planId": "plan-nudge-test",
        "createdAtUtc": "2026-01-01T00:00:00Z",
        "strategy": {"strategyId": "test", "strategyVersion": "1.0.0"},
        "assets": [
            {"trackId": "outgoing", "sourceUri": "outgoing.wav", "formatHint": "wav"},
            {"trackId": "incoming", "sourceUri": "incoming.wav", "formatHint": "wav"},
        ],
        "tracks": [
            {
                "placementId": "place-outgoing",
                "trackId": "outgoing",
                "deck": 1,
                "sourceStartSeconds": 0.0,
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 2.0,
            },
            {
                "placementId": "place-incoming",
                "trackId": "incoming",
                "deck": 2,
                "sourceStartSeconds": 0.0,
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 2.0,
            },
        ],
        "transitions": [
            {
                "transitionId": "transition-nudge-test",
                "fromPlacementId": "place-outgoing",
                "toPlacementId": "place-incoming",
                "technique": "build_to_drop_swap",
                "templateId": "second_build_drop_switch_v1",
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 1.0,
                "score": 1.0,
                "sourceAnchors": {
                    "fromBuildStart": {"trackId": "outgoing", "sourceSeconds": 1.0},
                    "toBuildStart": {"trackId": "incoming", "sourceSeconds": 1.0},
                    "fromDropStart": {"trackId": "outgoing", "sourceSeconds": 1.0},
                    "toDropStart": {"trackId": "incoming", "sourceSeconds": 1.0},
                },
            }
        ],
        "commands": [
            {"type": "load", "at": 0.0, "deck": 1, "trackId": "outgoing", "cueSeconds": 0.0},
            {"type": "load", "at": 0.0, "deck": 2, "trackId": "incoming", "cueSeconds": 0.0},
        ],
        "annotations": [],
    }
    path = tmp_path / "mix-plan.json"
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return path


def _write_refined_anchor_report(path: Path, *, track_id: str, source_seconds: float, wall_seconds: float) -> Path:
    report = {
        "artifact": "beatgrid-phase-refinement-report",
        "trackId": track_id,
        "applied": True,
        "anchors": [
            {
                "label": "drop_1_start",
                "anchorTimeSeconds": source_seconds,
                "nearestBeatTimeSeconds": source_seconds,
                "selectedWallTimeSeconds": wall_seconds,
                "accepted": True,
                "riskProfile": {
                    "verdict": "strong",
                    "riskFlags": [],
                    "allowedTransitionFamilies": [
                        "drop_switch",
                        "layered_drop",
                        "reverb_exit",
                        "simple_handoff",
                    ],
                    "precisionSafe": True,
                    "dropSwitchSafe": True,
                    "layeredDropSafe": True,
                    "score": 0.96,
                    "absOffsetMilliseconds": abs(wall_seconds - source_seconds) * 1000.0,
                    "closeCompetitorCount": 0,
                },
            }
        ],
    }
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def test_nudge_mix_plan_offsets_incoming_source_start_to_align_transients(tmp_path: Path) -> None:
    sample_rate = 8_000
    _write_impulse_wav(tmp_path / "outgoing.wav", sample_rate=sample_rate, duration_seconds=2.0, impulse_seconds=1.005)
    _write_impulse_wav(tmp_path / "incoming.wav", sample_rate=sample_rate, duration_seconds=2.0, impulse_seconds=1.025)
    plan_path = _drop_switch_plan(tmp_path)
    output_path = tmp_path / "nudged-plan.json"

    result = nudge_mix_plan_file(
        plan_path,
        output_path,
        NudgeOptions(sample_rate=sample_rate, asset_root=tmp_path, window_seconds=0.04, max_nudge_seconds=0.05),
    )

    assert output_path.exists()
    assert abs(result.nudge_seconds - 0.02) < 0.004
    assert result.confidence > 0.5
    assert len(result.anchor_nudges) == 1
    assert result.anchor_nudges[0].anchor_pair == "fromDropStart->toDropStart"
    assert result.anchor_nudges[0].outgoing_candidates
    assert result.anchor_nudges[0].incoming_candidates

    nudged = json.loads(output_path.read_text(encoding="utf-8"))
    incoming = next(placement for placement in nudged["tracks"] if placement["trackId"] == "incoming")
    incoming_load = next(command for command in nudged["commands"] if command.get("trackId") == "incoming")
    assert abs(incoming["sourceStartSeconds"] - result.nudge_seconds) < 0.000001
    assert abs(incoming_load["cueSeconds"] - result.nudge_seconds) < 0.000001
    assert "transient nudge" in nudged["annotations"][-1]["message"]


def test_nudge_mix_plan_prefers_close_drop_transient_over_later_louder_hit(tmp_path: Path) -> None:
    sample_rate = 8_000
    _write_weighted_impulses_wav(
        tmp_path / "outgoing.wav",
        sample_rate=sample_rate,
        duration_seconds=2.0,
        impulses=[(1.005, 0.55), (1.065, 0.95)],
    )
    _write_weighted_impulses_wav(
        tmp_path / "incoming.wav",
        sample_rate=sample_rate,
        duration_seconds=2.0,
        impulses=[(1.010, 0.9)],
    )
    plan_path = _drop_switch_plan(tmp_path)
    output_path = tmp_path / "close-transient-nudged-plan.json"

    result = nudge_mix_plan_file(
        plan_path,
        output_path,
        NudgeOptions(
            sample_rate=sample_rate,
            asset_root=tmp_path,
            window_seconds=0.08,
            max_nudge_seconds=0.08,
        ),
    )

    assert output_path.exists()
    assert abs(result.nudge_seconds - 0.005) < 0.004
    assert "strongest_transient_was_not_selected" in result.risk_flags


def test_nudge_mix_plan_uses_drop_transient_not_build_transient(tmp_path: Path) -> None:
    sample_rate = 8_000
    _write_impulses_wav(
        tmp_path / "outgoing.wav",
        sample_rate=sample_rate,
        duration_seconds=2.0,
        impulse_seconds=[0.55, 1.005],
    )
    _write_impulses_wav(
        tmp_path / "incoming.wav",
        sample_rate=sample_rate,
        duration_seconds=2.0,
        impulse_seconds=[0.45, 1.025],
    )
    plan_path = _drop_switch_plan(tmp_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["transitions"][0]["sourceAnchors"] = {
        "fromBuildStart": {"trackId": "outgoing", "sourceSeconds": 0.5},
        "toBuildStart": {"trackId": "incoming", "sourceSeconds": 0.5},
        "fromDropStart": {"trackId": "outgoing", "sourceSeconds": 1.0},
        "toDropStart": {"trackId": "incoming", "sourceSeconds": 1.0},
    }
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    output_path = tmp_path / "drop-only-nudged-plan.json"

    result = nudge_mix_plan_file(
        plan_path,
        output_path,
        NudgeOptions(sample_rate=sample_rate, asset_root=tmp_path, window_seconds=0.08, max_nudge_seconds=0.08),
    )

    assert output_path.exists()
    assert abs(result.nudge_seconds - 0.02) < 0.004
    assert len(result.anchor_nudges) == 1
    assert result.anchor_nudges[0].anchor_pair == "fromDropStart->toDropStart"


def test_nudge_mix_plan_accounts_for_incoming_tempo_stretch_mapping(tmp_path: Path) -> None:
    sample_rate = 8_000
    _write_impulse_wav(tmp_path / "outgoing.wav", sample_rate=sample_rate, duration_seconds=2.0, impulse_seconds=1.005)
    _write_impulse_wav(tmp_path / "incoming.wav", sample_rate=sample_rate, duration_seconds=2.0, impulse_seconds=1.025)
    plan_path = _drop_switch_plan(tmp_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    incoming = next(placement for placement in plan["tracks"] if placement["trackId"] == "incoming")
    incoming["tempoPlan"] = {
        "sourceBpm": 100.0,
        "targetBpm": 50.0,
        "tempoRatio": 0.5,
        "preservePitch": True,
        "backend": "soundstretch",
    }
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    output_path = tmp_path / "nudged-stretched-plan.json"

    result = nudge_mix_plan_file(
        plan_path,
        output_path,
        NudgeOptions(sample_rate=sample_rate, asset_root=tmp_path, window_seconds=0.04, max_nudge_seconds=0.05),
    )

    assert output_path.exists()
    # Incoming source-start nudges are in original source seconds. With a 0.5
    # tempo ratio, a 22.5 ms source nudge moves the rendered incoming transient
    # 45 ms, which aligns its +50 ms rendered offset with the outgoing +5 ms
    # rendered offset.
    assert abs(result.nudge_seconds - 0.0225) < 0.004
    nudged = json.loads(output_path.read_text(encoding="utf-8"))
    incoming = next(placement for placement in nudged["tracks"] if placement["trackId"] == "incoming")
    assert abs(incoming["sourceStartSeconds"] - result.nudge_seconds) < 0.000001


def test_nudge_mix_plan_can_compare_and_apply_refined_anchor_reports(tmp_path: Path) -> None:
    sample_rate = 8_000
    _write_impulse_wav(tmp_path / "outgoing.wav", sample_rate=sample_rate, duration_seconds=2.0, impulse_seconds=1.005)
    _write_impulse_wav(tmp_path / "incoming.wav", sample_rate=sample_rate, duration_seconds=2.0, impulse_seconds=1.025)
    outgoing_report = _write_refined_anchor_report(
        tmp_path / "outgoing-phase-report.json",
        track_id="outgoing",
        source_seconds=1.0,
        wall_seconds=1.005,
    )
    incoming_report = _write_refined_anchor_report(
        tmp_path / "incoming-phase-report.json",
        track_id="incoming",
        source_seconds=1.0,
        wall_seconds=1.025,
    )
    plan_path = _drop_switch_plan(tmp_path)
    output_path = tmp_path / "refined-nudged-plan.json"

    result = nudge_mix_plan_file(
        plan_path,
        output_path,
        NudgeOptions(
            sample_rate=sample_rate,
            asset_root=tmp_path,
            window_seconds=0.04,
            max_nudge_seconds=0.05,
            refined_anchor_reports=(outgoing_report, incoming_report),
            use_refined_anchors=True,
        ),
    )

    assert output_path.exists()
    assert result.selected_anchor_mode == "refined"
    assert abs(result.nudge_seconds - 0.02) < 0.004
    assert len(result.raw_anchor_nudges) == 1
    assert len(result.refined_anchor_nudges) == 1
    payload = result.to_dict()
    assert payload["refinedAnchorComparison"]["rawAnchorNudges"]
    assert payload["refinedAnchorComparison"]["refinedAnchorNudges"][0]["anchorMode"] == "refined"


def test_micro_alignment_finds_sub_beat_lag() -> None:
    sample_rate = 8_000
    outgoing_samples = [0.0] * (sample_rate * 2)
    incoming_samples = [0.0] * (sample_rate * 2)
    outgoing_samples[round(1.0 * sample_rate)] = 0.9
    incoming_samples[round(1.003 * sample_rate)] = 0.9
    outgoing = LoadedAudio(tuple(outgoing_samples), sample_rate, Path("outgoing.wav"))
    incoming = LoadedAudio(tuple(incoming_samples), sample_rate, Path("incoming.wav"))

    micro_alignment = _micro_alignment_adjustment(
        outgoing,
        incoming,
        1.0,
        1.0,
        outgoing_tempo_ratio=1.0,
        incoming_tempo_ratio=1.0,
        options=NudgeOptions(
            sample_rate=sample_rate,
            micro_alignment_seconds=0.007,
            micro_alignment_window_seconds=0.03,
            min_micro_alignment_improvement=0.0,
        ),
    )

    assert micro_alignment is not None
    assert micro_alignment.applied
    assert abs(micro_alignment.adjustment_source_seconds - 0.003) < 0.001
