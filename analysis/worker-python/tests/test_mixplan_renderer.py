from __future__ import annotations

import json
import math
from pathlib import Path
import wave

import pytest

from autodj_analysis.mixplan_renderer import MixPlanRenderError, RenderOptions, render_mix_plan_file


def _write_wav(path: Path, samples: list[float], sample_rate: int) -> None:
    frames = bytearray()
    for sample in samples:
        value = max(-1.0, min(1.0, sample))
        frames.extend(round(value * 32767).to_bytes(2, byteorder="little", signed=True))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def _sine_fixture(path: Path, *, frequency_hz: float, duration_seconds: float, sample_rate: int, amplitude: float) -> None:
    total_frames = round(duration_seconds * sample_rate)
    samples = [
        amplitude * math.sin(2.0 * math.pi * frequency_hz * frame / sample_rate)
        for frame in range(total_frames)
    ]
    _write_wav(path, samples, sample_rate)


def _silence_fixture(path: Path, *, duration_seconds: float, sample_rate: int) -> None:
    _write_wav(path, [0.0] * round(duration_seconds * sample_rate), sample_rate)


def _read_wav_samples(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())
    samples = [
        int.from_bytes(frames[offset : offset + 2], byteorder="little", signed=True) / 32768.0
        for offset in range(0, len(frames), 2)
    ]
    return sample_rate, samples


def _rms(samples: list[float], sample_rate: int, start_seconds: float, end_seconds: float) -> float:
    start = max(0, round(start_seconds * sample_rate))
    end = min(len(samples), round(end_seconds * sample_rate))
    window = samples[start:end]
    if not window:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in window) / len(window))


def _peak(samples: list[float], sample_rate: int, start_seconds: float, end_seconds: float) -> float:
    start = max(0, round(start_seconds * sample_rate))
    end = min(len(samples), round(end_seconds * sample_rate))
    window = samples[start:end]
    if not window:
        return 0.0
    return max(abs(sample) for sample in window)


def _drop_end_reverb_plan(tmp_path: Path) -> Path:
    plan = {
        "schemaVersion": "1.0.0",
        "planId": "plan-render-test",
        "createdAtUtc": "2026-01-01T00:00:00Z",
        "strategy": {"strategyId": "dubstep-dj", "strategyVersion": "0.3.0"},
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
                "sourceEndSeconds": 1.0,
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 1.4,
                "role": "primary",
            },
            {
                "placementId": "place-incoming",
                "trackId": "incoming",
                "deck": 2,
                "sourceStartSeconds": 0.0,
                "timelineStartSeconds": 1.0,
                "timelineEndSeconds": 1.8,
                "role": "incoming",
            },
        ],
        "transitions": [
            {
                "transitionId": "transition-render-test",
                "fromPlacementId": "place-outgoing",
                "toPlacementId": "place-incoming",
                "technique": "drop_end_reverb_exit",
                "templateId": "drop_end_reverb_exit_v1",
                "timelineStartSeconds": 0.5,
                "timelineEndSeconds": 1.4,
                "handoffTimelineSeconds": 1.0,
                "measureCountToTarget": 1.0,
                "score": 0.8,
                "reasons": ["test fixture"],
            }
        ],
        "commands": [
            {"type": "load", "at": 0.0, "deck": 1, "trackId": "outgoing", "stem": "full", "cueSeconds": 0.0},
            {"type": "play", "at": 0.0, "deck": 1},
            {
                "type": "automate",
                "deck": 1,
                "control": "eqLow",
                "keyframes": [
                    {"at": 0.5, "value": 1.0, "interpolation": "hold"},
                    {"at": 1.0, "value": 0.0, "interpolation": "linear"},
                ],
            },
            {
                "type": "automate",
                "deck": 1,
                "control": "reverbWet",
                "postFader": True,
                "effectParameters": {"style": "cdj", "reverbDecaySeconds": 4.0},
                "keyframes": [
                    {"at": 0.5, "value": 0.0, "interpolation": "hold"},
                    {"at": 0.8, "value": 0.5, "interpolation": "linear"},
                    {"at": 1.0, "value": 1.0, "interpolation": "linear"},
                ],
            },
            {
                "type": "automate",
                "deck": 1,
                "control": "volume",
                "keyframes": [
                    {"at": 0.8, "value": 1.0, "interpolation": "hold"},
                    {"at": 1.0, "value": 0.0, "interpolation": "linear"},
                ],
            },
            {
                "type": "automate",
                "deck": 1,
                "control": "reverbTailGain",
                "postFader": True,
                "keyframes": [
                    {"at": 0.8, "value": 0.0, "interpolation": "hold"},
                    {"at": 1.0, "value": 1.0, "interpolation": "linear"},
                    {"at": 1.4, "value": 0.0, "interpolation": "smoothstep"},
                ],
            },
            {"type": "load", "at": 0.9, "deck": 2, "trackId": "incoming", "stem": "full", "cueSeconds": 0.0},
            {"type": "play", "at": 1.0, "deck": 2},
            {
                "type": "automate",
                "deck": 2,
                "control": "eqLow",
                "keyframes": [
                    {"at": 1.0, "value": 0.0, "interpolation": "hold"},
                    {"at": 1.4, "value": 1.0, "interpolation": "linear"},
                ],
            },
            {"type": "stop", "at": 1.4, "deck": 1},
        ],
        "annotations": [{"at": 1.0, "transitionId": "transition-render-test", "message": "handoff"}],
    }
    path = tmp_path / "mix-plan.json"
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return path


def test_render_mix_plan_writes_wav_summary_and_trace(tmp_path: Path) -> None:
    sample_rate = 8_000
    _sine_fixture(tmp_path / "outgoing.wav", frequency_hz=110.0, duration_seconds=1.0, sample_rate=sample_rate, amplitude=0.7)
    _silence_fixture(tmp_path / "incoming.wav", duration_seconds=1.0, sample_rate=sample_rate)
    plan_path = _drop_end_reverb_plan(tmp_path)

    result = render_mix_plan_file(plan_path, tmp_path / "render", RenderOptions(sample_rate=sample_rate, asset_root=tmp_path))

    assert result.output_wav.exists()
    assert result.summary_path.exists()
    assert result.trace_path.exists()
    assert result.sample_rate == sample_rate
    assert result.transition_templates == ("drop_end_reverb_exit_v1",)
    assert {"eqLow", "reverbTailGain", "reverbWet", "volume"}.issubset(result.automation_controls)

    wav_sample_rate, samples = _read_wav_samples(result.output_wav)
    assert wav_sample_rate == sample_rate
    assert len(samples) == result.frames
    assert max(abs(sample) for sample in samples) > 0.01

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    trace = json.loads(result.trace_path.read_text(encoding="utf-8"))
    assert summary["outputWav"] == str(result.output_wav)
    assert trace["commands"][0]["type"] == "load"


def test_render_mix_plan_keeps_post_fader_reverb_tail_after_dry_handoff(tmp_path: Path) -> None:
    sample_rate = 8_000
    _sine_fixture(tmp_path / "outgoing.wav", frequency_hz=220.0, duration_seconds=1.0, sample_rate=sample_rate, amplitude=0.8)
    _silence_fixture(tmp_path / "incoming.wav", duration_seconds=1.0, sample_rate=sample_rate)
    plan_path = _drop_end_reverb_plan(tmp_path)

    result = render_mix_plan_file(
        plan_path,
        tmp_path / "render",
        RenderOptions(sample_rate=sample_rate, asset_root=tmp_path, reverb_feedback=0.7),
    )

    wav_sample_rate, samples = _read_wav_samples(result.output_wav)
    dry_handoff_tail = _rms(samples, wav_sample_rate, 1.05, 1.25)
    after_tail_fade = _rms(samples, wav_sample_rate, 1.6, 1.75)
    assert dry_handoff_tail > 0.005
    assert after_tail_fade < dry_handoff_tail * 0.5


def test_render_mix_plan_low_eq_restore_changes_bass_energy(tmp_path: Path) -> None:
    sample_rate = 8_000
    _silence_fixture(tmp_path / "outgoing.wav", duration_seconds=1.0, sample_rate=sample_rate)
    _sine_fixture(tmp_path / "incoming.wav", frequency_hz=80.0, duration_seconds=1.0, sample_rate=sample_rate, amplitude=0.8)
    plan_path = _drop_end_reverb_plan(tmp_path)

    result = render_mix_plan_file(plan_path, tmp_path / "render", RenderOptions(sample_rate=sample_rate, asset_root=tmp_path))

    wav_sample_rate, samples = _read_wav_samples(result.output_wav)
    low_cut_region = _rms(samples, wav_sample_rate, 1.02, 1.12)
    restored_region = _rms(samples, wav_sample_rate, 1.55, 1.70)
    assert restored_region > low_cut_region * 2.0


def test_render_mix_plan_rejects_missing_assets(tmp_path: Path) -> None:
    plan_path = tmp_path / "mix-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "assets": [],
                "tracks": [
                    {
                        "placementId": "missing",
                        "trackId": "missing-track",
                        "deck": 1,
                        "sourceStartSeconds": 0.0,
                        "timelineStartSeconds": 0.0,
                        "timelineEndSeconds": 1.0,
                    }
                ],
                "transitions": [],
                "commands": [{"type": "play", "at": 0.0, "deck": 1}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(MixPlanRenderError) as exc_info:
        render_mix_plan_file(plan_path, tmp_path / "render", RenderOptions(sample_rate=8_000, asset_root=tmp_path))

    assert exc_info.value.code == "missing_asset"


def test_render_mix_plan_renders_echo_wet_delay_return(tmp_path: Path) -> None:
    sample_rate = 8_000
    impulse = [0.0] * round(0.4 * sample_rate)
    impulse[0] = 0.9
    _write_wav(tmp_path / "outgoing.wav", impulse, sample_rate)
    plan = {
        "schemaVersion": "1.0.0",
        "planId": "plan-echo-test",
        "createdAtUtc": "2026-01-01T00:00:00Z",
        "strategy": {"strategyId": "manual-transition-recipe", "strategyVersion": "0.1.0"},
        "assets": [{"trackId": "outgoing", "sourceUri": "outgoing.wav", "formatHint": "wav"}],
        "tracks": [
            {
                "placementId": "place-outgoing",
                "trackId": "outgoing",
                "deck": 1,
                "sourceStartSeconds": 0.0,
                "sourceEndSeconds": 0.02,
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 0.35,
                "role": "primary",
            }
        ],
        "transitions": [],
        "commands": [
            {"type": "load", "at": 0.0, "deck": 1, "trackId": "outgoing", "stem": "full", "cueSeconds": 0.0},
            {"type": "play", "at": 0.0, "deck": 1},
            {
                "type": "automate",
                "deck": 1,
                "control": "echoWet",
                "postFader": True,
                "effectParameters": {"delaySeconds": 0.1, "feedback": 0.45, "returnGain": 1.0},
                "keyframes": [
                    {"at": 0.0, "value": 1.0, "interpolation": "hold"},
                    {"at": 0.3, "value": 1.0, "interpolation": "hold"},
                ],
            },
        ],
        "annotations": [{"at": 0.1, "message": "echo return"}],
    }
    plan_path = tmp_path / "mix-plan-echo.json"
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    result = render_mix_plan_file(
        plan_path,
        tmp_path / "render",
        RenderOptions(sample_rate=sample_rate, asset_root=tmp_path, output_gain=1.0),
    )

    wav_sample_rate, samples = _read_wav_samples(result.output_wav)
    dry_impulse = _peak(samples, wav_sample_rate, 0.0, 0.02)
    first_echo = _peak(samples, wav_sample_rate, 0.095, 0.105)
    second_echo = _peak(samples, wav_sample_rate, 0.195, 0.205)
    silent_gap = _peak(samples, wav_sample_rate, 0.04, 0.08)
    assert "echoWet" in result.automation_controls
    assert dry_impulse > 0.2
    assert first_echo > 0.1
    assert second_echo > 0.03
    assert silent_gap < first_echo * 0.1
