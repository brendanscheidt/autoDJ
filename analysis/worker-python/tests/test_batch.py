import json
import importlib.util
from pathlib import Path
import subprocess

import pytest

from audio_fixtures import create_energy_ramp_fixture
from autodj_analysis import (
    ANALYZER_PRODUCER,
    ANALYZER_VERSION,
    DEFAULT_PARAMETERS_HASH,
    AnalysisContext,
    AudioLoadError,
    AudioProbe,
    BackendExecutionError,
    CandidateProvenance,
    CurrentSignalBackend,
    DecodedAudio,
    EnergyFeatures,
    RepositoryTrack,
    SectionCandidate,
    SectionCandidateResult,
    SignalAnalysisResult,
    StructureFeatures,
    TempoFeatures,
    analyzed_track_path,
    analyze_repository_manifest,
    artifact_identity_for_track,
    build_analyzed_track_artifact,
    waveform_path,
)
from autodj_analysis.batch import _select_semantic_section_result


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
        "start_time_seconds": 0.125,
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


def _signal_analyzer(
    *,
    seen_track_ids: list[str] | None = None,
    waveform_peak: float = 0.8,
    fail_track_ids: tuple[str, ...] = (),
):
    failures = set(fail_track_ids)

    def analyze(track, identity, created_at_utc):
        if seen_track_ids is not None:
            seen_track_ids.append(track.track_id)
        if track.track_id in failures:
            raise AudioLoadError(
                "audio_decode_error",
                "Could not decode audio source: synthetic failure",
                source_uri=track.source_uri,
                track_id=track.track_id,
            )
        return _signal_result(
            track.track_id,
            identity.source_content_hash or "",
            identity.parameters_hash or "",
            created_at_utc,
            waveform_peak=waveform_peak,
        )

    return analyze


def _signal_result(
    track_id: str,
    source_content_hash: str,
    parameters_hash: str,
    created_at_utc: str,
    *,
    waveform_peak: float,
) -> SignalAnalysisResult:
    return SignalAnalysisResult(
        waveform_artifact={
            "schemaVersion": "1.0.0",
            "trackId": track_id,
            "analyzer": {
                "producer": ANALYZER_PRODUCER,
                "producerVersion": ANALYZER_VERSION,
                "createdAtUtc": created_at_utc,
                "sourceContentHash": source_content_hash,
                "parametersHash": parameters_hash,
            },
            "durationSeconds": 12.5,
            "sampleRate": 22050,
            "parameters": {
                "targetPointCount": 2,
                "mode": "peak-rms",
            },
            "summary": {
                "peak": waveform_peak,
                "rms": 0.4,
            },
            "points": [
                {"timeSeconds": 0.0, "min": -waveform_peak, "max": waveform_peak, "rms": 0.4},
                {"timeSeconds": 6.25, "min": -0.2, "max": 0.2, "rms": 0.1},
            ],
        },
        energy_features=EnergyFeatures(
            global_energy=0.42,
            curve=(
                {"timeSeconds": 0.0, "value": 0.15},
                {"timeSeconds": 4.0, "value": 0.55},
                {"timeSeconds": 8.0, "value": 0.90},
            ),
            bass_energy_curve=(
                {"timeSeconds": 0.0, "value": 0.10},
                {"timeSeconds": 4.0, "value": 0.50},
                {"timeSeconds": 8.0, "value": 0.85},
            ),
            onset_density_curve=(
                {"timeSeconds": 0.0, "value": 0.05},
                {"timeSeconds": 4.0, "value": 0.30},
                {"timeSeconds": 8.0, "value": 0.75},
            ),
            warnings=(),
            frame_length=2048,
            hop_length=512,
            curve_point_count=512,
            bass_cutoff_hz=180.0,
        ),
        tempo_features=TempoFeatures(
            bpm=140.0,
            normalized_bpm=140.0,
            confidence=0.76,
            tempo_class="straight",
            candidates=({"bpm": 140.0, "confidence": 0.76, "backend": "test"},),
            beats=(
                {"index": 0, "timeSeconds": 0.0, "confidence": 0.72},
                {"index": 1, "timeSeconds": 0.428571, "confidence": 0.72},
            ),
            downbeats=(),
            beat_grid_confidence=0.72,
            warnings=("Downbeats were not emitted.",),
            backend="test",
            hop_length=512,
        ),
        structure_features=StructureFeatures(
            sections=(
                {
                    "id": "section-drop-001",
                    "type": "drop",
                    "startSeconds": 8.0,
                    "endSeconds": 12.5,
                    "energyMean": 0.9,
                    "energyPeak": 0.95,
                    "confidence": 0.68,
                },
            ),
            cue_points=(
                {
                    "id": "cue-drop-001",
                    "type": "drop",
                    "timeSeconds": 8.0,
                    "sectionId": "section-drop-001",
                    "confidence": 0.68,
                    "tags": ["rough"],
                },
            ),
            warnings=("Rough sections and cue candidates are heuristic.",),
            backend="test",
            high_energy_threshold=0.65,
            low_energy_threshold=0.35,
        ),
    )


def _selected_section_result() -> SectionCandidateResult:
    return SectionCandidateResult(
        status="ok",
        provenance=CandidateProvenance(
            backend_name="dubstep-phrase-hybrid",
            backend_version="0.1.0",
            model_name="dubstep-phrase-hybrid",
            model_version="boundary-fusion-v1",
            processing_seconds=1.25,
            warnings=("Experimental dubstep phrase inference.",),
        ),
        sections=(
            SectionCandidate(
                id="section-build-001",
                type="build",
                start_seconds=16.0,
                end_seconds=32.0,
                confidence=0.62,
                source_label="pre-chorus",
                start_beat_index=64,
                end_beat_index=128,
                mapping_notes=("inferred backward from drop anchor",),
            ),
            SectionCandidate(
                id="section-drop-001",
                type="drop",
                start_seconds=32.0,
                end_seconds=64.0,
                confidence=0.71,
                source_label="chorus",
                start_beat_index=128,
                end_beat_index=256,
                provider_metadata={"dropAnchorScore": 0.78},
            ),
            SectionCandidate(
                id="section-break-001",
                type="break",
                start_seconds=64.0,
                end_seconds=80.0,
                confidence=0.55,
                source_label="bridge",
                start_beat_index=256,
                end_beat_index=320,
            ),
        ),
        cue_points=(
            {
                "id": "cue-drop-001",
                "type": "drop",
                "timeSeconds": 32.0,
                "sectionId": "section-drop-001",
                "confidence": 0.71,
                "tags": ["hybrid", "beat_snapped"],
                "beatIndex": 128,
            },
        ),
    )


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
    assert ffprobe["startTimeSeconds"] == 0.125
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


def test_build_analyzed_track_artifact_prefers_selected_section_backend_result() -> None:
    signal = _signal_result(
        "track-drop-001",
        "sha256:source-a",
        "sha256:params",
        "2026-05-16T00:00:00Z",
        waveform_peak=0.8,
    )
    artifact = build_analyzed_track_artifact(
        _track(),
        _probe(),
        created_at_utc="2026-05-16T00:00:00Z",
        energy_features=signal.energy_features,
        tempo_features=signal.tempo_features,
        structure_features=signal.structure_features,
        section_result=_selected_section_result(),
    )

    assert [section["type"] for section in artifact["sections"]] == ["build", "drop", "break"]
    assert artifact["sections"][1]["id"] == "section-drop-001"
    assert artifact["sections"][1]["sourceLabel"] == "chorus"
    assert artifact["sections"][1]["providerMetadata"]["dropAnchorScore"] == 0.78
    assert artifact["cuePoints"] == [
        {
            "id": "cue-drop-001",
            "type": "drop",
            "timeSeconds": 32.0,
            "sectionId": "section-drop-001",
            "confidence": 0.71,
            "tags": ["hybrid", "beat_snapped"],
            "beatIndex": 128,
        }
    ]
    assert any("Experimental dubstep phrase inference" in warning for warning in artifact["quality"]["warnings"])


def test_selected_section_backend_falls_back_to_current_signal_sections_when_unusable() -> None:
    signal = _signal_result(
        "track-drop-001",
        "sha256:source-a",
        "sha256:params",
        "2026-05-16T00:00:00Z",
        waveform_peak=0.8,
    )
    audio = DecodedAudio(
        samples=[],
        sample_rate=22050,
        duration_seconds=12.5,
        channels=1,
        source_path=Path("track-drop-001.wav"),
    )
    context = AnalysisContext(
        track_id="track-drop-001",
        source_path=Path("track-drop-001.wav"),
        analysis_audio_path=Path("track-drop-001.wav"),
        duration_seconds=12.5,
    )

    class EmptySelectedBackend:
        name = "dubstep-phrase-hybrid"

        def analyze_sections(self, _audio, _features, _beat_grid, _context):
            return SectionCandidateResult(
                status="unavailable",
                provenance=CandidateProvenance(backend_name=self.name),
                error=BackendExecutionError(
                    code="model_missing",
                    message="section model is not installed",
                    backend_name=self.name,
                ),
            )

    result = _select_semantic_section_result(
        section_backend="dubstep-phrase-hybrid",
        section_backend_factory=EmptySelectedBackend,
        current_backend=CurrentSignalBackend(),
        audio=audio,
        context=context,
        energy_features=signal.energy_features,
        tempo_features=signal.tempo_features,
        structure_features=signal.structure_features,
        extra_warnings=("analysis WAV could not be written",),
    )

    assert result.status == "ok"
    assert result.provenance.backend_name == "current-autodj-signal"
    assert [section.type for section in result.sections] == ["drop"]
    assert result.cue_points[0]["type"] == "drop"
    assert any("falling back to 'current-autodj-signal'" in warning for warning in result.provenance.warnings)
    assert "analysis WAV could not be written" in result.provenance.warnings


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
    seen_signals: list[str] = []

    result = analyze_repository_manifest(
        manifest_path,
        cache_root,
        ffprobe_path="fake-ffprobe",
        probe_runner=_runner(_ffprobe_payload(), seen_commands),
        signal_analyzer=_signal_analyzer(seen_track_ids=seen_signals),
    )

    assert result.ok is True
    assert result.total_tracks == 2
    assert result.analyzed == 2
    assert result.skipped == 0
    assert result.failed == 0
    assert result.errors == ()
    assert [track.status for track in result.tracks] == ["analyzed", "analyzed"]
    assert len(seen_commands) == 2
    assert seen_signals == ["track-a", "track-b"]

    artifact_a = json.loads(analyzed_track_path(cache_root, "track-a").read_text(encoding="utf-8"))
    artifact_b = json.loads(analyzed_track_path(cache_root, "track-b").read_text(encoding="utf-8"))
    waveform_a = json.loads(waveform_path(cache_root, "track-a").read_text(encoding="utf-8"))
    assert artifact_a["trackId"] == "track-a"
    assert artifact_a["analyzer"]["sourceContentHash"] == "sha256:a"
    assert artifact_a["tempo"]["confidence"] == 0.76
    assert artifact_a["beatGrid"]["beats"]
    assert artifact_a["energy"]["globalEnergy"] == 0.42
    assert artifact_a["sections"][0]["type"] == "drop"
    assert artifact_a["cuePoints"][0]["type"] == "drop"
    assert "Signal analysis populated" in artifact_a["quality"]["warnings"][0]
    assert waveform_a["trackId"] == "track-a"
    assert waveform_a["analyzer"]["sourceContentHash"] == "sha256:a"
    assert artifact_b["trackId"] == "track-b"

    summary = result.to_dict()
    assert summary["ok"] is True
    assert summary["total"] == 2
    assert summary["totalTracks"] == 2
    assert summary["tracks"][0]["artifactPath"] == str(analyzed_track_path(cache_root, "track-a"))
    assert summary["tracks"][0]["waveformPath"] == str(waveform_path(cache_root, "track-a"))


def test_analyze_repository_manifest_skips_current_artifacts_without_probing(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a", "content_hash": "sha256:a"}])
    cache_root = tmp_path / ".autodj-cache"
    analyze_repository_manifest(
        manifest_path,
        cache_root,
        probe_runner=_runner(_ffprobe_payload()),
        signal_analyzer=_signal_analyzer(),
    )

    def fail_if_called(command):
        raise AssertionError(f"unexpected ffprobe call: {command}")

    def fail_signal(track, identity, created_at_utc):
        raise AssertionError(f"unexpected signal analysis: {track.track_id}")

    result = analyze_repository_manifest(
        manifest_path,
        cache_root,
        probe_runner=fail_if_called,
        signal_analyzer=fail_signal,
    )

    assert result.ok is True
    assert result.analyzed == 0
    assert result.skipped == 1
    assert result.failed == 0
    assert result.tracks[0].status == "skipped"
    assert result.tracks[0].reason == "fresh"


def test_analyze_repository_manifest_rewrites_stale_artifacts(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a", "content_hash": "sha256:old"}])
    cache_root = tmp_path / ".autodj-cache"
    analyze_repository_manifest(
        manifest_path,
        cache_root,
        probe_runner=_runner(_ffprobe_payload(duration=10.0)),
        signal_analyzer=_signal_analyzer(),
    )

    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a", "content_hash": "sha256:new"}])
    result = analyze_repository_manifest(
        manifest_path,
        cache_root,
        probe_runner=_runner(_ffprobe_payload(duration=22.0)),
        signal_analyzer=_signal_analyzer(),
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
    analyze_repository_manifest(
        manifest_path,
        cache_root,
        probe_runner=_runner(_ffprobe_payload(duration=10.0)),
        signal_analyzer=_signal_analyzer(waveform_peak=0.25),
    )

    result = analyze_repository_manifest(
        manifest_path,
        cache_root,
        force=True,
        probe_runner=_runner(_ffprobe_payload(duration=33.0)),
        signal_analyzer=_signal_analyzer(waveform_peak=0.95),
    )

    artifact = json.loads(analyzed_track_path(cache_root, "track-a").read_text(encoding="utf-8"))
    waveform = json.loads(waveform_path(cache_root, "track-a").read_text(encoding="utf-8"))
    assert result.analyzed == 1
    assert result.skipped == 0
    assert result.tracks[0].reason == "force"
    assert artifact["durationSeconds"] == 33.0
    assert waveform["summary"]["peak"] == 0.95


def test_analyze_repository_manifest_rewrites_when_waveform_artifact_is_stale(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a", "content_hash": "sha256:a"}])
    cache_root = tmp_path / ".autodj-cache"
    analyze_repository_manifest(
        manifest_path,
        cache_root,
        probe_runner=_runner(_ffprobe_payload(duration=10.0)),
        signal_analyzer=_signal_analyzer(waveform_peak=0.25),
    )
    waveform_path(cache_root, "track-a").unlink()
    seen_signals: list[str] = []

    result = analyze_repository_manifest(
        manifest_path,
        cache_root,
        probe_runner=_runner(_ffprobe_payload(duration=10.0)),
        signal_analyzer=_signal_analyzer(seen_track_ids=seen_signals, waveform_peak=0.75),
    )

    waveform = json.loads(waveform_path(cache_root, "track-a").read_text(encoding="utf-8"))
    assert result.ok is True
    assert result.analyzed == 1
    assert result.skipped == 0
    assert result.tracks[0].reason == "waveform_artifact_missing"
    assert seen_signals == ["track-a"]
    assert waveform["summary"]["peak"] == 0.75


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
        signal_analyzer=_signal_analyzer(),
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


def test_analyze_repository_manifest_continues_after_signal_failure(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path,
        [
            {"track_id": "track-good", "content_hash": "sha256:good"},
            {"track_id": "track-bad", "content_hash": "sha256:bad"},
        ],
    )
    cache_root = tmp_path / ".autodj-cache"
    seen_commands: list[list[str]] = []

    result = analyze_repository_manifest(
        manifest_path,
        cache_root,
        probe_runner=_runner(_ffprobe_payload(), seen_commands),
        signal_analyzer=_signal_analyzer(fail_track_ids=("track-bad",)),
    )

    assert result.ok is False
    assert result.total_tracks == 2
    assert result.analyzed == 1
    assert result.skipped == 0
    assert result.failed == 1
    assert len(seen_commands) == 2
    assert analyzed_track_path(cache_root, "track-good").exists()
    assert waveform_path(cache_root, "track-good").exists()

    failed_track = result.tracks[1]
    assert failed_track.status == "failed"
    assert failed_track.artifact_path == analyzed_track_path(cache_root, "track-bad")
    assert failed_track.waveform_path == waveform_path(cache_root, "track-bad")
    assert failed_track.error is not None
    assert failed_track.error["code"] == "audio_decode_error"
    assert failed_track.error["trackId"] == "track-bad"
    assert failed_track.error["sourceUri"] == "track-bad.mp3"


@pytest.mark.analysis
def test_analyze_repository_manifest_runs_real_signal_analysis_for_generated_audio(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_energy_ramp_fixture(tmp_path / "music", duration_seconds=6.0)
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "track_id": "track-ramp",
                "filename": fixture.path.name,
                "content_hash": "sha256:ramp",
                "create_source": False,
                "title": "Generated Ramp",
            },
        ],
    )
    cache_root = tmp_path / ".autodj-cache"

    result = analyze_repository_manifest(
        manifest_path,
        cache_root,
        probe_runner=_runner(
            _ffprobe_payload(
                duration=fixture.duration_seconds,
                sample_rate=fixture.sample_rate,
                channels=1,
            )
        ),
    )

    artifact = json.loads(analyzed_track_path(cache_root, "track-ramp").read_text(encoding="utf-8"))
    waveform = json.loads(waveform_path(cache_root, "track-ramp").read_text(encoding="utf-8"))

    assert result.ok is True
    assert result.analyzed == 1
    assert result.failed == 0
    assert artifact["analyzer"]["producer"] == ANALYZER_PRODUCER
    assert artifact["analyzer"]["sourceContentHash"] == "sha256:ramp"
    assert artifact["energy"]["curve"]
    assert artifact["energy"]["curve"][-1]["value"] > artifact["energy"]["curve"][0]["value"]
    assert any(section["type"] == "drop" for section in artifact["sections"])
    assert any(cue["type"] == "drop" for cue in artifact["cuePoints"])
    assert waveform["trackId"] == "track-ramp"
    assert waveform["points"]
    assert result.to_dict()["tracks"][0]["waveformPath"] == str(waveform_path(cache_root, "track-ramp"))


def _skip_without_analysis_dependencies() -> None:
    missing = [
        module
        for module in ["numpy", "scipy", "librosa", "soundfile"]
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        pytest.skip(
            "analysis dependencies are not installed; missing "
            + ", ".join(missing)
            + ". Install the worker with `[analysis]`."
        )
