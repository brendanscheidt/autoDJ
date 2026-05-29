import json
from pathlib import Path
import subprocess

from autodj_analysis import (
    ANALYZER_PRODUCER,
    ANALYZER_VERSION,
    CURRENT_SIGNAL_BACKEND,
    CURRENT_SIGNAL_MODEL_NAME,
    BackendRegistry,
    CurrentSignalBackend,
    DecodedAudio,
    EnergyFeatures,
    FeatureBundle,
    RepositoryTrack,
    SignalAnalysisResult,
    StructureFeatures,
    TempoExtractionError,
    TempoFeatures,
    analyzed_track_path,
    analyze_repository_manifest,
    analyze_track_signal,
    artifact_identity_for_track,
    register_current_signal_backends,
    waveform_path,
)
import autodj_analysis.backends.current_signal as current_signal_module


def _decoded_audio(*, source_path: Path | None = None) -> DecodedAudio:
    return DecodedAudio(
        samples=(0.0, 0.25, -0.4, 0.1),
        sample_rate=4,
        duration_seconds=1.0,
        channels=1,
        source_path=source_path or Path("synthetic.wav"),
    )


def _energy_features() -> EnergyFeatures:
    return EnergyFeatures(
        global_energy=0.42,
        curve=(
            {"timeSeconds": 0.0, "value": 0.2},
            {"timeSeconds": 0.5, "value": 0.8},
        ),
        bass_energy_curve=({"timeSeconds": 0.5, "value": 0.7},),
        onset_density_curve=({"timeSeconds": 0.5, "value": 0.6},),
        warnings=("energy warning",),
        frame_length=2048,
        hop_length=512,
        curve_point_count=512,
        bass_cutoff_hz=180.0,
    )


def _tempo_features() -> TempoFeatures:
    return TempoFeatures(
        bpm=140.0,
        normalized_bpm=140.0,
        confidence=0.91,
        tempo_class="straight",
        candidates=(
            {"bpm": 140.0, "confidence": 0.91, "backend": "electronic_quantized_grid"},
            {"bpm": 70.0, "confidence": 0.4, "backend": "librosa.beat_track"},
        ),
        beats=(
            {"index": 0, "timeSeconds": 0.125, "confidence": 0.88},
            {"index": 1, "timeSeconds": 0.553571, "confidence": 0.88},
        ),
        downbeats=({"index": 0, "timeSeconds": 0.125, "beatInBar": 1, "confidence": 0.5},),
        beat_grid_confidence=0.88,
        warnings=("tempo warning",),
        backend="electronic_quantized_grid",
        hop_length=512,
    )


def _structure_features() -> StructureFeatures:
    return StructureFeatures(
        sections=(
            {
                "id": "section-drop-001",
                "type": "drop",
                "startSeconds": 0.553571,
                "endSeconds": 1.0,
                "energyMean": 0.8,
                "energyPeak": 0.9,
                "confidence": 0.7,
                "startBeatIndex": 1,
            },
        ),
        cue_points=(
            {
                "id": "cue-drop-001",
                "type": "drop",
                "timeSeconds": 0.553571,
                "sectionId": "section-drop-001",
                "confidence": 0.7,
                "tags": ["rough", "beat_snapped"],
                "beatIndex": 1,
            },
        ),
        warnings=("section warning",),
        backend="heuristic-energy-onset-v1",
        high_energy_threshold=0.65,
        low_energy_threshold=0.35,
    )


def _track(source_path: Path) -> RepositoryTrack:
    return RepositoryTrack(
        track_id="track-a",
        repository_id="local-test-repo",
        source_uri=source_path.name,
        source_path=source_path,
        content_hash="sha256:track-a",
        format_hint="mp3",
        title="Track A",
    )


def _context(track: RepositoryTrack | None = None):
    track = track or _track(Path("track-a.mp3"))
    return CurrentSignalBackend().context_for_track(
        track,
        artifact_identity_for_track(track),
        _decoded_audio(source_path=track.source_path),
        ffprobe_start_time_seconds=0.012,
    )


def _ffprobe_payload() -> dict:
    return {
        "streams": [
            {
                "index": 0,
                "codec_type": "audio",
                "codec_name": "mp3",
                "codec_long_name": "MP3",
                "sample_rate": "44100",
                "channels": 2,
                "duration": "1.000000",
                "disposition": {"default": 1},
            }
        ],
        "format": {"duration": "1.000000", "format_name": "mp3"},
    }


def _completed(command, payload: dict):
    return subprocess.CompletedProcess(
        args=list(command),
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )


def test_current_signal_feature_results_include_incumbent_provenance() -> None:
    backend = CurrentSignalBackend()

    tempo = backend.tempo_result_from_features(_tempo_features(), processing_seconds=0.123)
    beat_grid = backend.beat_grid_result_from_features(_tempo_features(), processing_seconds=0.01)
    sections = backend.section_result_from_features(_structure_features(), processing_seconds=0.02)

    assert tempo.ok is True
    assert tempo.provenance.backend_name == CURRENT_SIGNAL_BACKEND
    assert tempo.provenance.model_name == CURRENT_SIGNAL_MODEL_NAME
    assert tempo.provenance.parameters["tempoBackend"] == "electronic_quantized_grid"
    assert tempo.provenance.parameters["tempoHopLength"] == 512
    assert tempo.provenance.warnings == ("tempo warning",)
    assert tempo.candidates[0].backend == "electronic_quantized_grid"

    assert beat_grid.beats[0].time_seconds == 0.125
    assert beat_grid.downbeats[0].beat_in_bar == 1
    assert beat_grid.offset_seconds == 0.125
    assert beat_grid.provenance.parameters["beatCount"] == 2

    assert sections.sections[0].type == "drop"
    assert sections.sections[0].source_label == "drop"
    assert sections.sections[0].provider_metadata["sourceBackend"] == "heuristic-energy-onset-v1"
    assert sections.cue_points[0]["type"] == "drop"


def test_current_signal_backend_reports_structured_unavailable_tempo_dependency() -> None:
    def missing_tempo(_audio):
        raise TempoExtractionError(
            "tempo_dependency_missing",
            "librosa is not installed",
            dependency="librosa",
        )

    backend = CurrentSignalBackend(tempo_extractor=missing_tempo)

    result = backend.analyze_tempo(_decoded_audio(), _context())

    assert result.status == "unavailable"
    assert result.error is not None
    assert result.error.code == "tempo_dependency_missing"
    assert result.error.dependency == "librosa"
    assert result.provenance.backend_name == CURRENT_SIGNAL_BACKEND


def test_current_signal_load_track_audio_preserves_canonical_sample_rate() -> None:
    source_path = Path("canonical.wav")
    seen = {}

    def audio_loader(audio_path, **kwargs):
        seen["audio_path"] = Path(audio_path)
        seen["kwargs"] = kwargs
        return _decoded_audio(source_path=Path(audio_path))

    track = RepositoryTrack(
        track_id="track-a",
        repository_id="local-test-repo",
        source_uri="track-a.mp3",
        source_path=source_path,
        provider_metadata={
            "autodjAnalysisAudio": {
                "timelinePolicy": "shared-canonical-pcm",
                "canonicalPath": str(source_path),
            }
        },
    )

    audio = CurrentSignalBackend(audio_loader=audio_loader).load_track_audio(track)

    assert audio.source_path == source_path
    assert seen["audio_path"] == source_path
    assert seen["kwargs"]["target_sample_rate"] is None
    assert seen["kwargs"]["source_uri"] == "track-a.mp3"
    assert seen["kwargs"]["track_id"] == "track-a"


def test_current_signal_section_backend_uses_tempo_features_from_feature_bundle() -> None:
    seen_tempo_features: list[TempoFeatures | None] = []

    def structure_extractor(energy, *, tempo_features, duration_seconds):
        assert energy == _energy_features()
        assert duration_seconds == 1.0
        seen_tempo_features.append(tempo_features)
        return _structure_features()

    backend = CurrentSignalBackend(structure_extractor=structure_extractor)
    tempo_features = _tempo_features()

    result = backend.analyze_sections(
        _decoded_audio(),
        FeatureBundle(energy=_energy_features(), extras={"tempoFeatures": tempo_features}),
        backend.beat_grid_result_from_features(tempo_features),
        _context(),
    )

    assert result.ok is True
    assert seen_tempo_features == [tempo_features]
    assert result.sections[0].start_beat_index == 1


def test_current_signal_debug_waveform_uses_existing_artifact_shape() -> None:
    def debug_builder(track_id, audio, *, analyzer_producer, analyzer_version, created_at_utc):
        assert audio == _decoded_audio()
        return {
            "schemaVersion": "1.0.0",
            "artifactType": "debug-waveform",
            "trackId": track_id,
            "analyzer": {
                "producer": analyzer_producer,
                "producerVersion": analyzer_version,
                "createdAtUtc": created_at_utc,
            },
            "durationSeconds": 1.0,
            "sampleRate": 4,
            "parameters": {"targetPointCount": 2, "mode": "rgb-band-transient"},
            "summary": {"peak": 0.4, "rms": 0.2},
            "points": [],
        }

    backend = CurrentSignalBackend(debug_waveform_builder=debug_builder, backend_version="test-version")
    artifact = backend.build_debug_waveform(
        _decoded_audio(),
        _context(),
        created_at_utc="2026-05-17T00:00:00Z",
    )

    assert artifact["artifactType"] == "debug-waveform"
    assert artifact["analyzer"]["producer"] == "autodj_analysis.debug_waveform"
    assert artifact["analyzer"]["producerVersion"] == "test-version"
    assert artifact["parameters"]["mode"] == "rgb-band-transient"


def test_current_signal_backends_register_for_all_contract_kinds() -> None:
    registry = BackendRegistry()

    register_current_signal_backends(registry)

    assert registry.tempo_names() == (CURRENT_SIGNAL_BACKEND,)
    assert registry.beat_grid_names() == (CURRENT_SIGNAL_BACKEND,)
    assert registry.section_names() == (CURRENT_SIGNAL_BACKEND,)
    assert registry.create_tempo(CURRENT_SIGNAL_BACKEND).name == CURRENT_SIGNAL_BACKEND
    assert registry.create_beat_grid(CURRENT_SIGNAL_BACKEND).name == CURRENT_SIGNAL_BACKEND
    assert registry.create_section(CURRENT_SIGNAL_BACKEND).name == CURRENT_SIGNAL_BACKEND


def test_track_signal_analyzer_can_use_selected_current_signal_section_backend(monkeypatch, tmp_path: Path) -> None:
    track = _track(tmp_path / "track-a.mp3")
    identity = artifact_identity_for_track(track)
    selected_signal_result = SignalAnalysisResult(
        waveform_artifact={"trackId": "track-a"},
        energy_features=_energy_features(),
        tempo_features=_tempo_features(),
        structure_features=_structure_features(),
    )
    calls = []

    class FakeCurrentSignalBackend:
        def analyze_decoded_signal(self, seen_track, seen_identity, seen_created_at_utc, seen_audio):
            calls.append((seen_track, seen_identity, seen_created_at_utc, seen_audio.source_path))
            return selected_signal_result

        def load_track_audio(self, seen_track):
            return _decoded_audio(source_path=seen_track.source_path)

        def section_result_from_features(self, features):
            return CurrentSignalBackend().section_result_from_features(features)

    monkeypatch.setattr(current_signal_module, "CurrentSignalBackend", FakeCurrentSignalBackend)

    result = analyze_track_signal(
        track,
        identity,
        "2026-05-18T00:00:00Z",
        section_backend=CURRENT_SIGNAL_BACKEND,
    )

    assert result.waveform_artifact == {"trackId": "track-a"}
    assert result.section_result is not None
    assert result.section_result.provenance.backend_name == CURRENT_SIGNAL_BACKEND
    assert calls == [(track, identity, "2026-05-18T00:00:00Z", track.source_path)]


def test_current_signal_analyzer_preserves_legacy_artifact_composition(tmp_path: Path) -> None:
    music_root = tmp_path / "music"
    music_root.mkdir()
    source_path = music_root / "track-a.mp3"
    source_path.write_bytes(b"synthetic audio")
    manifest_path = tmp_path / "repository-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "repositoryId": "local-test-repo",
                "producer": "test",
                "producerVersion": "1.0.0",
                "createdAtUtc": "2026-05-17T00:00:00Z",
                "source": {"repositoryType": "local", "rootUri": str(music_root)},
                "tracks": [
                    {
                        "trackId": "track-a",
                        "repositoryId": "local-test-repo",
                        "sourceUri": "track-a.mp3",
                        "contentHash": "sha256:track-a",
                        "title": "Track A",
                        "formatHint": "mp3",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def audio_loader(audio_path, *, source_uri, track_id):
        assert Path(audio_path) == source_path
        assert source_uri == "track-a.mp3"
        assert track_id == "track-a"
        return _decoded_audio(source_path=Path(audio_path))

    def waveform_builder(
        track_id,
        audio,
        *,
        analyzer_producer,
        analyzer_version,
        source_content_hash,
        parameters_hash,
        created_at_utc,
    ):
        assert audio == _decoded_audio(source_path=source_path)
        return {
            "schemaVersion": "1.0.0",
            "trackId": track_id,
            "analyzer": {
                "producer": analyzer_producer,
                "producerVersion": analyzer_version,
                "createdAtUtc": created_at_utc,
                "sourceContentHash": source_content_hash,
                "parametersHash": parameters_hash,
            },
            "durationSeconds": 1.0,
            "sampleRate": 4,
            "parameters": {"targetPointCount": 2, "mode": "peak-rms"},
            "summary": {"peak": 0.4, "rms": 0.2},
            "points": [{"timeSeconds": 0.0, "min": -0.4, "max": 0.4, "rms": 0.2}],
        }

    backend = CurrentSignalBackend(
        audio_loader=audio_loader,
        waveform_builder=waveform_builder,
        energy_extractor=lambda _audio: _energy_features(),
        tempo_extractor=lambda _audio: _tempo_features(),
        structure_extractor=lambda _energy, **_kwargs: _structure_features(),
    )

    result = analyze_repository_manifest(
        manifest_path,
        tmp_path / ".autodj-cache",
        probe_runner=lambda command: _completed(command, _ffprobe_payload()),
        signal_analyzer=backend.as_signal_analyzer(),
    )

    analyzed = json.loads(
        analyzed_track_path(tmp_path / ".autodj-cache", "track-a").read_text(encoding="utf-8")
    )
    waveform = json.loads(
        waveform_path(tmp_path / ".autodj-cache", "track-a").read_text(encoding="utf-8")
    )

    assert result.ok is True
    assert analyzed["analyzer"]["producer"] == ANALYZER_PRODUCER
    assert analyzed["analyzer"]["producerVersion"] == ANALYZER_VERSION
    assert analyzed["tempo"]["bpm"] == 140.0
    assert analyzed["beatGrid"]["beats"][0]["timeSeconds"] == 0.125
    assert analyzed["energy"]["globalEnergy"] == 0.42
    assert analyzed["sections"][0]["type"] == "drop"
    assert analyzed["cuePoints"][0]["type"] == "drop"
    assert waveform["trackId"] == "track-a"
    assert waveform["analyzer"]["sourceContentHash"] == "sha256:track-a"
    assert waveform["parameters"]["mode"] == "peak-rms"
