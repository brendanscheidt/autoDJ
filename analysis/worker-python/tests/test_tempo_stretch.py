import json
import math
from pathlib import Path
import subprocess
import wave

import pytest

from autodj_analysis.tempo_stretch import (
    TEMPO_STRETCH_SMOKE_REPORT_TYPE,
    TempoStretchError,
    TempoStretchOptions,
    run_tempo_stretch_smoke,
    stretch_audio_file,
)


def _write_wav(path: Path, *, sample_rate: int = 8_000, duration_seconds: float = 1.0) -> None:
    frame_count = int(round(sample_rate * duration_seconds))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = math.sin(2.0 * math.pi * 440.0 * index / sample_rate)
            value = round(sample * 12000)
            frames.extend(value.to_bytes(2, "little", signed=True))
            frames.extend(value.to_bytes(2, "little", signed=True))
        wav_file.writeframes(bytes(frames))


def _duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav_file:
        return wav_file.getnframes() / wav_file.getframerate()


class FakeStretchRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command) -> subprocess.CompletedProcess[str]:
        command = tuple(str(part) for part in command)
        self.commands.append(command)
        if command[:2] == ("rubberband", "--version"):
            return subprocess.CompletedProcess(command, 0, stdout="3.3.0\n", stderr="")
        if command[:2] == ("soundstretch", "-license"):
            return subprocess.CompletedProcess(command, 0, stdout="SoundStretch v2.3.2\n", stderr="")
        if command[0] == "ffmpeg":
            _write_wav(Path(command[-1]), duration_seconds=1.0)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[0] == "rubberband":
            ratio = float(command[command.index("--tempo") + 1])
            _write_wav(Path(command[-1]), duration_seconds=1.0 / ratio)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[0] == "soundstretch":
            percent_arg = next(part for part in command if part.startswith("-tempo="))
            ratio = 1.0 + float(percent_arg.split("=", 1)[1]) / 100.0
            _write_wav(Path(command[2]), duration_seconds=1.0 / ratio)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="unexpected command")


def test_stretch_audio_file_writes_rubberband_report(tmp_path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"placeholder")
    output = tmp_path / "stretched.wav"
    report = tmp_path / "tempo-stretch-report.json"
    runner = FakeStretchRunner()

    result = stretch_audio_file(
        source,
        output,
        report_path=report,
        options=TempoStretchOptions(
            source_bpm=160.0,
            target_bpm=150.0,
            backend="rubberband",
            sample_rate=8_000,
        ),
        command_runner=runner,
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert result.ok is True
    assert result.backend_name == "rubberband"
    assert result.backend_version == "3.3.0"
    assert result.tempo_ratio == pytest.approx(150.0 / 160.0)
    assert _duration(output) == pytest.approx(160.0 / 150.0, abs=0.001)
    assert payload["backendName"] == "rubberband"
    assert any(command[0] == "ffmpeg" for command in runner.commands)
    assert any(command[0] == "rubberband" and "--fine" in command for command in runner.commands)
    assert not any(command[0] == "rubberband" and "--centre-focus" in command for command in runner.commands)


def test_stretch_audio_file_supports_rubberband_centre_focus_as_explicit_mode(tmp_path) -> None:
    source = tmp_path / "source.wav"
    _write_wav(source)
    output = tmp_path / "stretched.wav"
    runner = FakeStretchRunner()

    result = stretch_audio_file(
        source,
        output,
        options=TempoStretchOptions(
            source_bpm=145.0,
            target_bpm=155.0,
            backend="rubberband",
            sample_rate=8_000,
            quality="fine-centre",
        ),
        command_runner=runner,
    )

    assert result.quality_mode == "fine-centre"
    assert any(command[0] == "rubberband" and "--centre-focus" in command for command in runner.commands)


def test_stretch_audio_file_supports_soundstretch_backend(tmp_path) -> None:
    source = tmp_path / "source.wav"
    _write_wav(source)
    output = tmp_path / "stretched.wav"
    report = tmp_path / "tempo-stretch-report.json"
    runner = FakeStretchRunner()

    result = stretch_audio_file(
        source,
        output,
        report_path=report,
        options=TempoStretchOptions(
            source_bpm=140.0,
            target_bpm=150.0,
            backend="soundtouch",
            sample_rate=8_000,
            quality="fast",
        ),
        command_runner=runner,
    )

    assert result.backend_name == "soundstretch"
    assert result.backend_version == "2.3.2"
    assert any(command[0] == "soundstretch" for command in runner.commands)
    assert _duration(output) == pytest.approx(140.0 / 150.0, abs=0.001)


def test_stretch_audio_file_rejects_invalid_bpm(tmp_path) -> None:
    source = tmp_path / "source.wav"
    _write_wav(source)

    with pytest.raises(TempoStretchError) as exc_info:
        stretch_audio_file(
            source,
            tmp_path / "out.wav",
            options=TempoStretchOptions(source_bpm=0.0, target_bpm=150.0),
        )

    assert exc_info.value.code == "invalid_source_bpm"


def test_tempo_stretch_smoke_writes_per_backend_outputs(tmp_path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"placeholder")
    runner = FakeStretchRunner()

    summary = run_tempo_stretch_smoke(
        source,
        tmp_path / "smoke",
        source_bpm=160.0,
        target_bpm=150.0,
        backends=("rubberband", "soundtouch"),
        sample_rate=8_000,
        command_runner=runner,
    )

    assert summary["ok"] is True
    assert summary["artifact"] == TEMPO_STRETCH_SMOKE_REPORT_TYPE
    assert (tmp_path / "smoke" / "rubberband" / "stretched.wav").exists()
    assert (tmp_path / "smoke" / "soundstretch" / "stretched.wav").exists()
    assert (tmp_path / "smoke" / "tempo-stretch-smoke-summary.json").exists()
    assert [result["backendName"] for result in summary["results"]] == ["rubberband", "soundstretch"]
