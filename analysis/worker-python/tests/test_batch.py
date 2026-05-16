import json
from pathlib import Path
import subprocess

from autodj_analysis import (
    ANALYZER_PRODUCER,
    ANALYZER_VERSION,
    DEFAULT_PARAMETERS_HASH,
    AudioProbe,
    RepositoryTrack,
    analyzed_track_path,
    analyze_repository_manifest,
    artifact_identity_for_track,
    build_analyzed_track_artifact,
)


def _track(**overrides) -> RepositoryTrack:
    values = {
        "track_id": "track-drop-001",
        "repository_id": "local-test-repo",
        "source_uri": "C:/Music/Drop One.mp3",
        "source_path": Path("C:/Music/Drop One.mp3"),
        "content_hash": "sha256:source-a",
        "format_hint": "mp3",
        "title": "Manifest Title",
        "artist": "Manifest Artist",
        "album": "Manifest Album",
        "duration_seconds": 180.0,
        "sample_rate": 44100,
        "channels": 2,
        "provider_metadata": {"repositoryField": "kept"},
    }
    values.update(overrides)
    return RepositoryTrack(**values)


def _probe(**overrides) -> AudioProbe:
    values = {
        "duration_seconds": 182.5,
        "sample_rate": 48000,
        "channels": 2,
        "codec_name": "mp3",
        "codec_long_name": "MP3 (MPEG audio layer 3)",
        "bit_rate": 320000,
        "format_name": "mp3",
        "format_long_name": "MP2/3 (MPEG audio layer 2/3)",
        "tags": {
            "title": "Probe Title",
            "artist": "Probe Artist",
            "album": "Probe Album",
        },
        "raw": {"streams": [], "format": {}},
    }
    values.update(overrides)
    return AudioProbe(**values)


def _completed(command, payload: dict, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=list(command),
        returncode=returncode,
        stdout=json.dumps(payload),
        stderr=stderr,
    )


def _ffprobe_payload(*, duration: float = 12.5, sample_rate: int = 48000, channels: int = 2) -> dict:
    return {
        "streams": [
            {
                "index": 0,
                "codec_type": "audio",
                "codec_name": "mp3",
                "codec_long_name": "MP3 (MPEG audio layer 3)",
                "sample_rate": str(sample_rate),
                "channels": channels,
                "duration": f"{duration:.6f}",
                "bit_rate": "320000",
                "disposition": {"default": 1},
            }
        ],
        "format": {
            "duration": f"{duration:.6f}",
            "format_name": "mp3",
            "format_long_name": "MP2/3 (MPEG audio layer 2/3)",
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
        source_path = music_root / filename
        if track.get("create_source", True):
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(b"fake audio bytes")
        manifest_tracks.append(
            {
                "trackId": track_id,
                "repositoryId": "local-test-repo",
                "sourceUri": filename,
                "contentHash": track.get("content_hash", f"sha256:{track_id}"),
                "title": track.get("title", track_id),
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


def test_build_analyzed_track_artifact_has_required_top_level_shape() -> None:
    artifact = build_analyzed_track_artifact(_track(), _probe(), created_at_utc="2026-05-16T00:00:00Z")

    assert {
        "schemaVersion",
        "trackId",
        "source",
        "analyzer",
        "durationSeconds",
        "tempo",
        "key",
        "beatGrid",
        "sections",
        "energy",
        "vocals",
        "cuePoints",
        "quality",
    }.issubset(artifact.keys())
    assert artifact["schemaVersion"] == "1.0.0"
    assert artifact["trackId"] == "track-drop-001"


def test_build_analyzed_track_artifact_preserves_repository_identity_and_manifest_fields() -> None:
    artifact = build_analyzed_track_artifact(_track(), _probe(), created_at_utc="2026-05-16T00:00:00Z")

    source = artifact["source"]
    assert source["trackId"] == "track-drop-001"
    assert source["repositoryId"] == "local-test-repo"
    assert source["sourceUri"] == "C:/Music/Drop One.mp3"
    assert source["contentHash"] == "sha256:source-a"
    assert source["formatHint"] == "mp3"
    assert source["title"] == "Manifest Title"
    assert source["artist"] == "Manifest Artist"
    assert source["album"] == "Manifest Album"
    assert source["providerMetadata"]["repositoryField"] == "kept"


def test_build_analyzed_track_artifact_populates_real_probe_metadata() -> None:
    artifact = build_analyzed_track_artifact(_track(), _probe(), created_at_utc="2026-05-16T00:00:00Z")

    assert artifact["durationSeconds"] == 182.5
    assert artifact["source"]["durationSeconds"] == 182.5
    assert artifact["source"]["sampleRate"] == 48000
    assert artifact["source"]["channels"] == 2

    ffprobe = artifact["source"]["providerMetadata"]["ffprobe"]
    assert ffprobe["codecName"] == "mp3"
    assert ffprobe["codecLongName"] == "MP3 (MPEG audio layer 3)"
    assert ffprobe["bitRate"] == 320000
    assert ffprobe["formatName"] == "mp3"
    assert ffprobe["formatLongName"] == "MP2/3 (MPEG audio layer 2/3)"
    assert ffprobe["tags"]["title"] == "Probe Title"


def test_build_analyzed_track_artifact_populates_analyzer_provenance() -> None:
    artifact = build_analyzed_track_artifact(
        _track(),
        _probe(),
        parameters_hash="sha256:test-params",
        created_at_utc="2026-05-16T00:00:00Z",
    )

    assert artifact["analyzer"] == {
        "producer": ANALYZER_PRODUCER,
        "producerVersion": ANALYZER_VERSION,
        "createdAtUtc": "2026-05-16T00:00:00Z",
        "sourceContentHash": "sha256:source-a",
        "parametersHash": "sha256:test-params",
    }


def test_build_analyzed_track_artifact_uses_honest_low_confidence_placeholders() -> None:
    artifact = build_analyzed_track_artifact(_track(), _probe(), created_at_utc="2026-05-16T00:00:00Z")

    assert artifact["tempo"]["confidence"] == 0.0
    assert artifact["tempo"]["candidates"] == []
    assert artifact["key"]["confidence"] == 0.0
    assert artifact["beatGrid"] == {"beats": [], "downbeats": [], "confidence": 0.0}
    assert artifact["sections"] == []
    assert artifact["energy"]["globalEnergy"] == 0.0
    assert artifact["energy"]["curve"] == []
    assert artifact["vocals"] == {"hasVocals": False, "confidence": 0.0, "regions": []}
    assert artifact["cuePoints"] == []
    assert artifact["quality"]["overallConfidence"] == 0.1
    assert "Only FFprobe" in artifact["quality"]["warnings"][0]
    assert "low-confidence placeholders" in artifact["quality"]["warnings"][0]


def test_build_analyzed_track_artifact_derives_title_from_probe_tags_then_filename() -> None:
    tagged = build_analyzed_track_artifact(
        _track(title=None),
        _probe(tags={"TITLE": "Tagged Title"}),
        created_at_utc="2026-05-16T00:00:00Z",
    )
    fallback = build_analyzed_track_artifact(
        _track(title=None, source_path=Path("C:/Music/Filename Title.wav")),
        _probe(tags={}),
        created_at_utc="2026-05-16T00:00:00Z",
    )

    assert tagged["source"]["title"] == "Tagged Title"
    assert fallback["source"]["title"] == "Filename Title"


def test_build_analyzed_track_artifact_falls_back_to_manifest_duration_when_probe_duration_missing() -> None:
    artifact = build_analyzed_track_artifact(
        _track(duration_seconds=180.0),
        _probe(duration_seconds=None),
        created_at_utc="2026-05-16T00:00:00Z",
    )

    assert artifact["durationSeconds"] == 180.0
    assert artifact["source"]["durationSeconds"] == 180.0


def test_build_analyzed_track_artifact_handles_missing_optional_probe_and_content_hash() -> None:
    artifact = build_analyzed_track_artifact(
        _track(content_hash=None, duration_seconds=None),
        _probe(duration_seconds=None, sample_rate=None, channels=None, bit_rate=None, tags={}),
        created_at_utc="2026-05-16T00:00:00Z",
    )

    assert artifact["durationSeconds"] == 0.0
    assert "contentHash" not in artifact["source"]
    assert "sourceContentHash" not in artifact["analyzer"]
    assert "sampleRate" not in artifact["source"]
    assert "channels" not in artifact["source"]
    assert any("Duration was unavailable" in warning for warning in artifact["quality"]["warnings"])
    assert any("Sample rate was unavailable" in warning for warning in artifact["quality"]["warnings"])
    assert any("Channel count was unavailable" in warning for warning in artifact["quality"]["warnings"])


def test_artifact_identity_for_track_matches_batch_defaults() -> None:
    identity = artifact_identity_for_track(_track())

    assert identity.track_id == "track-drop-001"
    assert identity.analyzer_producer == ANALYZER_PRODUCER
    assert identity.analyzer_version == ANALYZER_VERSION
    assert identity.source_content_hash == "sha256:source-a"
    assert identity.parameters_hash == DEFAULT_PARAMETERS_HASH


def test_analyze_repository_manifest_analyzes_all_tracks_and_writes_artifacts(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path,
        [
            {"track_id": "track-a", "content_hash": "sha256:a"},
            {"track_id": "track-b", "content_hash": "sha256:b"},
        ],
    )
    cache_root = tmp_path / ".autodj-cache"
    seen_commands: list[list[str]] = []

    result = analyze_repository_manifest(
        manifest_path,
        cache_root,
        ffprobe_path="fake-ffprobe",
        probe_runner=_runner(_ffprobe_payload(), seen_commands),
    )

    assert result.ok is True
    assert result.total_tracks == 2
    assert result.analyzed == 2
    assert result.skipped == 0
    assert result.failed == 0
    assert result.errors == ()
    assert [track.status for track in result.tracks] == ["analyzed", "analyzed"]
    assert len(seen_commands) == 2

    artifact_a = json.loads(analyzed_track_path(cache_root, "track-a").read_text(encoding="utf-8"))
    artifact_b = json.loads(analyzed_track_path(cache_root, "track-b").read_text(encoding="utf-8"))
    assert artifact_a["trackId"] == "track-a"
    assert artifact_a["analyzer"]["sourceContentHash"] == "sha256:a"
    assert artifact_b["trackId"] == "track-b"

    summary = result.to_dict()
    assert summary["ok"] is True
    assert summary["total"] == 2
    assert summary["totalTracks"] == 2
    assert summary["tracks"][0]["artifactPath"] == str(analyzed_track_path(cache_root, "track-a"))


def test_analyze_repository_manifest_skips_current_artifacts_without_probing(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a", "content_hash": "sha256:a"}])
    cache_root = tmp_path / ".autodj-cache"
    analyze_repository_manifest(manifest_path, cache_root, probe_runner=_runner(_ffprobe_payload()))

    def fail_if_called(command):
        raise AssertionError(f"unexpected ffprobe call: {command}")

    result = analyze_repository_manifest(manifest_path, cache_root, probe_runner=fail_if_called)

    assert result.ok is True
    assert result.analyzed == 0
    assert result.skipped == 1
    assert result.failed == 0
    assert result.tracks[0].status == "skipped"
    assert result.tracks[0].reason == "fresh"


def test_analyze_repository_manifest_rewrites_stale_artifacts(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a", "content_hash": "sha256:old"}])
    cache_root = tmp_path / ".autodj-cache"
    analyze_repository_manifest(manifest_path, cache_root, probe_runner=_runner(_ffprobe_payload(duration=10.0)))

    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a", "content_hash": "sha256:new"}])
    result = analyze_repository_manifest(
        manifest_path,
        cache_root,
        probe_runner=_runner(_ffprobe_payload(duration=22.0)),
    )

    artifact = json.loads(analyzed_track_path(cache_root, "track-a").read_text(encoding="utf-8"))
    assert result.analyzed == 1
    assert result.skipped == 0
    assert result.tracks[0].reason == "source_content_hash_mismatch"
    assert artifact["durationSeconds"] == 22.0
    assert artifact["analyzer"]["sourceContentHash"] == "sha256:new"


def test_analyze_repository_manifest_force_rewrites_current_artifacts(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a", "content_hash": "sha256:a"}])
    cache_root = tmp_path / ".autodj-cache"
    analyze_repository_manifest(manifest_path, cache_root, probe_runner=_runner(_ffprobe_payload(duration=10.0)))

    result = analyze_repository_manifest(
        manifest_path,
        cache_root,
        force=True,
        probe_runner=_runner(_ffprobe_payload(duration=33.0)),
    )

    artifact = json.loads(analyzed_track_path(cache_root, "track-a").read_text(encoding="utf-8"))
    assert result.analyzed == 1
    assert result.skipped == 0
    assert result.tracks[0].reason == "force"
    assert artifact["durationSeconds"] == 33.0


def test_analyze_repository_manifest_continues_after_per_track_failure(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path,
        [
            {"track_id": "track-good", "content_hash": "sha256:good"},
            {"track_id": "track-missing", "content_hash": "sha256:missing", "create_source": False},
        ],
    )
    cache_root = tmp_path / ".autodj-cache"
    seen_commands: list[list[str]] = []

    result = analyze_repository_manifest(
        manifest_path,
        cache_root,
        probe_runner=_runner(_ffprobe_payload(), seen_commands),
    )

    assert result.ok is False
    assert result.total_tracks == 2
    assert result.analyzed == 1
    assert result.skipped == 0
    assert result.failed == 1
    assert len(seen_commands) == 1
    assert analyzed_track_path(cache_root, "track-good").exists()

    failed_track = result.tracks[1]
    assert failed_track.status == "failed"
    assert failed_track.error is not None
    assert failed_track.error["code"] == "source_missing"
    assert failed_track.error["trackId"] == "track-missing"
    assert failed_track.error["sourceUri"] == "track-missing.mp3"
    assert result.errors == (failed_track.error,)
