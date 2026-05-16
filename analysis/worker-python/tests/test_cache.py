import json
from pathlib import Path

import pytest

from autodj_analysis import (
    ArtifactIdentity,
    CacheError,
    analyzed_track_path,
    check_artifact_freshness,
    load_analyzed_artifact,
    track_cache_dir,
    write_json_atomic,
)


def _identity(**overrides) -> ArtifactIdentity:
    values = {
        "track_id": "track-drop-001",
        "analyzer_producer": "autodj_analysis.ffprobe",
        "analyzer_version": "0.1.0",
        "source_content_hash": "sha256:source-a",
        "parameters_hash": "sha256:params-a",
    }
    values.update(overrides)
    return ArtifactIdentity(**values)


def _artifact(**overrides) -> dict:
    artifact = {
        "schemaVersion": "1.0.0",
        "trackId": "track-drop-001",
        "analyzer": {
            "producer": "autodj_analysis.ffprobe",
            "producerVersion": "0.1.0",
            "createdAtUtc": "2026-05-16T00:00:00Z",
            "sourceContentHash": "sha256:source-a",
            "parametersHash": "sha256:params-a",
        },
    }
    for key, value in overrides.items():
        if key.startswith("analyzer."):
            artifact["analyzer"][key.split(".", 1)[1]] = value
        else:
            artifact[key] = value
    return artifact


def _loaded(tmp_path: Path, artifact: dict | None = None):
    artifact_path = tmp_path / "analyzed-track.json"
    artifact_path.write_text(json.dumps(artifact or _artifact()), encoding="utf-8")
    return load_analyzed_artifact(artifact_path)


def test_analyzed_track_path_resolves_without_creating_directories(tmp_path: Path) -> None:
    artifact_path = analyzed_track_path(tmp_path, "track-drop-001")

    assert artifact_path == tmp_path / "tracks" / "track-drop-001" / "analyzed-track.json"
    assert track_cache_dir(tmp_path, "track-drop-001") == tmp_path / "tracks" / "track-drop-001"
    assert not (tmp_path / "tracks").exists()


def test_analyzed_track_path_rejects_unsafe_track_ids(tmp_path: Path) -> None:
    with pytest.raises(CacheError) as exc_info:
        analyzed_track_path(tmp_path, "../outside")

    assert exc_info.value.code == "artifact_path_error"


def test_write_json_atomic_creates_artifact_parent_and_cleans_temp_files(tmp_path: Path) -> None:
    artifact_path = analyzed_track_path(tmp_path, "track-drop-001")

    written_path = write_json_atomic(artifact_path, _artifact())

    assert written_path == artifact_path
    assert json.loads(artifact_path.read_text(encoding="utf-8"))["trackId"] == "track-drop-001"
    assert not list(artifact_path.parent.glob("*.tmp"))
    assert not (artifact_path.parent / "waveform.json").exists()
    assert not (artifact_path.parent / "stems").exists()


def test_write_json_atomic_replaces_existing_artifact(tmp_path: Path) -> None:
    artifact_path = analyzed_track_path(tmp_path, "track-drop-001")
    write_json_atomic(artifact_path, _artifact(trackId="track-drop-001"))

    write_json_atomic(artifact_path, _artifact(trackId="track-drop-002"))

    assert json.loads(artifact_path.read_text(encoding="utf-8"))["trackId"] == "track-drop-002"


def test_write_json_atomic_reports_serialization_errors(tmp_path: Path) -> None:
    artifact_path = analyzed_track_path(tmp_path, "track-drop-001")

    with pytest.raises(CacheError) as exc_info:
        write_json_atomic(artifact_path, {"bad": object()})

    assert exc_info.value.code == "artifact_write_error"
    assert not artifact_path.exists()
    assert not list(artifact_path.parent.glob("*.tmp"))


def test_load_analyzed_artifact_reports_missing_without_raising(tmp_path: Path) -> None:
    result = load_analyzed_artifact(tmp_path / "missing.json")

    assert not result.loaded
    assert result.error_code == "artifact_missing"
    assert result.artifact is None


def test_load_analyzed_artifact_reports_malformed_json_without_raising(tmp_path: Path) -> None:
    artifact_path = tmp_path / "analyzed-track.json"
    artifact_path.write_text("{ bad json", encoding="utf-8")

    result = load_analyzed_artifact(artifact_path)

    assert not result.loaded
    assert result.error_code == "artifact_malformed_json"


def test_load_analyzed_artifact_reports_non_object_json_without_raising(tmp_path: Path) -> None:
    artifact_path = tmp_path / "analyzed-track.json"
    artifact_path.write_text("[]", encoding="utf-8")

    result = load_analyzed_artifact(artifact_path)

    assert not result.loaded
    assert result.error_code == "artifact_malformed_json"


def test_check_artifact_freshness_accepts_matching_artifact(tmp_path: Path) -> None:
    decision = check_artifact_freshness(_loaded(tmp_path), _identity())

    assert decision.is_fresh is True
    assert decision.should_analyze is False
    assert decision.reason == "fresh"


def test_check_artifact_freshness_detects_stale_content_hash(tmp_path: Path) -> None:
    decision = check_artifact_freshness(
        _loaded(tmp_path, _artifact(**{"analyzer.sourceContentHash": "sha256:old"})),
        _identity(),
    )

    assert decision.is_fresh is False
    assert decision.reason == "source_content_hash_mismatch"


def test_check_artifact_freshness_detects_stale_analyzer_version(tmp_path: Path) -> None:
    decision = check_artifact_freshness(
        _loaded(tmp_path, _artifact(**{"analyzer.producerVersion": "0.0.1"})),
        _identity(),
    )

    assert decision.reason == "analyzer_version_mismatch"


def test_check_artifact_freshness_detects_stale_parameters_hash(tmp_path: Path) -> None:
    decision = check_artifact_freshness(
        _loaded(tmp_path, _artifact(**{"analyzer.parametersHash": "sha256:old"})),
        _identity(),
    )

    assert decision.reason == "parameters_hash_mismatch"


def test_check_artifact_freshness_detects_missing_required_fields(tmp_path: Path) -> None:
    artifact = _artifact()
    del artifact["analyzer"]["producer"]

    decision = check_artifact_freshness(_loaded(tmp_path, artifact), _identity())

    assert decision.reason == "artifact_missing_field"
    assert "analyzer.producer" in decision.message


def test_check_artifact_freshness_rechecks_malformed_artifacts(tmp_path: Path) -> None:
    artifact_path = tmp_path / "analyzed-track.json"
    artifact_path.write_text("{ bad json", encoding="utf-8")

    decision = check_artifact_freshness(load_analyzed_artifact(artifact_path), _identity())

    assert decision.reason == "artifact_malformed_json"
    assert decision.should_analyze is True


def test_check_artifact_freshness_force_rewrites_current_artifact(tmp_path: Path) -> None:
    decision = check_artifact_freshness(_loaded(tmp_path), _identity(), force=True)

    assert decision.is_fresh is False
    assert decision.reason == "force"


def test_check_artifact_freshness_requires_source_and_parameter_hashes(tmp_path: Path) -> None:
    source_decision = check_artifact_freshness(_loaded(tmp_path), _identity(source_content_hash=None))
    parameter_decision = check_artifact_freshness(_loaded(tmp_path), _identity(parameters_hash=None))

    assert source_decision.reason == "source_content_hash_unavailable"
    assert parameter_decision.reason == "parameters_hash_unavailable"
