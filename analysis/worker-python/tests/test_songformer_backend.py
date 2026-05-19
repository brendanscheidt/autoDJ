from pathlib import Path

from autodj_analysis import (
    AnalysisContext,
    BackendExecutionError,
    BackendRegistry,
    BeatGridCandidateResult,
    BeatMarker,
    CandidateProvenance,
    DecodedAudio,
    DependencyError,
    FeatureBundle,
    SONGFORMER_BACKEND,
    SONGFORMER_EXPECTED_SAMPLE_RATE,
    SONGFORMER_INSTALL_NOTE,
    SONGFORMER_LICENSE_NOTE,
    SONGFORMER_MODEL_REPO,
    SongFormerBackend,
    register_songformer_backends,
)
from autodj_analysis.dependencies import OptionalDependencyUnavailable


def _audio() -> DecodedAudio:
    return DecodedAudio(
        samples=[0.0, 0.5, 0.0, -0.5],
        sample_rate=44100,
        duration_seconds=48.0,
        channels=1,
        source_path=Path("fixture-analysis.wav"),
    )


def _context() -> AnalysisContext:
    return AnalysisContext(
        track_id="track-001",
        source_path=Path("fixture.mp3"),
        analysis_audio_path=Path("fixture-analysis.wav"),
        duration_seconds=48.0,
    )


def _beat_grid() -> BeatGridCandidateResult:
    return BeatGridCandidateResult(
        status="ok",
        provenance=CandidateProvenance(backend_name="grid-a"),
        beats=(
            BeatMarker(index=0, time_seconds=0.0, beat_in_bar=1, confidence=0.9),
            BeatMarker(index=1, time_seconds=16.0, beat_in_bar=1, confidence=0.9),
            BeatMarker(index=2, time_seconds=32.0, beat_in_bar=1, confidence=0.9),
            BeatMarker(index=3, time_seconds=48.0, beat_in_bar=1, confidence=0.9),
        ),
        confidence=0.9,
    )


def _segments():
    return [
        {"start": 0.0, "end": 16.0, "label": "intro", "confidence": 0.91},
        {"start": 16.0, "end": 32.0, "label": "chorus", "confidence": 0.88},
        {"start": 32.0, "end": 40.0, "label": "breakdown"},
        {"start": 40.0, "end": 48.0, "label": "outro"},
    ]


def test_songformer_maps_runner_outputs_to_section_result() -> None:
    calls: list[tuple[Path, dict]] = []

    def runner(path, options):
        calls.append((path, dict(options)))
        return _segments()

    backend = SongFormerBackend(
        prediction_runner=runner,
        local_dir=Path("models/songformer"),
        version_resolver=lambda package: f"{package}-version",
        module_available=lambda module: module in {"torch", "transformers"},
    )

    result = backend.analyze_sections(_audio(), FeatureBundle(), _beat_grid(), _context())

    assert calls == [
        (
            Path("fixture-analysis.wav"),
            {
                "repoId": SONGFORMER_MODEL_REPO,
                "revision": None,
                "localDir": "models/songformer",
                "device": "cpu",
                "trustRemoteCode": True,
                "lowCpuMemUsage": False,
                "ignorePatterns": ["SongFormer.pt", "SongFormer.safetensors"],
                "expectedSampleRate": SONGFORMER_EXPECTED_SAMPLE_RATE,
            },
        )
    ]
    assert result.ok is True
    assert result.provenance.backend_name == SONGFORMER_BACKEND
    assert result.provenance.dependency_versions["transformers"] == "transformers-version"
    assert result.provenance.parameters["repoId"] == SONGFORMER_MODEL_REPO
    assert result.provenance.parameters["resolvedLocalDir"] == "models/songformer"
    assert result.provenance.parameters["timelineMode"] == "analysis_audio_path"
    assert result.provenance.parameters["effectiveDevice"] == "cpu"
    assert result.provenance.parameters["expectedSampleRate"] == SONGFORMER_EXPECTED_SAMPLE_RATE
    assert result.provenance.parameters["dependencyAvailability"]["torch"] is True
    assert result.provenance.parameters["licenseNote"] == SONGFORMER_LICENSE_NOTE
    assert result.provenance.parameters["installNote"] == SONGFORMER_INSTALL_NOTE
    assert [section.type for section in result.sections] == ["intro", "unknown", "break", "outro"]
    assert result.sections[0].confidence == 0.82
    assert result.sections[0].start_beat_index == 0
    assert result.sections[1].source_label == "chorus"
    assert result.sections[1].confidence == 0.45
    assert "requires energy/bass/onset/phrase evidence" in result.sections[1].mapping_notes[0]
    assert result.sections[2].mapping_notes == ("songformer label normalized",)
    assert any("semantic-section model only" in warning for warning in result.provenance.warnings)
    assert any("trust_remote_code=True" in warning for warning in result.provenance.warnings)


def test_songformer_uses_cached_prediction_for_repeated_section_calls() -> None:
    call_count = 0

    def runner(_path, _options):
        nonlocal call_count
        call_count += 1
        return _segments()

    backend = SongFormerBackend(prediction_runner=runner)

    first = backend.analyze_sections(_audio(), FeatureBundle(), _beat_grid(), _context())
    second = backend.analyze_sections(_audio(), FeatureBundle(), _beat_grid(), _context())

    assert first.ok is True
    assert second.ok is True
    assert call_count == 1


def test_songformer_warns_when_source_timeline_is_used() -> None:
    backend = SongFormerBackend(
        prediction_runner=lambda _path, _options: _segments(),
        prefer_analysis_audio=False,
    )

    result = backend.analyze_sections(_audio(), FeatureBundle(), _beat_grid(), _context())

    assert result.ok is True
    assert result.provenance.parameters["timelineMode"] == "source_path"
    assert any("source path" in warning for warning in result.provenance.warnings)


def test_songformer_reports_unavailable_dependency_structurally() -> None:
    def missing_dependency(*_args, **_kwargs):
        raise OptionalDependencyUnavailable(
            DependencyError(
                code="analysis_dependency_missing",
                dependency="transformers",
                module_name="transformers",
                install_extra="songformer",
                message="transformers is unavailable",
            )
        )

    backend = SongFormerBackend(dependency_loader=missing_dependency)

    result = backend.analyze_sections(_audio(), FeatureBundle(), _beat_grid(), _context())

    assert result.status == "unavailable"
    assert result.error is not None
    assert result.error.backend_name == SONGFORMER_BACKEND
    assert result.error.dependency == "transformers"
    assert result.error.details["installExtra"] == "songformer"


def test_songformer_reports_runtime_failures_structurally() -> None:
    def runner(_path, _options):
        raise RuntimeError("huggingface model snapshot failed")

    backend = SongFormerBackend(prediction_runner=runner)

    result = backend.analyze_sections(_audio(), FeatureBundle(), _beat_grid(), _context())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "songformer_failed"
    assert result.error.details["exceptionType"] == "RuntimeError"


def test_songformer_registers_only_as_section_backend() -> None:
    registry = BackendRegistry()

    register_songformer_backends(registry)

    assert registry.tempo_names() == ()
    assert registry.beat_grid_names() == ()
    assert registry.section_names() == (SONGFORMER_BACKEND,)
    assert registry.create_section(SONGFORMER_BACKEND).name == SONGFORMER_BACKEND
