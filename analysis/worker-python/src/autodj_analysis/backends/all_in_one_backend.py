"""All-In-One backend adapter for timing and functional section candidates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
import platform
import shutil
import time
from typing import Any

from .. import __version__
from ..audio_io import DecodedAudio
from ..dependencies import OptionalDependencyUnavailable, require_optional_dependency
from ..section_labels import map_section_label
from ..tempo import normalize_dubstep_bpm
from .base import (
    AnalysisContext,
    BackendExecutionError,
    BeatGridCandidateResult,
    BeatMarker,
    CandidateProvenance,
    FeatureBundle,
    SectionCandidate,
    SectionCandidateResult,
    TempoCandidate,
    TempoCandidateResult,
)
from .registry import BackendRegistry


ALL_IN_ONE_BACKEND = "all-in-one"
ALL_IN_ONE_UNLOCKED_BACKEND = "all-in-one-unlocked"
ALL_IN_ONE_MODEL_NAME = "All-In-One"
DEFAULT_ALL_IN_ONE_MODEL = "harmonix-all"
DEFAULT_ALL_IN_ONE_DEVICE = "auto"
ALL_IN_ONE_LICENSE_NOTE = (
    "All-In-One package code is MIT licensed; checkpoint/model and training-data "
    "terms must be reviewed before product distribution."
)
ALL_IN_ONE_MP3_TIMELINE_WARNING = (
    "All-In-One upstream warns MP3 decoder differences can shift timing by about "
    "20-40 ms; prefer normalized WAV analysis input for Rekordbox comparisons."
)

_DEPENDENCY_PACKAGES = ("allin1", "torch", "demucs", "madmom", "natten")
@dataclass(frozen=True)
class AllInOneSegment:
    start_seconds: float
    end_seconds: float
    label: str
    confidence: float | None = None
    provider_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_metadata", dict(self.provider_metadata))


@dataclass(frozen=True)
class AllInOneAnalysis:
    bpm: float | None
    beats: tuple[float, ...]
    downbeats: tuple[float, ...]
    beat_positions: tuple[int, ...]
    segments: tuple[AllInOneSegment, ...]
    requested_audio_path: Path
    result_path: Path | None
    timeline_mode: str
    requested_device: str
    effective_device: str
    cuda_available: bool
    model_name: str
    include_activations: bool
    include_embeddings: bool
    keep_byproducts: bool
    demix_dir: str
    spec_dir: str
    ffmpeg_available: bool
    ffmpeg_path: str | None
    processing_seconds: float
    activation_summary: Mapping[str, Any] = field(default_factory=dict)


AllInOneRunner = Callable[[Path, Mapping[str, Any]], Any]


class AllInOneBackend:
    """Optional adapter around the `allin1` Python package."""

    name = ALL_IN_ONE_BACKEND

    def __init__(
        self,
        *,
        model: str = DEFAULT_ALL_IN_ONE_MODEL,
        device: str = DEFAULT_ALL_IN_ONE_DEVICE,
        prefer_analysis_audio: bool = True,
        include_activations: bool = False,
        include_embeddings: bool = False,
        keep_byproducts: bool = False,
        multiprocess: bool = True,
        out_dir: str | Path | None = None,
        demix_dir: str | Path | None = None,
        spec_dir: str | Path | None = None,
        analysis_runner: AllInOneRunner | None = None,
        dependency_loader: Callable[..., Any] = require_optional_dependency,
        version_resolver: Callable[[str], str] = metadata.version,
        module_available: Callable[[str], bool] | None = None,
        ffmpeg_resolver: Callable[[str], str | None] = shutil.which,
        platform_resolver: Callable[[], str] = platform.system,
        backend_version: str = __version__,
    ) -> None:
        if not model:
            raise ValueError("model must not be empty")
        if not device:
            raise ValueError("device must not be empty")
        self.model = model
        self.device = device
        self.prefer_analysis_audio = bool(prefer_analysis_audio)
        self.include_activations = bool(include_activations)
        self.include_embeddings = bool(include_embeddings)
        self.keep_byproducts = bool(keep_byproducts)
        self.multiprocess = bool(multiprocess)
        self.out_dir = Path(out_dir) if out_dir is not None else None
        self.demix_dir = Path(demix_dir) if demix_dir is not None else None
        self.spec_dir = Path(spec_dir) if spec_dir is not None else None
        self._analysis_runner = analysis_runner
        self._dependency_loader = dependency_loader
        self._version_resolver = version_resolver
        self._module_available = module_available or _module_available
        self._ffmpeg_resolver = ffmpeg_resolver
        self._platform_resolver = platform_resolver
        self._backend_version = backend_version
        self._cache: dict[tuple[str, str, str, bool, bool], AllInOneAnalysis] = {}

    def analyze_tempo(self, audio: DecodedAudio, context: AnalysisContext) -> TempoCandidateResult:
        del audio
        start = time.perf_counter()
        try:
            analysis = self.analyze_file(context)
            return self.tempo_result_from_analysis(analysis, processing_seconds=_elapsed(start))
        except OptionalDependencyUnavailable as exc:
            return TempoCandidateResult(
                status="unavailable",
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=BackendExecutionError.from_optional_dependency(self.name, exc),
            )
        except Exception as exc:
            return TempoCandidateResult(
                status="failed",
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=_backend_error(exc, backend_name=self.name),
            )

    def analyze_beat_grid(
        self,
        audio: DecodedAudio,
        tempo: TempoCandidateResult,
        context: AnalysisContext,
    ) -> BeatGridCandidateResult:
        del audio
        start = time.perf_counter()
        try:
            analysis = self.analyze_file(context)
            return self.beat_grid_result_from_analysis(
                analysis,
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
            analysis = self.analyze_file(context)
            return self.section_result_from_analysis(
                analysis,
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

    def analyze_file(self, context: AnalysisContext) -> AllInOneAnalysis:
        audio_path, timeline_mode = self._select_audio_path(context)
        cache_key = (
            str(audio_path),
            timeline_mode,
            self.model,
            self.include_activations,
            self.include_embeddings,
        )
        if cache_key in self._cache:
            return self._cache[cache_key]

        ffmpeg_path = self._ffmpeg_resolver("ffmpeg")
        effective_device, cuda_available = self._resolve_device()
        demix_dir = self._directory_parameter(
            configured=self.demix_dir,
            context=context,
            directory_name="all-in-one-demix",
            fallback="./demix",
        )
        spec_dir = self._directory_parameter(
            configured=self.spec_dir,
            context=context,
            directory_name="all-in-one-spec",
            fallback="./spec",
        )
        options: dict[str, Any] = {
            "out_dir": str(self.out_dir) if self.out_dir is not None else None,
            "visualize": False,
            "sonify": False,
            "model": self.model,
            "device": effective_device,
            "include_activations": self.include_activations,
            "include_embeddings": self.include_embeddings,
            "demix_dir": demix_dir,
            "spec_dir": spec_dir,
            "keep_byproducts": self.keep_byproducts,
            "overwrite": True,
            "multiprocess": self.multiprocess,
        }

        start = time.perf_counter()
        if self._analysis_runner is not None:
            raw_result = self._analysis_runner(audio_path, options)
        else:
            allin1 = self._load_allin1_module()
            raw_result = allin1.analyze(str(audio_path), **options)

        analysis = self.analysis_from_result(
            _first_result(raw_result),
            requested_audio_path=audio_path,
            timeline_mode=timeline_mode,
            requested_device=self.device,
            effective_device=effective_device,
            cuda_available=cuda_available,
            model_name=self.model,
            include_activations=self.include_activations,
            include_embeddings=self.include_embeddings,
            keep_byproducts=self.keep_byproducts,
            demix_dir=demix_dir,
            spec_dir=spec_dir,
            ffmpeg_available=ffmpeg_path is not None,
            ffmpeg_path=ffmpeg_path,
            processing_seconds=_elapsed(start),
        )
        self._cache[cache_key] = analysis
        return analysis

    def analysis_from_result(
        self,
        result: Any,
        *,
        requested_audio_path: Path,
        timeline_mode: str,
        requested_device: str,
        effective_device: str,
        cuda_available: bool,
        model_name: str,
        include_activations: bool,
        include_embeddings: bool,
        keep_byproducts: bool,
        demix_dir: str,
        spec_dir: str,
        ffmpeg_available: bool,
        ffmpeg_path: str | None,
        processing_seconds: float = 0.0,
    ) -> AllInOneAnalysis:
        bpm = _optional_float(_read_value(result, "bpm"))
        result_path = _optional_path(_read_value(result, "path"))
        return AllInOneAnalysis(
            bpm=bpm,
            beats=_valid_times(_float_sequence(_read_value(result, "beats"))),
            downbeats=_valid_times(_float_sequence(_read_value(result, "downbeats"))),
            beat_positions=_int_sequence(_read_value(result, "beat_positions")),
            segments=_segments(_read_value(result, "segments")),
            requested_audio_path=Path(requested_audio_path),
            result_path=result_path,
            timeline_mode=timeline_mode,
            requested_device=requested_device,
            effective_device=effective_device,
            cuda_available=cuda_available,
            model_name=model_name,
            include_activations=include_activations,
            include_embeddings=include_embeddings,
            keep_byproducts=keep_byproducts,
            demix_dir=demix_dir,
            spec_dir=spec_dir,
            ffmpeg_available=ffmpeg_available,
            ffmpeg_path=ffmpeg_path,
            processing_seconds=processing_seconds,
            activation_summary=_activation_summary(_read_value(result, "activations")),
        )

    def tempo_result_from_analysis(
        self,
        analysis: AllInOneAnalysis,
        *,
        processing_seconds: float = 0.0,
    ) -> TempoCandidateResult:
        if analysis.bpm is None:
            return TempoCandidateResult(
                status="failed",
                provenance=self._provenance_from_analysis(
                    analysis,
                    processing_seconds=processing_seconds,
                ),
                error=BackendExecutionError(
                    code="all_in_one_missing_bpm",
                    message="All-In-One result did not include a BPM value.",
                    backend_name=self.name,
                ),
            )

        normalized = normalize_dubstep_bpm(analysis.bpm)
        warnings = _warnings(analysis, extra=() if normalized.warning is None else (normalized.warning,))
        confidence = 0.72
        return TempoCandidateResult(
            status="ok",
            provenance=self._provenance_from_analysis(
                analysis,
                processing_seconds=processing_seconds,
                warnings=warnings,
            ),
            bpm=normalized.bpm,
            normalized_bpm=normalized.normalized_bpm,
            confidence=confidence,
            tempo_class=normalized.tempo_class,
            candidates=(
                TempoCandidate(
                    bpm=float(analysis.bpm),
                    confidence=confidence,
                    backend="allin1.analyze",
                ),
            ),
        )

    def beat_grid_result_from_analysis(
        self,
        analysis: AllInOneAnalysis,
        *,
        tempo_status: str = "ok",
        processing_seconds: float = 0.0,
    ) -> BeatGridCandidateResult:
        confidence = _sequence_confidence(analysis.beats)
        if not analysis.beats:
            return BeatGridCandidateResult(
                status="failed",
                provenance=self._provenance_from_analysis(
                    analysis,
                    parameters={"tempoStatus": tempo_status},
                    processing_seconds=processing_seconds,
                    warnings=_warnings(analysis),
                ),
                error=BackendExecutionError(
                    code="all_in_one_missing_beats",
                    message="All-In-One result did not include beat markers.",
                    backend_name=self.name,
                ),
            )
        beats = tuple(
            BeatMarker(
                index=index,
                time_seconds=time_seconds,
                beat_in_bar=_beat_position(analysis.beat_positions, index),
                confidence=confidence,
            )
            for index, time_seconds in enumerate(analysis.beats)
        )
        downbeats = tuple(
            BeatMarker(
                index=index,
                time_seconds=time_seconds,
                beat_in_bar=1,
                confidence=confidence,
            )
            for index, time_seconds in enumerate(analysis.downbeats)
        )
        return BeatGridCandidateResult(
            status="ok",
            provenance=self._provenance_from_analysis(
                analysis,
                parameters={"tempoStatus": tempo_status},
                processing_seconds=processing_seconds,
                warnings=_warnings(analysis),
            ),
            beats=beats,
            downbeats=downbeats,
            confidence=confidence if beats else 0.0,
            offset_seconds=beats[0].time_seconds if beats else None,
        )

    def section_result_from_analysis(
        self,
        analysis: AllInOneAnalysis,
        *,
        beat_grid: BeatGridCandidateResult,
        processing_seconds: float = 0.0,
    ) -> SectionCandidateResult:
        sections = tuple(
            _section_candidate(
                segment,
                index=index,
                beat_grid=beat_grid,
            )
            for index, segment in enumerate(analysis.segments)
        )
        return SectionCandidateResult(
            status="ok",
            provenance=self._provenance_from_analysis(
                analysis,
                parameters={"sectionCount": len(sections)},
                processing_seconds=processing_seconds,
                warnings=_warnings(analysis),
            ),
            sections=sections,
            cue_points=(),
        )

    def _load_allin1_module(self) -> Any:
        self._dependency_loader("torch", module_name="torch", install_extra="all-in-one")
        _install_natten_legacy_api_shim()
        allin1 = self._dependency_loader("all-in-one", module_name="allin1", install_extra="all-in-one")
        self._dependency_loader("demucs", module_name="demucs", install_extra="all-in-one")
        self._dependency_loader("madmom", module_name="madmom", install_extra="all-in-one")
        if self._platform_resolver() in {"Linux", "Windows"}:
            self._dependency_loader("natten", module_name="natten", install_extra="all-in-one")
        return allin1

    def _resolve_device(self) -> tuple[str, bool]:
        if self._analysis_runner is not None and self.device == "auto":
            return "cpu", False
        torch = self._dependency_loader("torch", module_name="torch", install_extra="all-in-one")
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

    def _directory_parameter(
        self,
        *,
        configured: Path | None,
        context: AnalysisContext,
        directory_name: str,
        fallback: str,
    ) -> str:
        if configured is not None:
            return str(configured)
        if context.temp_dir is not None:
            return str(Path(context.temp_dir) / directory_name)
        return fallback

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
            model_name=ALL_IN_ONE_MODEL_NAME,
            model_version=self.model,
            dependency_versions=_dependency_versions(self._version_resolver),
            parameters={
                "model": self.model,
                "requestedDevice": self.device,
                "preferAnalysisAudio": self.prefer_analysis_audio,
                "includeActivations": self.include_activations,
                "includeEmbeddings": self.include_embeddings,
                "keepByproducts": self.keep_byproducts,
                "multiprocess": self.multiprocess,
                "ffmpegAvailable": self._ffmpeg_resolver("ffmpeg") is not None,
                "dependencyAvailability": {
                    package: self._module_available(package) for package in _DEPENDENCY_PACKAGES
                },
                "licenseNote": ALL_IN_ONE_LICENSE_NOTE,
                "mp3TimelineWarning": ALL_IN_ONE_MP3_TIMELINE_WARNING,
            }
            | dict(parameters or {}),
            processing_seconds=processing_seconds,
            warnings=warnings,
        )

    def _provenance_from_analysis(
        self,
        analysis: AllInOneAnalysis,
        *,
        parameters: Mapping[str, Any] | None = None,
        processing_seconds: float = 0.0,
        warnings: tuple[str, ...] = (),
    ) -> CandidateProvenance:
        return self._provenance(
            parameters={
                "requestedAudioPath": str(analysis.requested_audio_path),
                "resultPath": str(analysis.result_path) if analysis.result_path is not None else None,
                "timelineMode": analysis.timeline_mode,
                "requestedDevice": analysis.requested_device,
                "effectiveDevice": analysis.effective_device,
                "cudaAvailable": analysis.cuda_available,
                "ffmpegAvailable": analysis.ffmpeg_available,
                "ffmpegPath": analysis.ffmpeg_path,
                "demixDir": analysis.demix_dir,
                "specDir": analysis.spec_dir,
                "allInOneProcessingSeconds": analysis.processing_seconds,
                "beatCount": len(analysis.beats),
                "downbeatCount": len(analysis.downbeats),
                "segmentCount": len(analysis.segments),
                "activationSummary": dict(analysis.activation_summary),
            }
            | dict(parameters or {}),
            processing_seconds=processing_seconds,
            warnings=warnings,
        )


def register_all_in_one_backends(registry: BackendRegistry) -> None:
    """Register All-In-One for timing and functional section candidate contracts."""

    registry.register_tempo(ALL_IN_ONE_BACKEND, AllInOneBackend)
    registry.register_beat_grid(ALL_IN_ONE_BACKEND, AllInOneBackend)
    registry.register_section(ALL_IN_ONE_BACKEND, AllInOneBackend)
    registry.register_section(ALL_IN_ONE_UNLOCKED_BACKEND, AllInOneUnlockedBackend)


class AllInOneUnlockedBackend(AllInOneBackend):
    """All-In-One section backend with frame activations enabled for experiments."""

    name = ALL_IN_ONE_UNLOCKED_BACKEND

    def __init__(self, **kwargs: Any) -> None:
        kwargs["include_activations"] = True
        kwargs.setdefault("include_embeddings", False)
        super().__init__(**kwargs)


def _install_natten_legacy_api_shim() -> None:
    """Expose the NATTEN 0.14 API names expected by All-In-One.

    All-In-One 1.1.0 imports low-level NATTEN 0.14 functions that are absent in
    current NATTEN builds. NATTEN 0.14 does not build against the current
    PyTorch/CUDA stack, so provide inference-compatible tensor implementations
    before importing allin1.
    """

    try:
        from natten import functional as natten_functional
    except ImportError:
        return

    required = ("natten1dav", "natten1dqkrpb", "natten2dav", "natten2dqkrpb")
    if all(hasattr(natten_functional, name) for name in required):
        return

    natten_functional.natten1dqkrpb = _legacy_natten1dqkrpb  # type: ignore[attr-defined]
    natten_functional.natten1dav = _legacy_natten1dav  # type: ignore[attr-defined]
    natten_functional.natten2dqkrpb = _legacy_natten2dqkrpb  # type: ignore[attr-defined]
    natten_functional.natten2dav = _legacy_natten2dav  # type: ignore[attr-defined]


def _legacy_natten1dqkrpb(query: Any, key: Any, rpb: Any, kernel_size: int, dilation: int) -> Any:
    import torch

    batch, heads, length, dim = query.shape
    offsets = _legacy_offsets(kernel_size, dilation, query.device)
    positions = torch.arange(length, device=query.device)
    center = rpb.shape[-1] // 2
    scores = []
    neg_inf = torch.finfo(query.dtype).min
    for offset in offsets.tolist():
        source = positions + int(offset)
        valid = (source >= 0) & (source < length)
        clipped = source.clamp(0, length - 1)
        gathered = key.index_select(2, clipped)
        score = (query * gathered).sum(dim=-1)
        bias = rpb[:, center + int(offset // dilation)].view(1, heads, 1)
        score = score + bias
        scores.append(torch.where(valid.view(1, 1, length), score, torch.full_like(score, neg_inf)))
    return torch.stack(scores, dim=-1)


def _legacy_natten1dav(attn: Any, value: Any, kernel_size: int, dilation: int) -> Any:
    import torch

    batch, heads, length, dim = value.shape
    del batch, heads
    offsets = _legacy_offsets(kernel_size, dilation, value.device)
    positions = torch.arange(length, device=value.device)
    output = torch.zeros_like(value)
    for kernel_index, offset in enumerate(offsets.tolist()):
        source = positions + int(offset)
        valid = (source >= 0) & (source < length)
        clipped = source.clamp(0, length - 1)
        gathered = value.index_select(2, clipped)
        weight = attn[..., kernel_index].unsqueeze(-1)
        output = output + torch.where(valid.view(1, 1, length, 1), weight * gathered, torch.zeros_like(gathered))
    return output


def _legacy_natten2dqkrpb(query: Any, key: Any, rpb: Any, kernel_size: int, dilation: int) -> Any:
    import torch

    batch, heads, height, width, dim = query.shape
    del batch, dim
    offsets = _legacy_offsets(kernel_size, dilation, query.device)
    y_positions = torch.arange(height, device=query.device)
    x_positions = torch.arange(width, device=query.device)
    center_y = rpb.shape[-2] // 2
    center_x = rpb.shape[-1] // 2
    scores = []
    neg_inf = torch.finfo(query.dtype).min
    for offset_y in offsets.tolist():
        source_y = y_positions + int(offset_y)
        valid_y = (source_y >= 0) & (source_y < height)
        clipped_y = source_y.clamp(0, height - 1)
        key_y = key.index_select(2, clipped_y)
        for offset_x in offsets.tolist():
            source_x = x_positions + int(offset_x)
            valid_x = (source_x >= 0) & (source_x < width)
            clipped_x = source_x.clamp(0, width - 1)
            gathered = key_y.index_select(3, clipped_x)
            score = (query * gathered).sum(dim=-1)
            bias = rpb[
                :,
                center_y + int(offset_y // dilation),
                center_x + int(offset_x // dilation),
            ].view(1, heads, 1, 1)
            valid = valid_y.view(1, 1, height, 1) & valid_x.view(1, 1, 1, width)
            scores.append(torch.where(valid, score + bias, torch.full_like(score, neg_inf)))
    return torch.stack(scores, dim=-1)


def _legacy_natten2dav(attn: Any, value: Any, kernel_size: int, dilation: int) -> Any:
    import torch

    batch, heads, height, width, dim = value.shape
    del batch, heads
    offsets = _legacy_offsets(kernel_size, dilation, value.device)
    y_positions = torch.arange(height, device=value.device)
    x_positions = torch.arange(width, device=value.device)
    output = torch.zeros_like(value)
    kernel_index = 0
    for offset_y in offsets.tolist():
        source_y = y_positions + int(offset_y)
        valid_y = (source_y >= 0) & (source_y < height)
        clipped_y = source_y.clamp(0, height - 1)
        value_y = value.index_select(2, clipped_y)
        for offset_x in offsets.tolist():
            source_x = x_positions + int(offset_x)
            valid_x = (source_x >= 0) & (source_x < width)
            clipped_x = source_x.clamp(0, width - 1)
            gathered = value_y.index_select(3, clipped_x)
            valid = valid_y.view(1, 1, height, 1, 1) & valid_x.view(1, 1, 1, width, 1)
            weight = attn[..., kernel_index].unsqueeze(-1)
            output = output + torch.where(valid, weight * gathered, torch.zeros_like(gathered))
            kernel_index += 1
    return output


def _legacy_offsets(kernel_size: int, dilation: int, device: Any) -> Any:
    import torch

    radius = kernel_size // 2
    return torch.arange(-radius, radius + 1, device=device, dtype=torch.long) * int(dilation)


def _segments(values: Any) -> tuple[AllInOneSegment, ...]:
    if values is None:
        return ()
    segments: list[AllInOneSegment] = []
    for index, value in enumerate(values):
        start = _optional_float(_read_value(value, "start"))
        end = _optional_float(_read_value(value, "end"))
        label = _read_value(value, "label")
        if start is None or end is None or label is None:
            continue
        if end < start:
            continue
        segments.append(
            AllInOneSegment(
                start_seconds=_round_float(start),
                end_seconds=_round_float(end),
                label=str(label),
                confidence=_optional_float(_read_value(value, "confidence")),
                provider_metadata={"sourceIndex": index},
            )
        )
    return tuple(segments)


def _activation_summary(values: Any) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        return {}
    summary: dict[str, Any] = {}
    for key, value in values.items():
        shape = tuple(int(part) for part in getattr(value, "shape", ()) or ())
        item: dict[str, Any] = {"shape": list(shape)}
        try:
            size = int(getattr(value, "size", 0))
            if size:
                item["min"] = _round_float(float(value.min()))
                item["max"] = _round_float(float(value.max()))
                item["mean"] = _round_float(float(value.mean()))
        except Exception:
            pass
        summary[str(key)] = item
    return summary


def _section_candidate(
    segment: AllInOneSegment,
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
            "sourceBackend": ALL_IN_ONE_BACKEND,
            "providerMetadata": dict(segment.provider_metadata),
        },
    )


def _map_section_label(label: str, confidence: float | None = None) -> tuple[str, float, tuple[str, ...]]:
    mapping = map_section_label(
        label,
        confidence=confidence if confidence is not None else 0.60,
        provider_name="all-in-one",
    )
    return (mapping.label, mapping.confidence, mapping.notes)


def _warnings(analysis: AllInOneAnalysis, *, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    warnings = [
        ALL_IN_ONE_LICENSE_NOTE,
        "All-In-One depends on PyTorch, Demucs, madmom, and NATTEN on Linux/Windows.",
    ]
    if analysis.requested_audio_path.suffix.lower() == ".mp3" or analysis.timeline_mode == "source_path":
        warnings.append(ALL_IN_ONE_MP3_TIMELINE_WARNING)
    if analysis.timeline_mode == "analysis_audio_path":
        warnings.append("All-In-One was run against AnalysisContext.analysis_audio_path for timeline consistency.")
    if analysis.requested_device == "auto":
        warnings.append(f"All-In-One auto-selected device: {analysis.effective_device}.")
    if not analysis.cuda_available:
        warnings.append("All-In-One ran without CUDA; benchmark reports should include CPU runtime.")
    warnings.extend(extra)
    return tuple(warnings)


def _nearest_beat_index(time_seconds: float, beat_grid: BeatGridCandidateResult, *, tolerance: float = 0.08) -> int | None:
    if not beat_grid.beats:
        return None
    nearest = min(beat_grid.beats, key=lambda beat: abs(beat.time_seconds - time_seconds))
    if abs(nearest.time_seconds - time_seconds) <= tolerance:
        return nearest.index
    return None


def _beat_position(beat_positions: tuple[int, ...], index: int) -> int | None:
    if index >= len(beat_positions):
        return None
    value = int(beat_positions[index])
    return value if value > 0 else None


def _first_result(raw_result: Any) -> Any:
    if isinstance(raw_result, list):
        if not raw_result:
            raise ValueError("All-In-One returned an empty result list")
        return raw_result[0]
    return raw_result


def _read_value(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_path(value: Any) -> Path | None:
    if value is None:
        return None
    return Path(value)


def _float_sequence(values: Any) -> tuple[float, ...]:
    if values is None:
        return ()
    try:
        return tuple(float(value) for value in values)
    except TypeError:
        return ()


def _int_sequence(values: Any) -> tuple[int, ...]:
    if values is None:
        return ()
    try:
        return tuple(int(value) for value in values)
    except TypeError:
        return ()


def _valid_times(values: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(_round_float(value) for value in sorted(value for value in values if value >= 0))


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
    regularity = 1.0 - min(median_error / (median_interval * 0.20), 1.0)
    count_score = min(len(beats) / 16.0, 1.0)
    return _round_float(_clamp(0.20 + 0.60 * regularity + 0.20 * count_score, ceiling=0.9))


def _backend_error(exc: Exception, *, backend_name: str) -> BackendExecutionError:
    return BackendExecutionError(
        code="all_in_one_failed",
        message=str(exc) or exc.__class__.__name__,
        backend_name=backend_name,
        details={"exceptionType": exc.__class__.__name__},
    )


def _dependency_versions(version_resolver: Callable[[str], str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in _DEPENDENCY_PACKAGES + ("torchaudio",):
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


def _module_available(module_name: str) -> bool:
    try:
        from importlib.util import find_spec

        return find_spec(module_name) is not None
    except Exception:
        return False


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
