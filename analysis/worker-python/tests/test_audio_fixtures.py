from __future__ import annotations

from pathlib import Path
import math
import wave

import pytest

from audio_fixtures import (
    DEFAULT_FIXTURE_SAMPLE_RATE,
    create_70_bpm_halftime_fixture,
    create_140_bpm_click_fixture,
    create_energy_ramp_fixture,
    create_silence_fixture,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_140_bpm_click_fixture_writes_temp_mono_wav_with_expected_beats(tmp_path: Path) -> None:
    fixture = create_140_bpm_click_fixture(tmp_path)
    metadata, samples = _read_pcm16_mono_wav(fixture.path)

    assert fixture.path.parent == tmp_path
    assert fixture.expected_bpm == 140.0
    assert fixture.expected_normalized_bpm == 140.0
    assert fixture.expected_beat_times[:3] == pytest.approx((0.0, 60.0 / 140.0, 120.0 / 140.0))
    assert metadata["channels"] == 1
    assert metadata["sample_width"] == 2
    assert metadata["sample_rate"] == DEFAULT_FIXTURE_SAMPLE_RATE
    assert metadata["frame_count"] == round(fixture.duration_seconds * fixture.sample_rate)
    assert max(abs(sample) for sample in samples) > 0.40
    assert _rms_window(samples, fixture.sample_rate, fixture.expected_beat_times[1], 0.030) > 0.10


def test_70_bpm_halftime_fixture_exposes_raw_and_normalized_tempo(tmp_path: Path) -> None:
    fixture = create_70_bpm_halftime_fixture(tmp_path)
    _, samples = _read_pcm16_mono_wav(fixture.path)

    assert fixture.expected_bpm == 70.0
    assert fixture.expected_normalized_bpm == 140.0
    assert fixture.expected_beat_times[:3] == pytest.approx((0.0, 60.0 / 70.0, 120.0 / 70.0))
    assert max(abs(sample) for sample in samples) > 0.40
    assert _rms_window(samples, fixture.sample_rate, fixture.expected_beat_times[1], 0.070) > 0.08


def test_energy_ramp_fixture_has_known_low_and_high_regions(tmp_path: Path) -> None:
    fixture = create_energy_ramp_fixture(tmp_path)
    _, samples = _read_pcm16_mono_wav(fixture.path)

    assert fixture.low_energy_regions == ((0.0, 4.0),)
    assert fixture.high_energy_regions == ((8.0, 12.0),)

    low_start, low_end = fixture.low_energy_regions[0]
    high_start, high_end = fixture.high_energy_regions[0]
    low_rms = _rms_between(samples, fixture.sample_rate, low_start + 0.25, low_end - 0.25)
    high_rms = _rms_between(samples, fixture.sample_rate, high_start + 0.25, high_end - 0.25)

    assert low_rms > 0.0
    assert high_rms > low_rms * 4.0


def test_silence_and_near_silence_fixtures_are_low_confidence_inputs(tmp_path: Path) -> None:
    silence = create_silence_fixture(tmp_path, filename="silence.wav")
    near_silence = create_silence_fixture(tmp_path, filename="near-silence.wav", near_silence=True)
    _, silence_samples = _read_pcm16_mono_wav(silence.path)
    _, near_silence_samples = _read_pcm16_mono_wav(near_silence.path)

    assert all(sample == 0.0 for sample in silence_samples)
    assert max(abs(sample) for sample in near_silence_samples) > 0.0
    assert max(abs(sample) for sample in near_silence_samples) < 0.001


def test_audio_fixture_generation_is_deterministic(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first_click = create_140_bpm_click_fixture(first_dir).path
    second_click = create_140_bpm_click_fixture(second_dir).path
    first_ramp = create_energy_ramp_fixture(first_dir).path
    second_ramp = create_energy_ramp_fixture(second_dir).path

    assert first_click.read_bytes() == second_click.read_bytes()
    assert first_ramp.read_bytes() == second_ramp.read_bytes()


def test_audio_fixture_helpers_write_only_under_requested_temp_path(tmp_path: Path) -> None:
    fixtures = [
        create_140_bpm_click_fixture(tmp_path),
        create_70_bpm_halftime_fixture(tmp_path),
        create_energy_ramp_fixture(tmp_path),
        create_silence_fixture(tmp_path),
    ]

    for fixture in fixtures:
        fixture_path = fixture.path.resolve()
        assert fixture_path.is_relative_to(tmp_path.resolve())
        assert not fixture_path.is_relative_to(REPO_ROOT)
        assert fixture_path.suffix == ".wav"


@pytest.mark.parametrize("filename", ["../escape.wav", "nested/escape.wav", "not-a-wav.mp3"])
def test_audio_fixture_helpers_reject_unsafe_output_filenames(tmp_path: Path, filename: str) -> None:
    with pytest.raises(ValueError):
        create_140_bpm_click_fixture(tmp_path, filename=filename)


def _read_pcm16_mono_wav(path: Path) -> tuple[dict[str, int], list[float]]:
    with wave.open(str(path), "rb") as wav_file:
        metadata = {
            "channels": wav_file.getnchannels(),
            "sample_width": wav_file.getsampwidth(),
            "sample_rate": wav_file.getframerate(),
            "frame_count": wav_file.getnframes(),
        }
        frames = wav_file.readframes(metadata["frame_count"])

    assert metadata["channels"] == 1
    assert metadata["sample_width"] == 2
    samples = [
        int.from_bytes(frames[index : index + 2], byteorder="little", signed=True) / 32767.0
        for index in range(0, len(frames), 2)
    ]
    return metadata, samples


def _rms_window(samples: list[float], sample_rate: int, center_seconds: float, duration_seconds: float) -> float:
    half_duration = duration_seconds / 2.0
    return _rms_between(
        samples,
        sample_rate,
        max(0.0, center_seconds - half_duration),
        center_seconds + half_duration,
    )


def _rms_between(samples: list[float], sample_rate: int, start_seconds: float, end_seconds: float) -> float:
    start_frame = max(0, round(start_seconds * sample_rate))
    end_frame = min(len(samples), round(end_seconds * sample_rate))
    assert end_frame > start_frame
    window = samples[start_frame:end_frame]
    return math.sqrt(sum(sample * sample for sample in window) / len(window))
