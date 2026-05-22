from __future__ import annotations

import json
from pathlib import Path
import wave

from autodj_analysis.mixplan_nudge import NudgeOptions, nudge_mix_plan_file


def _write_impulse_wav(path: Path, *, sample_rate: int, duration_seconds: float, impulse_seconds: float) -> None:
    total_frames = round(duration_seconds * sample_rate)
    impulse_frame = round(impulse_seconds * sample_rate)
    frames = bytearray()
    for frame in range(total_frames):
        sample = 0.9 if frame == impulse_frame else 0.0
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
    assert len(result.anchor_nudges) == 2

    nudged = json.loads(output_path.read_text(encoding="utf-8"))
    incoming = next(placement for placement in nudged["tracks"] if placement["trackId"] == "incoming")
    incoming_load = next(command for command in nudged["commands"] if command.get("trackId") == "incoming")
    assert abs(incoming["sourceStartSeconds"] - result.nudge_seconds) < 0.000001
    assert abs(incoming_load["cueSeconds"] - result.nudge_seconds) < 0.000001
    assert "transient nudge" in nudged["annotations"][-1]["message"]
