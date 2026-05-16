import json
from pathlib import Path
import subprocess

from autodj_analysis import (
    AudioProbe,
    RepositoryTrack,
    analyzed_track_path,
    analyze_repository_manifest,
    build_analyzed_track_artifact,
)


CONTRACT_ROOT = Path(__file__).resolve().parents[3] / "core" / "contracts"
ANALYZED_TRACK_SCHEMA = CONTRACT_ROOT / "schemas" / "analyzed-track.schema.json"


def _track(**overrides) -> RepositoryTrack:
    values = {
        "track_id": "track-contract-001",
        "repository_id": "local-test-repo",
        "source_uri": "contract-track.mp3",
        "source_path": Path("contract-track.mp3"),
        "content_hash": "sha256:contract-track",
        "format_hint": "mp3",
        "title": "Contract Track",
        "artist": "Contract Artist",
        "album": "Contract Album",
        "duration_seconds": 180.0,
        "sample_rate": 48000,
        "channels": 2,
        "provider_metadata": {},
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
        "tags": {},
        "raw": {"streams": [], "format": {}},
    }
    values.update(overrides)
    return AudioProbe(**values)


def _completed(command, payload: dict):
    return subprocess.CompletedProcess(
        args=list(command),
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )


def _ffprobe_payload() -> dict:
    return {
        "streams": [
            {
                "index": 0,
                "codec_type": "audio",
                "codec_name": "mp3",
                "sample_rate": "48000",
                "channels": 2,
                "duration": "182.500000",
                "bit_rate": "320000",
                "disposition": {"default": 1},
            }
        ],
        "format": {
            "duration": "182.500000",
            "format_name": "mp3",
        },
    }


def _write_manifest(tmp_path: Path) -> Path:
    music_root = tmp_path / "music"
    music_root.mkdir()
    (music_root / "contract-track.mp3").write_bytes(b"fake audio bytes")

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
                "tracks": [
                    {
                        "trackId": "track-contract-001",
                        "repositoryId": "local-test-repo",
                        "sourceUri": "contract-track.mp3",
                        "contentHash": "sha256:contract-track",
                        "title": "Contract Track",
                        "formatHint": "mp3",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _schema() -> dict:
    return json.loads(ANALYZED_TRACK_SCHEMA.read_text(encoding="utf-8"))


def _assert_required_keys(payload: dict, required: list[str], label: str) -> None:
    missing = [field for field in required if field not in payload]
    assert missing == [], f"{label} missing required fields: {missing}"


def _assert_generated_artifact_matches_required_contract_shape(artifact: dict) -> None:
    schema = _schema()
    defs = schema["$defs"]

    _assert_required_keys(artifact, schema["required"], "AnalyzedTrack")
    _assert_required_keys(artifact["source"], defs["trackAsset"]["required"], "source")
    _assert_required_keys(artifact["analyzer"], defs["analyzerProvenance"]["required"], "analyzer")
    _assert_required_keys(artifact["tempo"], defs["tempoAnalysis"]["required"], "tempo")
    _assert_required_keys(artifact["key"], defs["keyAnalysis"]["required"], "key")
    _assert_required_keys(artifact["beatGrid"], defs["beatGrid"]["required"], "beatGrid")
    _assert_required_keys(artifact["energy"], defs["energyAnalysis"]["required"], "energy")
    _assert_required_keys(artifact["vocals"], defs["vocalAnalysis"]["required"], "vocals")
    _assert_required_keys(artifact["quality"], defs["analysisQuality"]["required"], "quality")

    assert isinstance(artifact["sections"], list)
    assert isinstance(artifact["cuePoints"], list)
    assert isinstance(artifact["beatGrid"]["beats"], list)
    assert isinstance(artifact["beatGrid"]["downbeats"], list)
    assert isinstance(artifact["energy"]["curve"], list)
    assert isinstance(artifact["vocals"]["regions"], list)
    assert isinstance(artifact["quality"]["warnings"], list)


def test_generated_artifact_matches_required_analyzed_track_contract_shape() -> None:
    artifact = build_analyzed_track_artifact(
        _track(),
        _probe(),
        created_at_utc="2026-05-16T00:00:00Z",
    )

    _assert_generated_artifact_matches_required_contract_shape(artifact)


def test_batch_written_artifact_matches_required_analyzed_track_contract_shape(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    cache_root = tmp_path / ".autodj-cache"

    analyze_repository_manifest(
        manifest_path,
        cache_root,
        ffprobe_path="fake-ffprobe",
        probe_runner=lambda command: _completed(command, _ffprobe_payload()),
    )

    artifact = json.loads(analyzed_track_path(cache_root, "track-contract-001").read_text(encoding="utf-8"))
    _assert_generated_artifact_matches_required_contract_shape(artifact)


def test_generated_artifact_does_not_fake_high_confidence_musical_analysis() -> None:
    artifact = build_analyzed_track_artifact(
        _track(),
        _probe(),
        created_at_utc="2026-05-16T00:00:00Z",
    )

    assert artifact["tempo"]["confidence"] == 0.0
    assert artifact["tempo"]["candidates"] == []
    assert artifact["key"]["confidence"] == 0.0
    assert artifact["key"]["candidates"] == []
    assert artifact["beatGrid"] == {"beats": [], "downbeats": [], "confidence": 0.0}
    assert artifact["sections"] == []
    assert artifact["energy"] == {
        "globalEnergy": 0.0,
        "curve": [],
        "bassEnergyCurve": [],
        "onsetDensityCurve": [],
    }
    assert artifact["vocals"] == {"hasVocals": False, "confidence": 0.0, "regions": []}
    assert "stems" not in artifact
    assert artifact["cuePoints"] == []
    assert artifact["quality"]["overallConfidence"] == 0.1
    assert "Only FFprobe" in artifact["quality"]["warnings"][0]
    assert "low-confidence placeholders" in artifact["quality"]["warnings"][0]
