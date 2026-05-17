from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import wave


DEFAULT_FIXTURE_SAMPLE_RATE = 22_050


@dataclass(frozen=True)
class GeneratedAudioFixture:
    path: Path
    sample_rate: int
    duration_seconds: float
    expected_bpm: float | None = None
    expected_normalized_bpm: float | None = None
    expected_beat_times: tuple[float, ...] = ()
    low_energy_regions: tuple[tuple[float, float], ...] = ()
    high_energy_regions: tuple[tuple[float, float], ...] = ()


def create_140_bpm_click_fixture(
    output_dir: Path,
    *,
    filename: str = "click-140-bpm.wav",
    duration_seconds: float = 8.0,
    sample_rate: int = DEFAULT_FIXTURE_SAMPLE_RATE,
) -> GeneratedAudioFixture:
    return create_click_fixture(
        output_dir,
        bpm=140.0,
        filename=filename,
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        normalized_bpm=140.0,
    )


def create_70_bpm_halftime_fixture(
    output_dir: Path,
    *,
    filename: str = "click-70-bpm-halftime.wav",
    duration_seconds: float = 12.0,
    sample_rate: int = DEFAULT_FIXTURE_SAMPLE_RATE,
) -> GeneratedAudioFixture:
    return create_click_fixture(
        output_dir,
        bpm=70.0,
        filename=filename,
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        normalized_bpm=140.0,
        click_frequency_hz=660.0,
        pulse_frequency_hz=82.5,
    )


def create_click_fixture(
    output_dir: Path,
    *,
    bpm: float,
    filename: str,
    duration_seconds: float,
    sample_rate: int = DEFAULT_FIXTURE_SAMPLE_RATE,
    normalized_bpm: float | None = None,
    click_frequency_hz: float = 1760.0,
    pulse_frequency_hz: float | None = None,
) -> GeneratedAudioFixture:
    if bpm <= 0:
        raise ValueError("bpm must be greater than zero")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be greater than zero")

    beat_times = _beat_times(bpm, duration_seconds)
    total_frames = _frame_count(duration_seconds, sample_rate)
    samples = [0.0] * total_frames
    click_frames = max(1, round(sample_rate * 0.030))
    pulse_frames = max(1, round(sample_rate * 0.070))

    for beat_time in beat_times:
        start_frame = round(beat_time * sample_rate)
        _add_sine_burst(
            samples,
            start_frame=start_frame,
            frame_count=click_frames,
            sample_rate=sample_rate,
            frequency_hz=click_frequency_hz,
            amplitude=0.75,
        )
        if pulse_frequency_hz is not None:
            _add_sine_burst(
                samples,
                start_frame=start_frame,
                frame_count=pulse_frames,
                sample_rate=sample_rate,
                frequency_hz=pulse_frequency_hz,
                amplitude=0.45,
            )

    path = _resolve_fixture_path(output_dir, filename)
    _write_pcm16_mono_wav(path, samples=samples, sample_rate=sample_rate)
    return GeneratedAudioFixture(
        path=path,
        sample_rate=sample_rate,
        duration_seconds=duration_seconds,
        expected_bpm=bpm,
        expected_normalized_bpm=normalized_bpm or bpm,
        expected_beat_times=beat_times,
    )


def create_energy_ramp_fixture(
    output_dir: Path,
    *,
    filename: str = "energy-ramp.wav",
    duration_seconds: float = 12.0,
    sample_rate: int = DEFAULT_FIXTURE_SAMPLE_RATE,
) -> GeneratedAudioFixture:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be greater than zero")

    total_frames = _frame_count(duration_seconds, sample_rate)
    low_end = duration_seconds / 3.0
    ramp_end = 2.0 * duration_seconds / 3.0
    samples = []

    for frame_index in range(total_frames):
        time_seconds = frame_index / sample_rate
        if time_seconds < low_end:
            amplitude = 0.10
        elif time_seconds < ramp_end:
            progress = (time_seconds - low_end) / (ramp_end - low_end)
            amplitude = 0.10 + 0.55 * progress
        else:
            amplitude = 0.65

        bass = math.sin(2.0 * math.pi * 110.0 * time_seconds)
        mid = math.sin(2.0 * math.pi * 440.0 * time_seconds)
        samples.append(amplitude * (0.70 * bass + 0.30 * mid))

    path = _resolve_fixture_path(output_dir, filename)
    _write_pcm16_mono_wav(path, samples=samples, sample_rate=sample_rate)
    return GeneratedAudioFixture(
        path=path,
        sample_rate=sample_rate,
        duration_seconds=duration_seconds,
        low_energy_regions=((0.0, low_end),),
        high_energy_regions=((ramp_end, duration_seconds),),
    )


def create_silence_fixture(
    output_dir: Path,
    *,
    filename: str = "silence.wav",
    duration_seconds: float = 4.0,
    sample_rate: int = DEFAULT_FIXTURE_SAMPLE_RATE,
    near_silence: bool = False,
) -> GeneratedAudioFixture:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be greater than zero")

    total_frames = _frame_count(duration_seconds, sample_rate)
    if near_silence:
        samples = [
            0.0005 * math.sin(2.0 * math.pi * 220.0 * frame_index / sample_rate)
            for frame_index in range(total_frames)
        ]
    else:
        samples = [0.0] * total_frames

    path = _resolve_fixture_path(output_dir, filename)
    _write_pcm16_mono_wav(path, samples=samples, sample_rate=sample_rate)
    return GeneratedAudioFixture(
        path=path,
        sample_rate=sample_rate,
        duration_seconds=duration_seconds,
    )


def _beat_times(bpm: float, duration_seconds: float) -> tuple[float, ...]:
    interval_seconds = 60.0 / bpm
    beat_count = int(math.floor((duration_seconds - 1e-9) / interval_seconds)) + 1
    return tuple(round(index * interval_seconds, 9) for index in range(beat_count))


def _frame_count(duration_seconds: float, sample_rate: int) -> int:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be greater than zero")
    return round(duration_seconds * sample_rate)


def _add_sine_burst(
    samples: list[float],
    *,
    start_frame: int,
    frame_count: int,
    sample_rate: int,
    frequency_hz: float,
    amplitude: float,
) -> None:
    for offset in range(frame_count):
        frame_index = start_frame + offset
        if frame_index >= len(samples):
            break
        envelope = 1.0 - (offset / frame_count)
        value = amplitude * envelope * math.sin(2.0 * math.pi * frequency_hz * offset / sample_rate)
        samples[frame_index] = _clamp_sample(samples[frame_index] + value)


def _resolve_fixture_path(output_dir: Path, filename: str) -> Path:
    relative_path = Path(filename)
    if relative_path.name != filename:
        raise ValueError("filename must not include directory components")
    if relative_path.suffix.lower() != ".wav":
        raise ValueError("generated audio fixtures must use a .wav extension")

    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / filename


def _write_pcm16_mono_wav(path: Path, *, samples: list[float], sample_rate: int) -> None:
    frames = bytearray()
    for sample in samples:
        sample_int = round(_clamp_sample(sample) * 32767)
        frames.extend(sample_int.to_bytes(2, byteorder="little", signed=True))

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def _clamp_sample(sample: float) -> float:
    return min(1.0, max(-1.0, sample))
