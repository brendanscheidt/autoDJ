from pathlib import Path

from autodj_analysis import (
    ESSENTIA_RHYTHM_BACKEND,
    ESSENTIA_RHYTHM_LICENSE_NOTE,
    AnalysisContext,
    BackendExecutionError,
    BackendRegistry,
    CandidateProvenance,
    DecodedAudio,
    DependencyError,
    EssentiaRhythmBackend,
    EssentiaRhythmFeatures,
    TempoCandidateResult,
    register_essentia_rhythm_backends,
)
from autodj_analysis.dependencies import OptionalDependencyUnavailable


class _FakeArray(list):
    @property
    def size(self) -> int:
        return len(self)

    def reshape(self, *_shape):
        return self

    def astype(self, *_args, **_kwargs):
        return self


class _FakeNumpy:
    float32 = "float32"

    @staticmethod
    def asarray(values, *, dtype=None):
        return _FakeArray(values)


class _FakeEssentiaStandard:
    def __init__(self) -> None:
        self.extractor_calls: list[dict] = []
        self.resample_calls: list[dict] = []

    def RhythmExtractor2013(self, **kwargs):
        self.extractor_calls.append(dict(kwargs))

        class Extractor:
            def __call__(_self, samples):
                assert isinstance(samples, _FakeArray)
                return (
                    142.0,
                    _FakeArray([0.1, 0.522535, 0.94507, 1.367605]),
                    0.61,
                    _FakeArray([142.0, 142.0, 142.5, 71.0]),
                    _FakeArray([0.422535, 0.422535, 0.421053]),
                )

        return Extractor()

    def Resample(self, **kwargs):
        self.resample_calls.append(dict(kwargs))

        class Resampler:
            def __call__(_self, samples):
                return _FakeArray(samples)

        return Resampler()


def _audio(*, sample_rate: int = 44100) -> DecodedAudio:
    return DecodedAudio(
        samples=[0.0, 1.0, 0.0, -1.0],
        sample_rate=sample_rate,
        duration_seconds=1.5,
        channels=1,
        source_path=Path("fixture.wav"),
    )


def _context() -> AnalysisContext:
    return AnalysisContext(
        track_id="track-001",
        source_path=Path("fixture.mp3"),
        analysis_audio_path=Path("fixture.wav"),
        duration_seconds=1.5,
    )


def _features(**overrides) -> EssentiaRhythmFeatures:
    values = {
        "bpm": 70.0,
        "ticks": (0.1, 0.528571, 0.957142, 1.385713, 1.814284),
        "confidence": 0.0,
        "estimates": (70.0, 70.0, 140.0, 70.5),
        "bpm_intervals": (0.857142, 0.857142, 0.428571),
        "source_sample_rate": 22050,
        "analysis_sample_rate": 44100,
        "method": "multifeature",
        "min_tempo_bpm": 50.0,
        "max_tempo_bpm": 220.0,
        "resampled": True,
    }
    values.update(overrides)
    return EssentiaRhythmFeatures(**values)


def test_essentia_rhythm_extracts_with_runtime_optional_dependencies() -> None:
    fake_essentia = _FakeEssentiaStandard()

    def dependency_loader(_dependency, *, module_name, install_extra):
        assert install_extra == "analysis-wsl"
        if module_name == "numpy":
            return _FakeNumpy
        if module_name == "essentia.standard":
            return fake_essentia
        raise AssertionError(module_name)

    backend = EssentiaRhythmBackend(
        method="multifeature",
        min_tempo_bpm=60.0,
        max_tempo_bpm=190.0,
        dependency_loader=dependency_loader,
    )

    features = backend.extract_features(_audio(sample_rate=22050))

    assert features.bpm == 142.0
    assert features.ticks == (0.1, 0.522535, 0.94507, 1.367605)
    assert features.confidence == 0.61
    assert features.resampled is True
    assert fake_essentia.resample_calls == [
        {"inputSampleRate": 22050.0, "outputSampleRate": 44100.0}
    ]
    assert fake_essentia.extractor_calls == [
        {"method": "multifeature", "minTempo": 60.0, "maxTempo": 190.0}
    ]


def test_essentia_rhythm_maps_features_to_tempo_and_beat_grid_results() -> None:
    backend = EssentiaRhythmBackend(version_resolver=lambda package: f"{package}-version")

    tempo = backend.tempo_result_from_features(_features(), processing_seconds=0.25)
    beat_grid = backend.beat_grid_result_from_features(_features(), processing_seconds=0.11)

    assert tempo.ok is True
    assert tempo.provenance.backend_name == ESSENTIA_RHYTHM_BACKEND
    assert tempo.provenance.dependency_versions["essentia"] == "essentia-version"
    assert tempo.provenance.parameters["licenseNote"] == ESSENTIA_RHYTHM_LICENSE_NOTE
    assert tempo.provenance.parameters["rawConfidence"] == 0.0
    assert tempo.provenance.processing_seconds == 0.25
    assert tempo.bpm == 70.0
    assert tempo.normalized_bpm == 140.0
    assert tempo.tempo_class == "halftime"
    assert tempo.confidence > 0.0
    assert tempo.candidates[0].backend == "essentia.RhythmExtractor2013"
    assert any(candidate.bpm == 140.0 for candidate in tempo.candidates)

    assert beat_grid.ok is True
    assert beat_grid.provenance.backend_name == ESSENTIA_RHYTHM_BACKEND
    assert beat_grid.provenance.parameters["beatCount"] == 5
    assert beat_grid.provenance.processing_seconds == 0.11
    assert beat_grid.beats[0].to_dict() == {
        "index": 0,
        "timeSeconds": 0.1,
        "confidence": beat_grid.confidence,
    }
    assert beat_grid.downbeats == ()
    assert beat_grid.offset_seconds == 0.1
    assert any("AGPLv3" in warning for warning in beat_grid.provenance.warnings)


def test_essentia_rhythm_reports_unavailable_dependency_structurally() -> None:
    def missing_dependency(*_args, **_kwargs):
        raise OptionalDependencyUnavailable(
            DependencyError(
                code="analysis_dependency_missing",
                dependency="essentia",
                module_name="essentia.standard",
                install_extra="analysis-wsl",
                message="Essentia is unavailable",
            )
        )

    backend = EssentiaRhythmBackend(dependency_loader=missing_dependency)

    result = backend.analyze_tempo(_audio(), _context())

    assert result.status == "unavailable"
    assert result.error is not None
    assert result.error.backend_name == ESSENTIA_RHYTHM_BACKEND
    assert result.error.dependency == "essentia"
    assert result.error.details["installExtra"] == "analysis-wsl"


def test_essentia_rhythm_beat_grid_requires_ok_tempo_result() -> None:
    backend = EssentiaRhythmBackend()
    tempo = TempoCandidateResult(
        status="failed",
        provenance=CandidateProvenance(backend_name="tempo-a"),
        error=BackendExecutionError(
            code="tempo_failed",
            message="tempo failed",
            backend_name="tempo-a",
        ),
    )

    result = backend.analyze_beat_grid(_audio(), tempo, _context())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "tempo_result_not_ok"
    assert result.provenance.parameters["tempoStatus"] == "failed"


def test_essentia_rhythm_registers_tempo_and_beat_grid_backends() -> None:
    registry = BackendRegistry()

    register_essentia_rhythm_backends(registry)

    assert registry.tempo_names() == (ESSENTIA_RHYTHM_BACKEND,)
    assert registry.beat_grid_names() == (ESSENTIA_RHYTHM_BACKEND,)
    assert registry.section_names() == ()
    assert registry.create_tempo(ESSENTIA_RHYTHM_BACKEND).name == ESSENTIA_RHYTHM_BACKEND
    assert registry.create_beat_grid(ESSENTIA_RHYTHM_BACKEND).name == ESSENTIA_RHYTHM_BACKEND
