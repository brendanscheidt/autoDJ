from pathlib import Path

from autodj_analysis import (
    BEAT_THIS_BACKEND,
    BEAT_THIS_LICENSE_NOTE,
    AnalysisContext,
    BackendExecutionError,
    BackendRegistry,
    BeatThisBackend,
    BeatThisPrediction,
    CandidateProvenance,
    DecodedAudio,
    DependencyError,
    TempoCandidate,
    TempoCandidateResult,
    register_beat_this_backends,
)
from autodj_analysis.dependencies import OptionalDependencyUnavailable


class _FakeArray(list):
    @property
    def size(self) -> int:
        return len(self)

    def reshape(self, *_shape):
        return self


class _FakeNumpy:
    float32 = "float32"

    @staticmethod
    def asarray(values, *, dtype=None):
        return _FakeArray(values)


class _FakeCuda:
    def __init__(self, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available


class _FakeTorch:
    def __init__(self, *, cuda_available: bool) -> None:
        self.cuda = _FakeCuda(cuda_available)


class _FakeBeatThisInference:
    def __init__(self) -> None:
        self.init_calls: list[dict] = []
        self.call_count = 0

    def Audio2Beats(self, **kwargs):
        self.init_calls.append(dict(kwargs))
        parent = self

        class Predictor:
            def __call__(_self, samples, sample_rate):
                parent.call_count += 1
                assert isinstance(samples, _FakeArray)
                assert sample_rate == 48000
                return (
                    _FakeArray([0.12, 0.548571, 0.977142, 1.405713]),
                    _FakeArray([0.12, 1.405713]),
                )

        return Predictor()


def _audio() -> DecodedAudio:
    return DecodedAudio(
        samples=[0.0, 0.75, 0.0, -0.75],
        sample_rate=48000,
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


def _tempo(status: str = "ok") -> TempoCandidateResult:
    if status == "ok":
        return TempoCandidateResult(
            status="ok",
            provenance=CandidateProvenance(backend_name="tempo-a"),
            bpm=140.0,
            normalized_bpm=140.0,
            confidence=0.9,
            tempo_class="straight",
            candidates=(TempoCandidate(bpm=140.0, confidence=0.9, backend="tempo-a"),),
        )
    return TempoCandidateResult(
        status=status,
        provenance=CandidateProvenance(backend_name="tempo-a"),
        error=BackendExecutionError(
            code="tempo_failed",
            message="tempo failed",
            backend_name="tempo-a",
        ),
    )


def _prediction(**overrides) -> BeatThisPrediction:
    values = {
        "beats": (0.1, 0.528571, 0.957142, 1.385713),
        "downbeats": (0.1,),
        "checkpoint_path": "small0",
        "requested_device": "auto",
        "effective_device": "cpu",
        "cuda_available": False,
        "dbn": False,
        "float16": False,
        "analysis_sample_rate": 22050,
        "source_sample_rate": 48000,
        "model_load_seconds": 0.05,
        "inference_seconds": 0.2,
    }
    values.update(overrides)
    return BeatThisPrediction(**values)


def test_beat_this_predicts_with_runtime_optional_dependencies_and_auto_device() -> None:
    fake_inference = _FakeBeatThisInference()

    def dependency_loader(_dependency, *, module_name, install_extra):
        if module_name == "numpy":
            assert install_extra == "analysis"
            return _FakeNumpy
        if module_name == "beat_this.inference":
            assert install_extra == "beat-this"
            return fake_inference
        if module_name == "torch":
            assert install_extra == "beat-this"
            return _FakeTorch(cuda_available=True)
        raise AssertionError(module_name)

    backend = BeatThisBackend(
        checkpoint_path="small0",
        device="auto",
        float16=True,
        dependency_loader=dependency_loader,
        version_resolver=lambda package: f"{package}-version",
    )

    prediction = backend.predict(_audio())
    result = backend.beat_grid_result_from_prediction(
        prediction,
        tempo_status="failed",
        processing_seconds=1.25,
    )

    assert fake_inference.init_calls == [
        {"checkpoint_path": "small0", "device": "cuda", "float16": True, "dbn": False}
    ]
    assert fake_inference.call_count == 1
    assert prediction.effective_device == "cuda"
    assert prediction.cuda_available is True
    assert result.ok is True
    assert result.provenance.backend_name == BEAT_THIS_BACKEND
    assert result.provenance.dependency_versions["beat-this"] == "beat-this-version"
    assert result.provenance.parameters["checkpointPath"] == "small0"
    assert result.provenance.parameters["effectiveDevice"] == "cuda"
    assert result.provenance.parameters["tempoStatus"] == "failed"
    assert result.provenance.parameters["licenseNote"] == BEAT_THIS_LICENSE_NOTE
    assert result.provenance.processing_seconds == 1.25
    assert result.beats[0].time_seconds == 0.12
    assert result.downbeats[0].beat_in_bar == 1
    assert result.offset_seconds == 0.12
    assert any("auto-selected device: cuda" in warning for warning in result.provenance.warnings)


def test_beat_this_prediction_mapping_records_cpu_and_missing_downbeat_warnings() -> None:
    backend = BeatThisBackend()

    result = backend.beat_grid_result_from_prediction(_prediction(downbeats=()))

    assert result.ok is True
    assert result.confidence > 0.0
    assert result.downbeats == ()
    assert result.provenance.parameters["cudaAvailable"] is False
    assert result.provenance.parameters["modelLoadSeconds"] == 0.05
    assert result.provenance.parameters["inferenceSeconds"] == 0.2
    assert any("without CUDA" in warning for warning in result.provenance.warnings)
    assert any("no downbeats" in warning for warning in result.provenance.warnings)


def test_beat_this_reports_unavailable_dependency_structurally() -> None:
    def missing_dependency(*_args, **_kwargs):
        raise OptionalDependencyUnavailable(
            DependencyError(
                code="analysis_dependency_missing",
                dependency="beat-this",
                module_name="beat_this.inference",
                install_extra="beat-this",
                message="Beat This is unavailable",
            )
        )

    backend = BeatThisBackend(dependency_loader=missing_dependency)

    result = backend.analyze_beat_grid(_audio(), _tempo(), _context())

    assert result.status == "unavailable"
    assert result.error is not None
    assert result.error.backend_name == BEAT_THIS_BACKEND
    assert result.error.dependency == "beat-this"
    assert result.error.details["installExtra"] == "beat-this"


def test_beat_this_reports_runtime_failures_structurally() -> None:
    class BrokenInference:
        def Audio2Beats(self, **_kwargs):
            raise RuntimeError("model download failed")

    def dependency_loader(_dependency, *, module_name, install_extra):
        if module_name == "numpy":
            return _FakeNumpy
        if module_name == "beat_this.inference":
            return BrokenInference()
        if module_name == "torch":
            return _FakeTorch(cuda_available=False)
        raise AssertionError(module_name)

    backend = BeatThisBackend(dependency_loader=dependency_loader)

    result = backend.analyze_beat_grid(_audio(), _tempo(), _context())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "beat_this_failed"
    assert result.error.details["exceptionType"] == "RuntimeError"


def test_beat_this_registers_only_as_beat_grid_backend() -> None:
    registry = BackendRegistry()

    register_beat_this_backends(registry)

    assert registry.tempo_names() == ()
    assert registry.beat_grid_names() == (BEAT_THIS_BACKEND,)
    assert registry.section_names() == ()
    assert registry.create_beat_grid(BEAT_THIS_BACKEND).name == BEAT_THIS_BACKEND
