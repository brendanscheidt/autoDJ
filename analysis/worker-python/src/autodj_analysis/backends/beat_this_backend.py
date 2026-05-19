"""Beat This backend adapter for beat and downbeat candidates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
import time
from typing import Any

from .. import __version__
from ..audio_io import DecodedAudio
from ..dependencies import OptionalDependencyUnavailable, require_optional_dependency
from .base import (
    AnalysisContext,
    BackendExecutionError,
    BeatGridCandidateResult,
    BeatMarker,
    CandidateProvenance,
    TempoCandidateResult,
)
from .registry import BackendRegistry


BEAT_THIS_BACKEND = "beat-this"
BEAT_THIS_MODEL_NAME = "Beat This"
BEAT_THIS_LICENSE_NOTE = (
    "Beat This package code is MIT licensed; checkpoint/model and training-data terms "
    "must be reviewed before product distribution."
)
DEFAULT_BEAT_THIS_CHECKPOINT = "final0"
DEFAULT_BEAT_THIS_DEVICE = "auto"
DEFAULT_BEAT_THIS_DBN = False
DEFAULT_BEAT_THIS_FLOAT16 = False
BEAT_THIS_ANALYSIS_SAMPLE_RATE = 22_050


@dataclass(frozen=True)
class BeatThisPrediction:
    beats: tuple[float, ...]
    downbeats: tuple[float, ...]
    checkpoint_path: str
    requested_device: str
    effective_device: str
    cuda_available: bool
    dbn: bool
    float16: bool
    analysis_sample_rate: int
    source_sample_rate: int
    model_load_seconds: float
    inference_seconds: float


class BeatThisBackend:
    """Optional adapter around the `beat-this` Python package."""

    name = BEAT_THIS_BACKEND

    def __init__(
        self,
        *,
        checkpoint_path: str = DEFAULT_BEAT_THIS_CHECKPOINT,
        device: str = DEFAULT_BEAT_THIS_DEVICE,
        dbn: bool = DEFAULT_BEAT_THIS_DBN,
        float16: bool = DEFAULT_BEAT_THIS_FLOAT16,
        dependency_loader: Callable[..., Any] = require_optional_dependency,
        version_resolver: Callable[[str], str] = metadata.version,
        backend_version: str = __version__,
    ) -> None:
        if not checkpoint_path:
            raise ValueError("checkpoint_path must not be empty")
        if not device:
            raise ValueError("device must not be empty")
        self.checkpoint_path = checkpoint_path
        self.device = device
        self.dbn = bool(dbn)
        self.float16 = bool(float16)
        self._dependency_loader = dependency_loader
        self._version_resolver = version_resolver
        self._backend_version = backend_version
        self._predictor: Any | None = None
        self._effective_device: str | None = None
        self._cuda_available = False
        self._model_load_seconds = 0.0

    def analyze_beat_grid(
        self,
        audio: DecodedAudio,
        tempo: TempoCandidateResult,
        context: AnalysisContext,
    ) -> BeatGridCandidateResult:
        del context
        start = time.perf_counter()
        try:
            prediction = self.predict(audio)
            result = self.beat_grid_result_from_prediction(
                prediction,
                tempo_status=tempo.status,
                processing_seconds=_elapsed(start),
            )
        except OptionalDependencyUnavailable as exc:
            return BeatGridCandidateResult(
                status="unavailable",
                provenance=self._provenance(
                    parameters={"tempoStatus": tempo.status},
                    processing_seconds=_elapsed(start),
                ),
                error=BackendExecutionError.from_optional_dependency(self.name, exc),
            )
        except Exception as exc:
            return BeatGridCandidateResult(
                status="failed",
                provenance=self._provenance(
                    parameters={"tempoStatus": tempo.status},
                    processing_seconds=_elapsed(start),
                ),
                error=_backend_error(exc, backend_name=self.name),
            )
        return result

    def predict(self, audio: DecodedAudio) -> BeatThisPrediction:
        numpy = self._dependency_loader(
            "numpy",
            module_name="numpy",
            install_extra="analysis",
        )
        samples = numpy.asarray(audio.samples, dtype=numpy.float32).reshape(-1)
        if int(samples.size) == 0:
            raise ValueError("Decoded audio contains no samples")

        predictor = self._load_predictor()
        inference_start = time.perf_counter()
        beats, downbeats = predictor(samples, int(audio.sample_rate))
        inference_seconds = _elapsed(inference_start)
        return BeatThisPrediction(
            beats=_valid_times(_float_sequence(beats)),
            downbeats=_valid_times(_float_sequence(downbeats)),
            checkpoint_path=self.checkpoint_path,
            requested_device=self.device,
            effective_device=self._effective_device or "unknown",
            cuda_available=self._cuda_available,
            dbn=self.dbn,
            float16=self.float16,
            analysis_sample_rate=BEAT_THIS_ANALYSIS_SAMPLE_RATE,
            source_sample_rate=int(audio.sample_rate),
            model_load_seconds=self._model_load_seconds,
            inference_seconds=inference_seconds,
        )

    def beat_grid_result_from_prediction(
        self,
        prediction: BeatThisPrediction,
        *,
        tempo_status: str = "ok",
        processing_seconds: float = 0.0,
    ) -> BeatGridCandidateResult:
        confidence = _sequence_confidence(prediction.beats)
        beats = tuple(
            BeatMarker(index=index, time_seconds=time_seconds, confidence=confidence)
            for index, time_seconds in enumerate(prediction.beats)
        )
        downbeats = tuple(
            BeatMarker(index=index, time_seconds=time_seconds, beat_in_bar=1, confidence=confidence)
            for index, time_seconds in enumerate(prediction.downbeats)
        )
        return BeatGridCandidateResult(
            status="ok",
            provenance=self._provenance(
                parameters=_parameters(prediction) | {"tempoStatus": tempo_status},
                processing_seconds=processing_seconds,
                warnings=_warnings(prediction),
            ),
            beats=beats,
            downbeats=downbeats,
            confidence=confidence if beats else 0.0,
            offset_seconds=beats[0].time_seconds if beats else None,
        )

    def _load_predictor(self) -> Any:
        if self._predictor is not None:
            return self._predictor

        beat_this_inference = self._dependency_loader(
            "beat-this",
            module_name="beat_this.inference",
            install_extra="beat-this",
        )
        torch = self._dependency_loader(
            "torch",
            module_name="torch",
            install_extra="beat-this",
        )
        device, cuda_available = _resolve_device(self.device, torch)
        model_start = time.perf_counter()
        self._predictor = beat_this_inference.Audio2Beats(
            checkpoint_path=self.checkpoint_path,
            device=device,
            float16=self.float16,
            dbn=self.dbn,
        )
        self._model_load_seconds = _elapsed(model_start)
        self._effective_device = device
        self._cuda_available = cuda_available
        return self._predictor

    def _provenance(
        self,
        *,
        parameters: dict[str, Any] | None = None,
        processing_seconds: float = 0.0,
        warnings: tuple[str, ...] = (),
    ) -> CandidateProvenance:
        return CandidateProvenance(
            backend_name=self.name,
            backend_version=self._backend_version,
            model_name=BEAT_THIS_MODEL_NAME,
            model_version=self.checkpoint_path,
            dependency_versions=_dependency_versions(self._version_resolver),
            parameters={
                "checkpointPath": self.checkpoint_path,
                "requestedDevice": self.device,
                "dbn": self.dbn,
                "float16": self.float16,
                "licenseNote": BEAT_THIS_LICENSE_NOTE,
            }
            | (parameters or {}),
            processing_seconds=processing_seconds,
            warnings=warnings,
        )


def register_beat_this_backends(registry: BackendRegistry) -> None:
    """Register Beat This as a beat-grid candidate."""

    registry.register_beat_grid(BEAT_THIS_BACKEND, BeatThisBackend)


def _parameters(prediction: BeatThisPrediction) -> dict[str, Any]:
    return {
        "checkpointPath": prediction.checkpoint_path,
        "requestedDevice": prediction.requested_device,
        "effectiveDevice": prediction.effective_device,
        "cudaAvailable": prediction.cuda_available,
        "dbn": prediction.dbn,
        "float16": prediction.float16,
        "analysisSampleRate": prediction.analysis_sample_rate,
        "sourceSampleRate": prediction.source_sample_rate,
        "modelLoadSeconds": prediction.model_load_seconds,
        "inferenceSeconds": prediction.inference_seconds,
        "beatCount": len(prediction.beats),
        "downbeatCount": len(prediction.downbeats),
    }


def _warnings(prediction: BeatThisPrediction) -> tuple[str, ...]:
    warnings = [BEAT_THIS_LICENSE_NOTE]
    if prediction.requested_device == "auto":
        warnings.append(f"Beat This auto-selected device: {prediction.effective_device}.")
    if not prediction.cuda_available:
        warnings.append("Beat This ran without CUDA; benchmark reports should include CPU runtime.")
    if prediction.dbn:
        warnings.append("Beat This DBN postprocessing was enabled; this adds madmom dependency risk.")
    if not prediction.downbeats:
        warnings.append("Beat This emitted no downbeats for this track.")
    if prediction.source_sample_rate != prediction.analysis_sample_rate:
        warnings.append(
            f"Beat This Audio2Beats internally uses {prediction.analysis_sample_rate} Hz; "
            f"input sample rate was {prediction.source_sample_rate} Hz."
        )
    return tuple(warnings)


def _resolve_device(requested_device: str, torch: Any) -> tuple[str, bool]:
    cuda_available = bool(torch.cuda.is_available()) if hasattr(torch, "cuda") else False
    if requested_device == "auto":
        return ("cuda" if cuda_available else "cpu"), cuda_available
    return requested_device, cuda_available


def _sequence_confidence(beats: tuple[float, ...]) -> float:
    if len(beats) < 4:
        return 0.2 if beats else 0.0
    intervals = [later - earlier for earlier, later in zip(beats, beats[1:]) if later > earlier]
    if len(intervals) < 3:
        return 0.2
    median_interval = _median(intervals)
    if median_interval <= 0:
        return 0.2
    median_error = _median([abs(interval - median_interval) for interval in intervals])
    regularity = 1.0 - min(median_error / (median_interval * 0.25), 1.0)
    count_score = min(len(beats) / 16.0, 1.0)
    return _round_float(_clamp(0.25 + 0.55 * regularity + 0.20 * count_score, ceiling=0.92))


def _valid_times(values: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(_round_float(value) for value in sorted(value for value in values if value >= 0))


def _float_sequence(values: Any) -> tuple[float, ...]:
    try:
        return tuple(float(value) for value in values)
    except TypeError:
        return ()


def _backend_error(exc: Exception, *, backend_name: str) -> BackendExecutionError:
    return BackendExecutionError(
        code="beat_this_failed",
        message=str(exc) or exc.__class__.__name__,
        backend_name=backend_name,
        details={"exceptionType": exc.__class__.__name__},
    )


def _dependency_versions(version_resolver: Callable[[str], str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in ("beat-this", "torch", "torchaudio", "soxr"):
        version = _dependency_version(package_name, version_resolver)
        if version is not None:
            versions[package_name] = version
    return versions


def _dependency_version(package_name: str, version_resolver: Callable[[str], str]) -> str | None:
    try:
        return version_resolver(package_name)
    except metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _clamp(value: float, *, ceiling: float = 1.0) -> float:
    return min(ceiling, max(0.0, value))


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded


def _elapsed(start: float) -> float:
    return round(max(0.0, time.perf_counter() - start), 6)
