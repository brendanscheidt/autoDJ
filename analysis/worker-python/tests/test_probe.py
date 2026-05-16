import json
from pathlib import Path
import shutil
import subprocess
import wave

import pytest

from autodj_analysis import ProbeError, parse_ffprobe_output, probe_audio


def _completed(command, payload: dict, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=list(command),
        returncode=returncode,
        stdout=json.dumps(payload),
        stderr=stderr,
    )


def _ffprobe_payload() -> dict:
    return {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "mjpeg",
            },
            {
                "index": 2,
                "codec_type": "audio",
                "codec_name": "aac",
                "codec_long_name": "AAC",
                "sample_rate": "44100",
                "channels": 1,
                "duration": "10.000000",
                "bit_rate": "128000",
                "disposition": {"default": 0},
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "mp3",
                "codec_long_name": "MP3 (MPEG audio layer 3)",
                "sample_rate": "48000",
                "channels": 2,
                "duration": "12.500000",
                "bit_rate": "192000",
                "disposition": {"default": 1},
                "tags": {"title": "Stream Title", "encoder": "stream-encoder"},
            },
        ],
        "format": {
            "duration": "13.000000",
            "bit_rate": "256000",
            "format_name": "mp3",
            "format_long_name": "MP2/3 (MPEG audio layer 2/3)",
            "tags": {"title": "Format Title", "album": "Probe Tests"},
        },
    }


def test_probe_audio_runs_ffprobe_command_and_parses_primary_stream(tmp_path: Path) -> None:
    audio_path = tmp_path / "drop.mp3"
    audio_path.write_bytes(b"fake audio bytes")
    seen_commands = []

    def runner(command):
        seen_commands.append(list(command))
        return _completed(command, _ffprobe_payload())

    probe = probe_audio(
        audio_path,
        ffprobe_path="fake-ffprobe",
        source_uri="fixture://drop.mp3",
        track_id="track-drop-001",
        runner=runner,
    )

    assert seen_commands == [
        [
            "fake-ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(audio_path),
        ]
    ]
    assert probe.duration_seconds == 12.5
    assert probe.sample_rate == 48000
    assert probe.channels == 2
    assert probe.codec_name == "mp3"
    assert probe.codec_long_name == "MP3 (MPEG audio layer 3)"
    assert probe.bit_rate == 192000
    assert probe.format_name == "mp3"
    assert probe.format_long_name == "MP2/3 (MPEG audio layer 2/3)"
    assert probe.tags == {
        "title": "Stream Title",
        "album": "Probe Tests",
        "encoder": "stream-encoder",
    }
    assert probe.raw["format"]["format_name"] == "mp3"


def test_parse_ffprobe_output_falls_back_to_format_duration_and_bit_rate() -> None:
    payload = {
        "streams": [
            {
                "index": 3,
                "codec_type": "audio",
                "codec_name": "pcm_s16le",
                "sample_rate": "44100",
                "channels": "2",
                "duration": "N/A",
                "bit_rate": "N/A",
            }
        ],
        "format": {
            "duration": "1.250000",
            "bit_rate": "1411200",
            "format_name": "wav",
        },
    }

    probe = parse_ffprobe_output(payload)

    assert probe.duration_seconds == 1.25
    assert probe.bit_rate == 1411200
    assert probe.sample_rate == 44100
    assert probe.channels == 2


def test_parse_ffprobe_output_selects_lowest_index_audio_without_default() -> None:
    payload = {
        "streams": [
            {"index": 5, "codec_type": "audio", "codec_name": "aac", "sample_rate": "44100"},
            {"index": 1, "codec_type": "audio", "codec_name": "mp3", "sample_rate": "48000"},
        ],
        "format": {},
    }

    probe = parse_ffprobe_output(payload)

    assert probe.codec_name == "mp3"
    assert probe.sample_rate == 48000


def test_probe_audio_reports_missing_source_before_running_ffprobe(tmp_path: Path) -> None:
    called = False

    def runner(command):
        nonlocal called
        called = True
        return _completed(command, _ffprobe_payload())

    with pytest.raises(ProbeError) as exc_info:
        probe_audio(tmp_path / "missing.mp3", runner=runner)

    assert exc_info.value.code == "source_missing"
    assert called is False


def test_probe_audio_reports_missing_ffprobe_executable(tmp_path: Path) -> None:
    audio_path = tmp_path / "drop.mp3"
    audio_path.write_bytes(b"fake")

    def runner(command):
        raise FileNotFoundError("missing ffprobe")

    with pytest.raises(ProbeError) as exc_info:
        probe_audio(audio_path, ffprobe_path="missing-ffprobe", runner=runner)

    assert exc_info.value.code == "ffprobe_missing"
    assert exc_info.value.source_uri == audio_path.as_posix()


def test_probe_audio_reports_nonzero_ffprobe_exit(tmp_path: Path) -> None:
    audio_path = tmp_path / "drop.mp3"
    audio_path.write_bytes(b"fake")

    def runner(command):
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=1,
            stdout="",
            stderr="invalid data found when processing input",
        )

    with pytest.raises(ProbeError) as exc_info:
        probe_audio(audio_path, runner=runner)

    assert exc_info.value.code == "ffprobe_failed"
    assert "invalid data" in exc_info.value.message


def test_probe_audio_reports_invalid_json(tmp_path: Path) -> None:
    audio_path = tmp_path / "drop.mp3"
    audio_path.write_bytes(b"fake")

    def runner(command):
        return subprocess.CompletedProcess(args=list(command), returncode=0, stdout="{ not json", stderr="")

    with pytest.raises(ProbeError) as exc_info:
        probe_audio(audio_path, runner=runner)

    assert exc_info.value.code == "ffprobe_invalid_json"


def test_probe_audio_reports_no_audio_stream(tmp_path: Path) -> None:
    audio_path = tmp_path / "cover.jpg"
    audio_path.write_bytes(b"fake")

    def runner(command):
        return _completed(command, {"streams": [{"index": 0, "codec_type": "video"}], "format": {}})

    with pytest.raises(ProbeError) as exc_info:
        probe_audio(audio_path, source_uri="fixture://cover.jpg", track_id="track-cover", runner=runner)

    assert exc_info.value.code == "ffprobe_no_audio_stream"
    assert exc_info.value.to_dict()["trackId"] == "track-cover"
    assert exc_info.value.to_dict()["sourceUri"] == "fixture://cover.jpg"


def test_probe_audio_with_real_ffprobe_on_generated_wav(tmp_path: Path) -> None:
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe is not installed")

    audio_path = tmp_path / "generated.wav"
    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(b"\x00\x00" * 800)

    probe = probe_audio(audio_path)

    assert probe.sample_rate == 8000
    assert probe.channels == 1
    assert probe.duration_seconds == pytest.approx(0.1, abs=0.01)
    assert probe.codec_name is not None
