from __future__ import annotations

import json
import math
from pathlib import Path
import wave

from autodj_analysis.mixplan_energy import GainPlanOptions, gain_plan_drop_switch_file


def _write_sectioned_wav(
    path: Path,
    *,
    sample_rate: int,
    duration_seconds: float,
    sections: list[tuple[float, float, list[tuple[float, float]]]],
) -> None:
    frames = bytearray()
    total_frames = round(duration_seconds * sample_rate)
    for frame in range(total_frames):
        seconds = frame / sample_rate
        sample = 0.0
        for start, end, components in sections:
            if start <= seconds < end:
                for frequency_hz, amplitude in components:
                    sample += amplitude * math.sin(2.0 * math.pi * frequency_hz * seconds)
                break
        sample = max(-0.95, min(0.95, sample))
        frames.extend(round(sample * 32767).to_bytes(2, byteorder="little", signed=True))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def _write_plan(tmp_path: Path) -> Path:
    plan = {
        "schemaVersion": "1.0.0",
        "planId": "plan-energy-test",
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
                "timelineEndSeconds": 7.0,
            },
            {
                "placementId": "place-incoming",
                "trackId": "incoming",
                "deck": 2,
                "sourceStartSeconds": 0.0,
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 16.0,
            },
        ],
        "transitions": [
            {
                "transitionId": "transition-energy-test",
                "fromPlacementId": "place-outgoing",
                "toPlacementId": "place-incoming",
                "technique": "build_to_drop_swap",
                "templateId": "second_build_drop_switch_v1",
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 8.0,
                "alignedDropTimelineSeconds": 8.0,
                "measureCountToTarget": 8.0,
                "score": 1.0,
                "sourceAnchors": {
                    "fromBuildStart": {"trackId": "outgoing", "sourceSeconds": 0.0},
                    "fromDropStart": {"trackId": "outgoing", "sourceSeconds": 8.0},
                    "toBuildStart": {"trackId": "incoming", "sourceSeconds": 0.0},
                    "toDropStart": {"trackId": "incoming", "sourceSeconds": 8.0},
                },
            }
        ],
        "commands": [
            {
                "type": "automate",
                "at": 0.0,
                "deck": 2,
                "control": "volume",
                "keyframes": [
                    {"at": 0.0, "value": 0.0, "interpolation": "hold"},
                    {"at": 4.0, "value": 1.0, "interpolation": "smoothstep"},
                ],
            },
            {
                "type": "automate",
                "at": 0.0,
                "deck": 2,
                "control": "eqLow",
                "keyframes": [
                    {"at": 0.0, "value": 0.0, "interpolation": "hold"},
                    {"at": 4.0, "value": 1.0, "interpolation": "hold"},
                ],
            },
            {
                "type": "automate",
                "at": 4.0,
                "deck": 1,
                "control": "eqLow",
                "keyframes": [{"at": 4.0, "value": 0.0, "interpolation": "hold"}],
            },
            {
                "type": "automate",
                "at": 0.0,
                "deck": 1,
                "control": "volume",
                "keyframes": [
                    {"at": 0.0, "value": 1.0, "interpolation": "hold"},
                    {"at": 7.0, "value": 0.0, "interpolation": "hold"},
                ],
            },
        ],
        "annotations": [],
    }
    path = tmp_path / "mix-plan.json"
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return path


def _run_gain_plan(tmp_path: Path, *, sample_rate: int = 8_000):
    plan_path = _write_plan(tmp_path)
    out_path = tmp_path / "mix-plan-gain-planned.json"
    report_path = tmp_path / "energy-report.json"
    result = gain_plan_drop_switch_file(
        plan_path,
        out_path,
        report_path,
        GainPlanOptions(sample_rate=sample_rate, asset_root=tmp_path),
    )
    return result, json.loads(out_path.read_text(encoding="utf-8")), json.loads(report_path.read_text(encoding="utf-8"))


def test_gain_plan_reports_compatible_pair_as_strong_or_usable(tmp_path: Path) -> None:
    sample_rate = 8_000
    _write_sectioned_wav(
        tmp_path / "outgoing.wav",
        sample_rate=sample_rate,
        duration_seconds=16.0,
        sections=[(0.0, 8.0, [(1_000.0, 0.04)]), (8.0, 16.0, [(90.0, 0.2), (1_000.0, 0.1)])],
    )
    _write_sectioned_wav(
        tmp_path / "incoming.wav",
        sample_rate=sample_rate,
        duration_seconds=16.0,
        sections=[(0.0, 8.0, [(90.0, 0.08), (1_000.0, 0.04)]), (8.0, 16.0, [(90.0, 0.45), (1_000.0, 0.25)])],
    )

    result, planned, report = _run_gain_plan(tmp_path, sample_rate=sample_rate)

    assert result.verdict in {"strong", "usable"}
    assert report["verdict"] == result.verdict
    assert report["windows"]["aBuildFinal"]["startSeconds"] == 0.0
    assert report["windows"]["bDropFirst"]["startSeconds"] == 8.0
    assert planned["transitions"][0]["sourceAnchors"] == json.loads((_write_plan(tmp_path)).read_text(encoding="utf-8"))[
        "transitions"
    ][0]["sourceAnchors"]


def test_gain_plan_rejects_or_flags_weak_drop_after_loud_layered_build(tmp_path: Path) -> None:
    sample_rate = 8_000
    loud_build = [(90.0, 0.28), (1_000.0, 0.28)]
    _write_sectioned_wav(
        tmp_path / "outgoing.wav",
        sample_rate=sample_rate,
        duration_seconds=16.0,
        sections=[(0.0, 8.0, loud_build), (8.0, 16.0, loud_build)],
    )
    _write_sectioned_wav(
        tmp_path / "incoming.wav",
        sample_rate=sample_rate,
        duration_seconds=16.0,
        sections=[(0.0, 8.0, loud_build), (8.0, 16.0, [(90.0, 0.04), (1_000.0, 0.04)])],
    )

    result, _, report = _run_gain_plan(tmp_path, sample_rate=sample_rate)

    assert result.verdict in {"risky_energy_drop", "reject_energy_drop"}
    assert "drop_energy_below_layered_build" in report["reasons"]
    assert report["comparisons"]["bDropVsPostGainLayeredDb"] < 0.0


def test_gain_plan_reduces_outgoing_overlap_when_layered_build_is_hot(tmp_path: Path) -> None:
    sample_rate = 8_000
    _write_sectioned_wav(
        tmp_path / "outgoing.wav",
        sample_rate=sample_rate,
        duration_seconds=16.0,
        sections=[(0.0, 8.0, [(1_000.0, 0.72)]), (8.0, 16.0, [(90.0, 0.3), (1_000.0, 0.2)])],
    )
    _write_sectioned_wav(
        tmp_path / "incoming.wav",
        sample_rate=sample_rate,
        duration_seconds=16.0,
        sections=[(0.0, 8.0, [(90.0, 0.38), (1_000.0, 0.38)]), (8.0, 16.0, [(90.0, 0.42), (1_000.0, 0.42)])],
    )

    result, planned, report = _run_gain_plan(tmp_path, sample_rate=sample_rate)
    outgoing_volume = next(
        command for command in planned["commands"] if command.get("deck") == 1 and command.get("control") == "volume"
    )

    assert result.outgoing_overlap_trim_db < 0.0
    assert report["recommendedOutgoingTrimDb"] < 0.0
    assert any(0.0 < keyframe["value"] < 1.0 for keyframe in outgoing_volume["keyframes"])
    assert planned["tracks"] == json.loads((_write_plan(tmp_path)).read_text(encoding="utf-8"))["tracks"]


def test_gain_plan_reports_low_band_drop_mismatch(tmp_path: Path) -> None:
    sample_rate = 8_000
    _write_sectioned_wav(
        tmp_path / "outgoing.wav",
        sample_rate=sample_rate,
        duration_seconds=16.0,
        sections=[(0.0, 8.0, [(90.0, 0.4), (1_000.0, 0.1)]), (8.0, 16.0, [(90.0, 0.4)])],
    )
    _write_sectioned_wav(
        tmp_path / "incoming.wav",
        sample_rate=sample_rate,
        duration_seconds=16.0,
        sections=[(0.0, 8.0, [(90.0, 0.35), (1_000.0, 0.1)]), (8.0, 16.0, [(90.0, 0.02), (1_000.0, 0.5)])],
    )

    result, _, report = _run_gain_plan(tmp_path, sample_rate=sample_rate)

    assert result.verdict in {"risky_energy_drop", "reject_energy_drop"}
    assert "drop_low_band_deficit" in report["reasons"]
    assert report["comparisons"]["bDropLowVsBuildLowDb"] < -4.0
