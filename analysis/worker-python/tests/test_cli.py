import json
from pathlib import Path
import subprocess

import pytest

from autodj_analysis import analyzed_track_path
from autodj_analysis.cli import main


def test_cli_classify_prints_json(capsys) -> None:
    exit_code = main(["classify", "cli-track.wav"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["primaryGenre"] == "dubstep"


def test_cli_analyze_writes_artifact_and_prints_path(tmp_path, capsys) -> None:
    exit_code = main(["analyze", "cli-track.wav", "--out", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert (tmp_path / "analyzed-track.json").exists()


def _completed(command, payload: dict, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=list(command),
        returncode=returncode,
        stdout=json.dumps(payload),
        stderr=stderr,
    )


def _ffprobe_payload(duration: float = 12.5) -> dict:
    return {
        "streams": [
            {
                "index": 0,
                "codec_type": "audio",
                "codec_name": "mp3",
                "sample_rate": "48000",
                "channels": 2,
                "duration": f"{duration:.6f}",
            }
        ],
        "format": {
            "duration": f"{duration:.6f}",
            "format_name": "mp3",
        },
    }


def _runner(payload: dict, seen_commands: list[list[str]] | None = None):
    def run(command):
        if seen_commands is not None:
            seen_commands.append(list(command))
        return _completed(command, payload)

    return run


def _write_manifest(tmp_path: Path, tracks: list[dict]) -> Path:
    music_root = tmp_path / "music"
    music_root.mkdir(exist_ok=True)
    manifest_tracks = []

    for track in tracks:
        track_id = track["track_id"]
        filename = track.get("filename", f"{track_id}.mp3")
        if track.get("create_source", True):
            (music_root / filename).write_bytes(b"fake audio bytes")
        manifest_tracks.append(
            {
                "trackId": track_id,
                "repositoryId": "local-test-repo",
                "sourceUri": filename,
                "contentHash": track.get("content_hash", f"sha256:{track_id}"),
                "title": track_id,
                "formatHint": "mp3",
            }
        )

    manifest_path = tmp_path / "repository-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "repositoryId": "local-test-repo",
                "producer": "autodj.repository.local",
                "producerVersion": "0.1.0",
                "createdAtUtc": "2026-05-16T00:00:00Z",
                "source": {
                    "repositoryType": "local",
                    "rootUri": str(music_root),
                },
                "tracks": manifest_tracks,
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_cli_analyze_batch_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["analyze-batch", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "repository_manifest" in captured.out
    assert "--ffprobe" in captured.out
    assert "--force" in captured.out
    assert "--parameters-hash" in captured.out
    assert "--json" in captured.out


def test_cli_analyze_batch_json_summary_output(tmp_path, capsys) -> None:
    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a", "content_hash": "sha256:a"}])
    cache_root = tmp_path / ".autodj-cache"
    seen_commands: list[list[str]] = []

    exit_code = main(
        [
            "analyze-batch",
            str(manifest_path),
            "--out",
            str(cache_root),
            "--ffprobe",
            "fake-ffprobe",
            "--parameters-hash",
            "sha256:cli-params",
            "--json",
        ],
        probe_runner=_runner(_ffprobe_payload(), seen_commands),
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    artifact = json.loads(analyzed_track_path(cache_root, "track-a").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert captured.err == ""
    assert payload["ok"] is True
    assert payload["totalTracks"] == 1
    assert payload["analyzed"] == 1
    assert payload["tracks"][0]["status"] == "analyzed"
    assert payload["tracks"][0]["artifactPath"] == str(analyzed_track_path(cache_root, "track-a"))
    assert seen_commands[0][0] == "fake-ffprobe"
    assert artifact["analyzer"]["parametersHash"] == "sha256:cli-params"


def test_cli_analyze_batch_successful_human_output(tmp_path, capsys) -> None:
    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a"}])
    cache_root = tmp_path / ".autodj-cache"

    exit_code = main(
        ["analyze-batch", str(manifest_path), "--out", str(cache_root)],
        probe_runner=_runner(_ffprobe_payload()),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Batch analysis ok" in captured.out
    assert "Tracks: total=1, analyzed=1, skipped=0, failed=0" in captured.out
    assert "- track-a: analyzed" in captured.out
    assert captured.err == ""
    assert analyzed_track_path(cache_root, "track-a").exists()


def test_cli_analyze_batch_manifest_failure_is_actionable(tmp_path, capsys) -> None:
    missing_manifest = tmp_path / "missing" / "repository-manifest.json"

    exit_code = main(["analyze-batch", str(missing_manifest), "--out", str(tmp_path / "cache")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Could not read repository manifest" in captured.err
    assert "Traceback" not in captured.err


def test_cli_analyze_batch_partial_failure_returns_nonzero_after_summary(tmp_path, capsys) -> None:
    manifest_path = _write_manifest(
        tmp_path,
        [
            {"track_id": "track-good", "content_hash": "sha256:good"},
            {"track_id": "track-missing", "content_hash": "sha256:missing", "create_source": False},
        ],
    )
    cache_root = tmp_path / ".autodj-cache"

    exit_code = main(
        ["analyze-batch", str(manifest_path), "--out", str(cache_root), "--json"],
        probe_runner=_runner(_ffprobe_payload()),
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert captured.err == ""
    assert payload["ok"] is False
    assert payload["totalTracks"] == 2
    assert payload["analyzed"] == 1
    assert payload["failed"] == 1
    assert payload["errors"][0]["code"] == "source_missing"
    assert payload["errors"][0]["trackId"] == "track-missing"
