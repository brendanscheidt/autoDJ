import json
from pathlib import Path

import pytest

from autodj_analysis import (
    ManifestError,
    load_repository_manifest,
    parse_repository_manifest,
    resolve_source_path,
)


def _manifest(root_uri: str, source_uri: str = "nested/Drop One.wav") -> dict:
    return {
        "schemaVersion": "1.0.0",
        "repositoryId": "local-test-repo",
        "producer": "autodj.repository.local",
        "producerVersion": "0.1.0",
        "createdAtUtc": "2026-05-16T00:00:00Z",
        "source": {
            "repositoryType": "local",
            "rootUri": root_uri,
            "providerMetadata": {"scanMode": "test"},
        },
        "tracks": [
            {
                "trackId": "track-drop-one",
                "repositoryId": "local-test-repo",
                "sourceUri": source_uri,
                "contentHash": "sha256:exact-content-hash",
                "title": "Drop One",
                "artist": "AutoDJ Fixture",
                "album": "Manifest Tests",
                "durationSeconds": 180.25,
                "sampleRate": 48000,
                "channels": 2,
                "formatHint": "wav",
                "providerMetadata": {"extension": ".wav"},
            }
        ],
    }


def test_parse_repository_manifest_recovers_tracks_and_preserves_identity(tmp_path: Path) -> None:
    root = tmp_path / "music"
    payload = _manifest(str(root), "nested/Drop One.wav")

    manifest = parse_repository_manifest(payload)

    assert manifest.schema_version == "1.0.0"
    assert manifest.repository_id == "local-test-repo"
    assert manifest.producer == "autodj.repository.local"
    assert manifest.producer_version == "0.1.0"
    assert manifest.created_at_utc == "2026-05-16T00:00:00Z"
    assert manifest.source.repository_type == "local"
    assert manifest.source.root_uri == str(root)
    assert manifest.source.root_path == root
    assert manifest.source.provider_metadata == {"scanMode": "test"}
    assert len(manifest.tracks) == 1

    track = manifest.tracks[0]
    assert track.track_id == "track-drop-one"
    assert track.repository_id == "local-test-repo"
    assert track.source_uri == "nested/Drop One.wav"
    assert track.source_path == root / "nested" / "Drop One.wav"
    assert track.content_hash == "sha256:exact-content-hash"
    assert track.title == "Drop One"
    assert track.artist == "AutoDJ Fixture"
    assert track.album == "Manifest Tests"
    assert track.duration_seconds == 180.25
    assert track.sample_rate == 48000
    assert track.channels == 2
    assert track.format_hint == "wav"
    assert track.provider_metadata == {"extension": ".wav"}


def test_load_repository_manifest_reads_json_file(tmp_path: Path) -> None:
    manifest_path = tmp_path / "repository-manifest.json"
    manifest_path.write_text(json.dumps(_manifest(str(tmp_path))), encoding="utf-8")

    manifest = load_repository_manifest(manifest_path)

    assert manifest.manifest_path == manifest_path
    assert manifest.tracks[0].track_id == "track-drop-one"


def test_manifest_reader_resolves_file_root_uri_without_changing_source_uri(tmp_path: Path) -> None:
    root = tmp_path / "music"
    payload = _manifest(root.as_uri(), "relative/drop.mp3")

    manifest = parse_repository_manifest(payload)

    assert manifest.source.root_uri == root.as_uri()
    assert manifest.source.root_path == root
    assert manifest.tracks[0].source_uri == "relative/drop.mp3"
    assert manifest.tracks[0].source_path == root / "relative" / "drop.mp3"


def test_manifest_reader_keeps_absolute_platform_source_uri_as_probe_path(tmp_path: Path) -> None:
    audio_path = tmp_path / "absolute" / "drop.mp3"
    source_uri = audio_path.as_posix()
    payload = _manifest(str(tmp_path), source_uri)

    manifest = parse_repository_manifest(payload)

    assert manifest.tracks[0].source_uri == source_uri
    assert manifest.tracks[0].source_path == audio_path


def test_resolve_source_path_leaves_nonlocal_uri_as_path_candidate() -> None:
    assert resolve_source_path("fixture://autodj/local/track-a.wav") == Path("fixture://autodj/local/track-a.wav")


def test_load_repository_manifest_reports_malformed_json(tmp_path: Path) -> None:
    manifest_path = tmp_path / "repository-manifest.json"
    manifest_path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(ManifestError) as exc_info:
        load_repository_manifest(manifest_path)

    assert exc_info.value.code == "manifest_parse_error"
    assert exc_info.value.source_uri == str(manifest_path)


def test_load_repository_manifest_reports_read_errors(tmp_path: Path) -> None:
    manifest_path = tmp_path / "missing" / "repository-manifest.json"

    with pytest.raises(ManifestError) as exc_info:
        load_repository_manifest(manifest_path)

    assert exc_info.value.code == "manifest_read_error"
    assert exc_info.value.source_uri == str(manifest_path)


def test_parse_repository_manifest_reports_missing_top_level_fields(tmp_path: Path) -> None:
    payload = _manifest(str(tmp_path))
    del payload["repositoryId"]

    with pytest.raises(ManifestError) as exc_info:
        parse_repository_manifest(payload)

    assert exc_info.value.code == "manifest_missing_field"
    assert "manifest.repositoryId" in exc_info.value.message


def test_parse_repository_manifest_reports_missing_provenance_fields(tmp_path: Path) -> None:
    payload = _manifest(str(tmp_path))
    del payload["producerVersion"]

    with pytest.raises(ManifestError) as exc_info:
        parse_repository_manifest(payload)

    assert exc_info.value.code == "manifest_missing_field"
    assert "manifest.producerVersion" in exc_info.value.message


def test_parse_repository_manifest_reports_missing_track_fields(tmp_path: Path) -> None:
    payload = _manifest(str(tmp_path))
    del payload["tracks"][0]["sourceUri"]

    with pytest.raises(ManifestError) as exc_info:
        parse_repository_manifest(payload)

    assert exc_info.value.code == "manifest_missing_field"
    assert "manifest.tracks[0].sourceUri" in exc_info.value.message


def test_parse_repository_manifest_reports_unsupported_schema(tmp_path: Path) -> None:
    payload = _manifest(str(tmp_path))
    payload["schemaVersion"] = "9.9.9"

    with pytest.raises(ManifestError) as exc_info:
        parse_repository_manifest(payload)

    assert exc_info.value.code == "manifest_schema_unsupported"
