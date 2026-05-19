"""SongFormer backend adapter for semantic section candidates."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
import os
import sys
import time
from typing import Any

from .. import __version__
from ..audio_io import DecodedAudio
from ..dependencies import OptionalDependencyUnavailable, require_optional_dependency
from ..section_labels import map_section_label
from .base import (
    AnalysisContext,
    BackendExecutionError,
    BeatGridCandidateResult,
    CandidateProvenance,
    FeatureBundle,
    SectionCandidate,
    SectionCandidateResult,
)
from .registry import BackendRegistry


SONGFORMER_BACKEND = "songformer"
SONGFORMER_MODEL_NAME = "SongFormer"
SONGFORMER_MODEL_REPO = "ASLP-lab/SongFormer"
SONGFORMER_EXPECTED_SAMPLE_RATE = 24_000
DEFAULT_SONGFORMER_DEVICE = "auto"
DEFAULT_SONGFORMER_IGNORE_PATTERNS = ("SongFormer.pt", "SongFormer.safetensors")
SONGFORMER_LICENSE_NOTE = (
    "SongFormer repository and Hugging Face model card indicate CC-BY-4.0 terms; "
    "review model, dataset, MuQ, MusicFM, and dependency terms before product distribution."
)
SONGFORMER_INSTALL_NOTE = (
    "SongFormer has no PyPI package; upstream installation uses a GitHub checkout, "
    "submodules, Python 3.10, requirements.txt, and Hugging Face model files."
)

_DEPENDENCY_PACKAGES = (
    "transformers",
    "huggingface-hub",
    "torch",
    "torchaudio",
    "safetensors",
    "librosa",
    "muq",
    "ema-pytorch",
    "x-transformers",
    "omegaconf",
    "msaf",
)
_RUNTIME_MODULES = (
    ("transformers", "transformers"),
    ("huggingface-hub", "huggingface_hub"),
    ("torch", "torch"),
    ("safetensors", "safetensors"),
    ("librosa", "librosa"),
    ("muq", "muq"),
    ("ema-pytorch", "ema_pytorch"),
    ("x-transformers", "x_transformers"),
    ("omegaconf", "omegaconf"),
    ("msaf", "msaf"),
)
@dataclass(frozen=True)
class SongFormerSegment:
    start_seconds: float
    end_seconds: float
    label: str
    confidence: float | None = None
    provider_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_metadata", dict(self.provider_metadata))


@dataclass(frozen=True)
class SongFormerPrediction:
    segments: tuple[SongFormerSegment, ...]
    requested_audio_path: Path
    result_path: Path | None
    timeline_mode: str
    repo_id: str
    local_dir: Path | None
    revision: str | None
    requested_device: str
    effective_device: str
    cuda_available: bool
    trust_remote_code: bool
    expected_sample_rate: int
    processing_seconds: float


SongFormerRunner = Callable[[Path, Mapping[str, Any]], Any]


class SongFormerBackend:
    """Optional adapter around the SongFormer Hugging Face custom-code model."""

    name = SONGFORMER_BACKEND

    def __init__(
        self,
        *,
        repo_id: str = SONGFORMER_MODEL_REPO,
        revision: str | None = None,
        local_dir: str | Path | None = None,
        device: str = DEFAULT_SONGFORMER_DEVICE,
        prefer_analysis_audio: bool = True,
        trust_remote_code: bool = True,
        low_cpu_mem_usage: bool = False,
        ignore_patterns: Sequence[str] = DEFAULT_SONGFORMER_IGNORE_PATTERNS,
        prediction_runner: SongFormerRunner | None = None,
        dependency_loader: Callable[..., Any] = require_optional_dependency,
        version_resolver: Callable[[str], str] = metadata.version,
        module_available: Callable[[str], bool] | None = None,
        backend_version: str = __version__,
    ) -> None:
        if not repo_id:
            raise ValueError("repo_id must not be empty")
        if not device:
            raise ValueError("device must not be empty")
        self.repo_id = repo_id
        self.revision = revision
        self.local_dir = Path(local_dir) if local_dir is not None else None
        self.device = device
        self.prefer_analysis_audio = bool(prefer_analysis_audio)
        self.trust_remote_code = bool(trust_remote_code)
        self.low_cpu_mem_usage = bool(low_cpu_mem_usage)
        self.ignore_patterns = tuple(ignore_patterns)
        self._prediction_runner = prediction_runner
        self._dependency_loader = dependency_loader
        self._version_resolver = version_resolver
        self._module_available = module_available or _module_available
        self._backend_version = backend_version
        self._model: Any | None = None
        self._resolved_local_dir: Path | None = self.local_dir
        self._effective_device: str | None = None
        self._cuda_available = False
        self._model_load_seconds = 0.0
        self._cache: dict[tuple[str, str, str, str | None], SongFormerPrediction] = {}

    def analyze_sections(
        self,
        audio: DecodedAudio,
        features: FeatureBundle,
        beat_grid: BeatGridCandidateResult,
        context: AnalysisContext,
    ) -> SectionCandidateResult:
        del audio, features
        start = time.perf_counter()
        try:
            prediction = self.predict(context)
            return self.section_result_from_prediction(
                prediction,
                beat_grid=beat_grid,
                processing_seconds=_elapsed(start),
            )
        except OptionalDependencyUnavailable as exc:
            return SectionCandidateResult(
                status="unavailable",
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=BackendExecutionError.from_optional_dependency(self.name, exc),
            )
        except Exception as exc:
            return SectionCandidateResult(
                status="failed",
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=_backend_error(exc, backend_name=self.name),
            )

    def predict(self, context: AnalysisContext) -> SongFormerPrediction:
        audio_path, timeline_mode = self._select_audio_path(context)
        cache_key = (str(audio_path), timeline_mode, self.repo_id, self.revision)
        if cache_key in self._cache:
            return self._cache[cache_key]

        start = time.perf_counter()
        effective_device, cuda_available = self._resolve_device()
        options = {
            "repoId": self.repo_id,
            "revision": self.revision,
            "localDir": str(self.local_dir) if self.local_dir is not None else None,
            "device": effective_device,
            "trustRemoteCode": self.trust_remote_code,
            "lowCpuMemUsage": self.low_cpu_mem_usage,
            "ignorePatterns": list(self.ignore_patterns),
            "expectedSampleRate": SONGFORMER_EXPECTED_SAMPLE_RATE,
        }
        if self._prediction_runner is not None:
            raw_result = self._prediction_runner(audio_path, options)
            local_dir = self.local_dir
        else:
            model = self._load_model(effective_device=effective_device)
            torch = self._dependency_loader("torch", module_name="torch", install_extra="songformer")
            with torch.no_grad():
                raw_result = model(str(audio_path))
            local_dir = self._resolved_local_dir

        prediction = self.prediction_from_result(
            raw_result,
            requested_audio_path=audio_path,
            timeline_mode=timeline_mode,
            repo_id=self.repo_id,
            local_dir=local_dir,
            revision=self.revision,
            requested_device=self.device,
            effective_device=effective_device,
            cuda_available=cuda_available,
            trust_remote_code=self.trust_remote_code,
            processing_seconds=_elapsed(start),
        )
        self._cache[cache_key] = prediction
        return prediction

    def prediction_from_result(
        self,
        result: Any,
        *,
        requested_audio_path: Path,
        timeline_mode: str,
        repo_id: str,
        local_dir: Path | None,
        revision: str | None,
        requested_device: str,
        effective_device: str,
        cuda_available: bool,
        trust_remote_code: bool,
        processing_seconds: float = 0.0,
    ) -> SongFormerPrediction:
        return SongFormerPrediction(
            segments=_segments(result),
            requested_audio_path=Path(requested_audio_path),
            result_path=None,
            timeline_mode=timeline_mode,
            repo_id=repo_id,
            local_dir=Path(local_dir) if local_dir is not None else None,
            revision=revision,
            requested_device=requested_device,
            effective_device=effective_device,
            cuda_available=cuda_available,
            trust_remote_code=trust_remote_code,
            expected_sample_rate=SONGFORMER_EXPECTED_SAMPLE_RATE,
            processing_seconds=processing_seconds,
        )

    def section_result_from_prediction(
        self,
        prediction: SongFormerPrediction,
        *,
        beat_grid: BeatGridCandidateResult,
        processing_seconds: float = 0.0,
    ) -> SectionCandidateResult:
        sections = tuple(
            _section_candidate(segment, index=index, beat_grid=beat_grid)
            for index, segment in enumerate(prediction.segments)
        )
        return SectionCandidateResult(
            status="ok",
            provenance=self._provenance_from_prediction(
                prediction,
                parameters={"sectionCount": len(sections)},
                processing_seconds=processing_seconds,
                warnings=_warnings(prediction),
            ),
            sections=sections,
            cue_points=(),
        )

    def _load_model(self, *, effective_device: str) -> Any:
        if self._model is not None:
            return self._model

        _install_msaf_scipy_compat_shim()
        for dependency, module_name in _RUNTIME_MODULES:
            self._dependency_loader(dependency, module_name=module_name, install_extra="songformer")
        transformers = self._dependency_loader(
            "transformers",
            module_name="transformers",
            install_extra="songformer",
        )
        huggingface_hub = self._dependency_loader(
            "huggingface-hub",
            module_name="huggingface_hub",
            install_extra="songformer",
        )
        local_dir = self.local_dir
        if local_dir is None:
            snapshot_kwargs: dict[str, Any] = {
                "repo_id": self.repo_id,
                "repo_type": "model",
                "resume_download": True,
                "allow_patterns": "*",
                "ignore_patterns": list(self.ignore_patterns),
            }
            if self.revision is not None:
                snapshot_kwargs["revision"] = self.revision
            local_dir = Path(huggingface_hub.snapshot_download(**snapshot_kwargs))
        local_dir = Path(local_dir)
        _add_to_syspath(local_dir)
        os.environ["SONGFORMER_LOCAL_DIR"] = str(local_dir)

        start = time.perf_counter()
        model = transformers.AutoModel.from_pretrained(
            str(local_dir),
            trust_remote_code=self.trust_remote_code,
            low_cpu_mem_usage=self.low_cpu_mem_usage,
        )
        model.to(effective_device)
        model.eval()
        self._model = model
        self._resolved_local_dir = local_dir
        self._model_load_seconds = _elapsed(start)
        return model

    def _resolve_device(self) -> tuple[str, bool]:
        if self._prediction_runner is not None and self.device == "auto":
            return "cpu", False
        torch = self._dependency_loader("torch", module_name="torch", install_extra="songformer")
        cuda_available = bool(torch.cuda.is_available()) if hasattr(torch, "cuda") else False
        if self.device == "auto":
            return ("cuda" if cuda_available else "cpu"), cuda_available
        return self.device, cuda_available

    def _select_audio_path(self, context: AnalysisContext) -> tuple[Path, str]:
        analysis_path = Path(context.analysis_audio_path)
        source_path = Path(context.source_path)
        if self.prefer_analysis_audio and analysis_path != source_path:
            return analysis_path, "analysis_audio_path"
        return source_path, "source_path"

    def _provenance(
        self,
        *,
        parameters: Mapping[str, Any] | None = None,
        processing_seconds: float = 0.0,
        warnings: tuple[str, ...] = (),
    ) -> CandidateProvenance:
        return CandidateProvenance(
            backend_name=self.name,
            backend_version=self._backend_version,
            model_name=SONGFORMER_MODEL_NAME,
            model_version=self.revision or self.repo_id,
            dependency_versions=_dependency_versions(self._version_resolver),
            parameters={
                "repoId": self.repo_id,
                "revision": self.revision,
                "localDir": str(self.local_dir) if self.local_dir is not None else None,
                "requestedDevice": self.device,
                "preferAnalysisAudio": self.prefer_analysis_audio,
                "trustRemoteCode": self.trust_remote_code,
                "lowCpuMemUsage": self.low_cpu_mem_usage,
                "ignorePatterns": list(self.ignore_patterns),
                "expectedSampleRate": SONGFORMER_EXPECTED_SAMPLE_RATE,
                "dependencyAvailability": {
                    module: self._module_available(module_name)
                    for module, module_name in _RUNTIME_MODULES
                },
                "licenseNote": SONGFORMER_LICENSE_NOTE,
                "installNote": SONGFORMER_INSTALL_NOTE,
            }
            | dict(parameters or {}),
            processing_seconds=processing_seconds,
            warnings=warnings,
        )

    def _provenance_from_prediction(
        self,
        prediction: SongFormerPrediction,
        *,
        parameters: Mapping[str, Any] | None = None,
        processing_seconds: float = 0.0,
        warnings: tuple[str, ...] = (),
    ) -> CandidateProvenance:
        return self._provenance(
            parameters={
                "requestedAudioPath": str(prediction.requested_audio_path),
                "timelineMode": prediction.timeline_mode,
                "repoId": prediction.repo_id,
                "resolvedLocalDir": str(prediction.local_dir) if prediction.local_dir is not None else None,
                "revision": prediction.revision,
                "requestedDevice": prediction.requested_device,
                "effectiveDevice": prediction.effective_device,
                "cudaAvailable": prediction.cuda_available,
                "trustRemoteCode": prediction.trust_remote_code,
                "expectedSampleRate": prediction.expected_sample_rate,
                "modelLoadSeconds": self._model_load_seconds,
                "songFormerProcessingSeconds": prediction.processing_seconds,
                "segmentCount": len(prediction.segments),
            }
            | dict(parameters or {}),
            processing_seconds=processing_seconds,
            warnings=warnings,
        )


def register_songformer_backends(registry: BackendRegistry) -> None:
    """Register SongFormer as a semantic-section candidate backend."""

    registry.register_section(SONGFORMER_BACKEND, SongFormerBackend)


def _install_msaf_scipy_compat_shim() -> None:
    try:
        import numpy as np
        import scipy
    except ImportError:
        return
    if not hasattr(scipy, "inf"):
        scipy.inf = np.inf  # type: ignore[attr-defined]


def _segments(values: Any) -> tuple[SongFormerSegment, ...]:
    if values is None:
        return ()
    if isinstance(values, Mapping):
        for key in ("segments", "sections", "prediction", "predictions"):
            if key in values:
                return _segments(values[key])
    if hasattr(values, "segments"):
        return _segments(getattr(values, "segments"))
    if hasattr(values, "sections"):
        return _segments(getattr(values, "sections"))

    boundary_segments = _boundary_segments(values)
    if boundary_segments:
        return boundary_segments

    segments: list[SongFormerSegment] = []
    for index, value in enumerate(values):
        parsed = _parse_segment(value)
        if parsed is None:
            continue
        start, end, label, confidence = parsed
        if end < start:
            continue
        segments.append(
            SongFormerSegment(
                start_seconds=_round_float(start),
                end_seconds=_round_float(end),
                label=label,
                confidence=confidence,
                provider_metadata={"sourceIndex": index},
            )
        )
    return tuple(segments)


def _boundary_segments(values: Any) -> tuple[SongFormerSegment, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        return ()
    boundaries: list[tuple[float, str, float | None]] = []
    for value in values:
        parsed = _parse_boundary(value)
        if parsed is None:
            return ()
        boundaries.append(parsed)
    if len(boundaries) < 2:
        return ()

    segments: list[SongFormerSegment] = []
    for index, ((start, label, confidence), (end, _next_label, _next_confidence)) in enumerate(
        zip(boundaries, boundaries[1:])
    ):
        if end < start or label.strip().lower() == "end":
            continue
        segments.append(
            SongFormerSegment(
                start_seconds=_round_float(start),
                end_seconds=_round_float(end),
                label=label,
                confidence=confidence,
                provider_metadata={"sourceIndex": index, "sourceShape": "boundary_pair"},
            )
        )
    return tuple(segments)


def _parse_boundary(value: Any) -> tuple[float, str, float | None] | None:
    if isinstance(value, Mapping):
        if "end" in value:
            return None
        start = _optional_float(value.get("start"))
        label = value.get("label")
        confidence = _optional_float(value.get("confidence"))
    elif hasattr(value, "start") and hasattr(value, "label"):
        start = _optional_float(getattr(value, "start"))
        label = getattr(value, "label")
        confidence = _optional_float(getattr(value, "confidence", None))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 2:
        start = _optional_float(value[0])
        label = value[1]
        confidence = _optional_float(value[2]) if len(value) >= 3 else None
    else:
        return None
    if start is None or label is None:
        return None
    return (start, str(label), confidence)


def _parse_segment(value: Any) -> tuple[float, float, str, float | None] | None:
    if isinstance(value, Mapping):
        start = _optional_float(value.get("start"))
        end = _optional_float(value.get("end"))
        label = value.get("label")
        confidence = _optional_float(value.get("confidence"))
    elif hasattr(value, "start") and hasattr(value, "end") and hasattr(value, "label"):
        start = _optional_float(getattr(value, "start"))
        end = _optional_float(getattr(value, "end"))
        label = getattr(value, "label")
        confidence = _optional_float(getattr(value, "confidence", None))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 3:
        start = _optional_float(value[0])
        end = _optional_float(value[1])
        label = value[2]
        confidence = _optional_float(value[3]) if len(value) >= 4 else None
    else:
        return None
    if start is None or end is None or label is None:
        return None
    return (start, end, str(label), confidence)


def _section_candidate(
    segment: SongFormerSegment,
    *,
    index: int,
    beat_grid: BeatGridCandidateResult,
) -> SectionCandidate:
    section_type, confidence, notes = _map_section_label(segment.label, segment.confidence)
    return SectionCandidate(
        id=f"section-{section_type}-{index + 1:03d}",
        type=section_type,  # type: ignore[arg-type]
        start_seconds=segment.start_seconds,
        end_seconds=segment.end_seconds,
        confidence=confidence,
        source_label=segment.label,
        start_beat_index=_nearest_beat_index(segment.start_seconds, beat_grid),
        end_beat_index=_nearest_beat_index(segment.end_seconds, beat_grid),
        mapping_notes=notes,
        provider_metadata={
            "sourceBackend": SONGFORMER_BACKEND,
            "providerMetadata": dict(segment.provider_metadata),
        },
    )


def _map_section_label(label: str, confidence: float | None = None) -> tuple[str, float, tuple[str, ...]]:
    mapping = map_section_label(
        label,
        confidence=confidence if confidence is not None else 0.62,
        provider_name="songformer",
    )
    return (mapping.label, mapping.confidence, mapping.notes)


def _warnings(prediction: SongFormerPrediction) -> tuple[str, ...]:
    warnings = [
        SONGFORMER_LICENSE_NOTE,
        SONGFORMER_INSTALL_NOTE,
        "SongFormer is a semantic-section model only; it does not emit BPM, beatgrid, or cue points.",
    ]
    if prediction.timeline_mode == "analysis_audio_path":
        warnings.append("SongFormer was run against AnalysisContext.analysis_audio_path for timeline consistency.")
    else:
        warnings.append("SongFormer was run against the source path; benchmark reports should verify decoder timeline alignment.")
    if prediction.requested_device == "auto":
        warnings.append(f"SongFormer auto-selected device: {prediction.effective_device}.")
    if not prediction.cuda_available:
        warnings.append("SongFormer ran without CUDA; a 0.7B F32 model may be slow on CPU.")
    if prediction.trust_remote_code:
        warnings.append("SongFormer requires Hugging Face trust_remote_code=True for the official model.")
    return tuple(warnings)


def _nearest_beat_index(time_seconds: float, beat_grid: BeatGridCandidateResult, *, tolerance: float = 0.08) -> int | None:
    if not beat_grid.beats:
        return None
    nearest = min(beat_grid.beats, key=lambda beat: abs(beat.time_seconds - time_seconds))
    if abs(nearest.time_seconds - time_seconds) <= tolerance:
        return nearest.index
    return None


def _backend_error(exc: Exception, *, backend_name: str) -> BackendExecutionError:
    return BackendExecutionError(
        code="songformer_failed",
        message=str(exc) or exc.__class__.__name__,
        backend_name=backend_name,
        details={"exceptionType": exc.__class__.__name__},
    )


def _dependency_versions(version_resolver: Callable[[str], str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in _DEPENDENCY_PACKAGES:
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


def _add_to_syspath(path: Path) -> None:
    path_string = str(path)
    if path_string not in sys.path:
        sys.path.append(path_string)


def _module_available(module_name: str) -> bool:
    try:
        from importlib.util import find_spec

        return find_spec(module_name) is not None
    except Exception:
        return False


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded


def _elapsed(start: float) -> float:
    return round(max(0.0, time.perf_counter() - start), 6)
