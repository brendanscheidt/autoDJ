import json
from pathlib import Path
import subprocess
import wave

import pytest

from autodj_analysis.canonical_audio import (
    CANONICAL_AUDIO_FILENAME,
    CANONICAL_AUDIO_METADATA_FILENAME,
    CanonicalAudioError,
    CanonicalAudioOptions,
    canonical_audio_paths,
    canonicalize_audio_file,
    canonicalize_repository_manifest,
)


def _write_source(path: Path, payload: bytes = b"source-audio") -> None:
    path.write_bytes(payload)


def _write_wav(path: Path, *, sample_rate: int = 44_100, frames: int = 4_410) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frames)


def _probe_runner(sample_rate: int = 44_100):
    def run(command):
        payload = {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "mp3",
                    "codec_long_name": "MP3",
                    "sample_rate": str(sample_rate),
                    "channels": 2,
                    "duration": "1.000",
                    "start_time": "0.000",
                }
            ],
            "format": {"duration": "1.000", "format_name": "mp3", "format_long_name": "MP3"},
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    return run


class _FakeFfmpeg:
    def __init__(self) -> None:
        self.decode_count = 0
        self.commands = []

    def __call__(self, command):
        self.commands.append(tuple(command))
        if tuple(command) == ("ffmpeg", "-version"):
            return subprocess.CompletedProcess(command, 0, stdout="ffmpeg fake 1.0\n", stderr="")
        self.decode_count += 1
        output = Path(command[-1])
        sample_rate = 44_100
        if "-ar" in command:
            sample_rate = int(command[command.index("-ar") + 1])
        _write_wav(output, sample_rate=sample_rate)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_canonicalize_audio_file_writes_pcm_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "song.mp3"
    _write_source(source)
    runner = _FakeFfmpeg()

    result = canonicalize_audio_file(
        source,
        tmp_path / "canonical",
        track_id="song-1",
        source_uri="song.mp3",
        repository_id="repo",
        command_runner=runner,
        probe_runner=_probe_runner(),
    )

    paths = canonical_audio_paths(tmp_path / "canonical", "song-1")
    assert result.status == "canonicalized"
    assert result.canonical_path == paths.audio_path
    assert result.metadata_path == paths.metadata_path
    assert paths.audio_path.name == CANONICAL_AUDIO_FILENAME
    assert paths.metadata_path.name == CANONICAL_AUDIO_METADATA_FILENAME
    assert result.sample_rate == 44_100
    assert result.channels == 1
    assert runner.decode_count == 1

    metadata = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
    assert metadata["artifactType"] == "canonical-audio"
    assert metadata["timelinePolicy"] == "shared-canonical-pcm"
    assert metadata["trackId"] == "song-1"
    assert metadata["repositoryId"] == "repo"
    assert metadata["decoder"]["version"] == "ffmpeg fake 1.0"
    assert metadata["sourceContentHash"].startswith("sha256:")


def test_canonicalize_audio_file_skips_fresh_artifact(tmp_path: Path) -> None:
    source = tmp_path / "song.mp3"
    _write_source(source)
    runner = _FakeFfmpeg()
    output_root = tmp_path / "canonical"

    first = canonicalize_audio_file(
        source,
        output_root,
        track_id="song-1",
        command_runner=runner,
        probe_runner=_probe_runner(),
    )
    second = canonicalize_audio_file(
        source,
        output_root,
        track_id="song-1",
        command_runner=runner,
        probe_runner=_probe_runner(),
    )

    assert first.status == "canonicalized"
    assert second.status == "skipped"
    assert runner.decode_count == 1


def test_canonicalize_audio_file_regenerates_when_sample_rate_options_change(tmp_path: Path) -> None:
    source = tmp_path / "song.mp3"
    _write_source(source)
    runner = _FakeFfmpeg()
    output_root = tmp_path / "canonical"

    first = canonicalize_audio_file(
        source,
        output_root,
        track_id="song-1",
        options=CanonicalAudioOptions(target_sample_rate=44_100),
        command_runner=runner,
        probe_runner=_probe_runner(sample_rate=44_100),
    )
    second = canonicalize_audio_file(
        source,
        output_root,
        track_id="song-1",
        options=CanonicalAudioOptions(target_sample_rate=48_000),
        command_runner=runner,
        probe_runner=_probe_runner(sample_rate=44_100),
    )

    assert first.status == "canonicalized"
    assert second.status == "canonicalized"
    assert second.sample_rate == 48_000
    assert runner.decode_count == 2


def test_canonicalize_audio_file_regenerates_when_source_hash_changes(tmp_path: Path) -> None:
    source = tmp_path / "song.mp3"
    _write_source(source, b"v1")
    runner = _FakeFfmpeg()
    output_root = tmp_path / "canonical"

    canonicalize_audio_file(
        source,
        output_root,
        track_id="song-1",
        command_runner=runner,
        probe_runner=_probe_runner(),
    )
    _write_source(source, b"v2")
    result = canonicalize_audio_file(
        source,
        output_root,
        track_id="song-1",
        command_runner=runner,
        probe_runner=_probe_runner(),
    )

    assert result.status == "canonicalized"
    assert runner.decode_count == 2


def test_canonicalize_audio_file_rejects_unsupported_extension(tmp_path: Path) -> None:
    source = tmp_path / "song.txt"
    _write_source(source)

    with pytest.raises(CanonicalAudioError) as error:
        canonicalize_audio_file(source, tmp_path / "canonical", track_id="song-1")

    assert error.value.code == "audio_unsupported_format"


def test_canonicalize_repository_manifest_writes_summary(tmp_path: Path) -> None:
    audio_root = tmp_path / "audio"
    audio_root.mkdir()
    source = audio_root / "song.mp3"
    _write_source(source)
    manifest = tmp_path / "repository-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "repositoryId": "repo",
                "producer": "test",
                "producerVersion": "1.0.0",
                "createdAtUtc": "2026-05-22T00:00:00Z",
                "source": {"repositoryType": "local", "rootUri": str(audio_root)},
                "tracks": [
                    {
                        "trackId": "song-1",
                        "repositoryId": "repo",
                        "sourceUri": "song.mp3",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = canonicalize_repository_manifest(
        manifest,
        tmp_path / "canonical",
        command_runner=_FakeFfmpeg(),
        probe_runner=_probe_runner(),
    )

    assert summary["ok"] is True
    assert summary["canonicalized"] == 1
    assert (tmp_path / "canonical" / "canonical-audio-summary.json").exists()
