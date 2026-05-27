"""Project-owned chroma/profile key detector baseline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
import time
from typing import Any

from .. import __version__
from ..audio_io import DecodedAudio
from ..dependencies import OptionalDependencyUnavailable, require_optional_dependency
from ..key_camelot import camelot_from_tonic_mode
from .base import (
    AnalysisContext,
    BackendExecutionError,
    CandidateProvenance,
    KeyCandidate,
    KeyCandidateResult,
)
from .registry import BackendRegistry


AUTODJ_CHROMA_KEY_BACKEND = "autodj-chroma-profile"
AUTODJ_CHROMA_KEY_MODEL_NAME = "AutoDJ Chroma/Profile Key Detector"
DEFAULT_CHROMA_PROFILE_FAMILY = "krumhansl"
DEFAULT_CHROMA_HOP_LENGTH = 1024
DEFAULT_CHROMA_N_FFT = 4096
MAX_KEY_CANDIDATES = 8

_PITCH_CLASS_NAMES = (
    "C",
    "D-flat",
    "D",
    "E-flat",
    "E",
    "F",
    "F-sharp",
    "G",
    "A-flat",
    "A",
    "B-flat",
    "B",
)

_PROFILE_FAMILIES: dict[str, dict[str, tuple[float, ...]]] = {
    "krumhansl": {
        "major": (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88),
        "minor": (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17),
    },
    "edm-weighted": {
        "major": (1.00, 0.12, 0.28, 0.16, 0.72, 0.38, 0.12, 0.86, 0.18, 0.34, 0.12, 0.34),
        "minor": (1.00, 0.12, 0.30, 0.76, 0.15, 0.38, 0.12, 0.86, 0.54, 0.16, 0.22, 0.18),
    },
}


@dataclass(frozen=True)
class ChromaAnalysisWindow:
    start_seconds: float
    end_seconds: float
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.start_seconds < 0:
            raise ValueError("start_seconds must be greater than or equal to zero")
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        if self.weight <= 0:
            raise ValueError("weight must be greater than zero")


@dataclass(frozen=True)
class ChromaKeyFeatures:
    chroma: tuple[float, ...]
    candidates: tuple[KeyCandidate, ...]
    profile_family: str
    source_sample_rate: int
    hop_length: int
    n_fft: int
    analysis_windows: tuple[ChromaAnalysisWindow, ...] = ()


class ChromaProfileKeyBackend:
    """Portable baseline detector using chroma energy and key profiles."""

    name = AUTODJ_CHROMA_KEY_BACKEND

    def __init__(
        self,
        *,
        profile_family: str = DEFAULT_CHROMA_PROFILE_FAMILY,
        hop_length: int = DEFAULT_CHROMA_HOP_LENGTH,
        n_fft: int = DEFAULT_CHROMA_N_FFT,
        analysis_windows: tuple[ChromaAnalysisWindow, ...] = (),
        dependency_loader: Callable[..., Any] = require_optional_dependency,
        version_resolver: Callable[[str], str] = metadata.version,
        backend_version: str = __version__,
    ) -> None:
        if profile_family not in _PROFILE_FAMILIES:
            raise ValueError(f"unsupported profile_family: {profile_family}")
        if hop_length <= 0:
            raise ValueError("hop_length must be greater than zero")
        if n_fft <= 0:
            raise ValueError("n_fft must be greater than zero")
        self.profile_family = profile_family
        self.hop_length = int(hop_length)
        self.n_fft = int(n_fft)
        self.analysis_windows = tuple(analysis_windows)
        self._dependency_loader = dependency_loader
        self._version_resolver = version_resolver
        self._backend_version = backend_version

    def analyze_key(self, audio: DecodedAudio, context: AnalysisContext) -> KeyCandidateResult:
        del context
        start = time.perf_counter()
        try:
            features = self.extract_features(audio)
            return self.result_from_features(features, processing_seconds=_elapsed(start))
        except OptionalDependencyUnavailable as exc:
            return KeyCandidateResult(
                status="unavailable",
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=BackendExecutionError.from_optional_dependency(self.name, exc),
            )
        except Exception as exc:
            return KeyCandidateResult(
                status="failed",
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=BackendExecutionError(
                    code="autodj_chroma_key_failed",
                    message=str(exc) or exc.__class__.__name__,
                    backend_name=self.name,
                    details={"exceptionType": exc.__class__.__name__},
                ),
            )

    def extract_features(self, audio: DecodedAudio) -> ChromaKeyFeatures:
        numpy = self._dependency_loader("numpy", module_name="numpy", install_extra="analysis")
        librosa = self._dependency_loader("librosa", module_name="librosa", install_extra="analysis")
        samples = numpy.asarray(audio.samples, dtype=numpy.float32).reshape(-1)
        if int(samples.size) == 0:
            raise ValueError("Decoded audio contains no samples")

        n_fft = min(self.n_fft, max(256, _previous_power_of_two(int(samples.size))))
        chroma_matrix = librosa.feature.chroma_stft(
            y=samples,
            sr=int(audio.sample_rate),
            n_fft=n_fft,
            hop_length=self.hop_length,
        )
        chroma = numpy.asarray(chroma_matrix, dtype=numpy.float32)
        if chroma.ndim != 2 or chroma.shape[0] != 12:
            raise ValueError("librosa returned an unexpected chroma shape")
        chroma_energy = numpy.maximum(
            0.0,
            _weighted_chroma_mean(
                chroma,
                sample_rate=int(audio.sample_rate),
                hop_length=self.hop_length,
                windows=self.analysis_windows,
                librosa=librosa,
                numpy=numpy,
            ),
        )
        total = float(numpy.sum(chroma_energy))
        if total <= 0:
            raise ValueError("Chroma energy is empty")
        normalized = tuple(float(value / total) for value in chroma_energy)
        candidates = _rank_key_candidates(normalized, profile_family=self.profile_family, numpy=numpy)
        return ChromaKeyFeatures(
            chroma=normalized,
            candidates=candidates,
            profile_family=self.profile_family,
            source_sample_rate=int(audio.sample_rate),
            hop_length=self.hop_length,
            n_fft=n_fft,
            analysis_windows=self.analysis_windows,
        )

    def result_from_features(
        self,
        features: ChromaKeyFeatures,
        *,
        processing_seconds: float = 0.0,
    ) -> KeyCandidateResult:
        if not features.candidates:
            raise ValueError("No key candidates were produced")
        selected = features.candidates[0]
        return KeyCandidateResult(
            status="ok",
            provenance=self._provenance(
                parameters={
                    "profileFamily": features.profile_family,
                    "sourceSampleRate": features.source_sample_rate,
                    "hopLength": features.hop_length,
                    "nFft": features.n_fft,
                    "analysisWindows": [window_to_dict(window) for window in features.analysis_windows],
                    "chroma": [_round_float(value) for value in features.chroma],
                },
                processing_seconds=processing_seconds,
            ),
            tonic=selected.tonic,
            mode=selected.mode,
            camelot=selected.camelot,
            confidence=selected.confidence,
            candidates=features.candidates[:MAX_KEY_CANDIDATES],
        )

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
            model_name=AUTODJ_CHROMA_KEY_MODEL_NAME,
            dependency_versions=_dependency_versions(self._version_resolver),
            parameters={
                "profileFamily": self.profile_family,
                "hopLength": self.hop_length,
                "nFft": self.n_fft,
                "analysisWindows": [window_to_dict(window) for window in self.analysis_windows],
            }
            | (parameters or {}),
            processing_seconds=processing_seconds,
            warnings=warnings,
        )


def register_chroma_key_backends(registry: BackendRegistry) -> None:
    """Register the project-owned chroma/profile key detector."""

    registry.register_key(AUTODJ_CHROMA_KEY_BACKEND, ChromaProfileKeyBackend)


def window_to_dict(window: ChromaAnalysisWindow) -> dict[str, float]:
    return {
        "startSeconds": _round_float(window.start_seconds),
        "endSeconds": _round_float(window.end_seconds),
        "weight": _round_float(window.weight),
    }


def _weighted_chroma_mean(
    chroma: Any,
    *,
    sample_rate: int,
    hop_length: int,
    windows: tuple[ChromaAnalysisWindow, ...],
    librosa: Any,
    numpy: Any,
) -> Any:
    if not windows:
        return numpy.mean(chroma, axis=1)
    frame_times = numpy.asarray(
        librosa.frames_to_time(numpy.arange(chroma.shape[1]), sr=sample_rate, hop_length=hop_length),
        dtype=numpy.float32,
    )
    weights = numpy.zeros(chroma.shape[1], dtype=numpy.float32)
    for window in windows:
        mask = (frame_times >= window.start_seconds) & (frame_times <= window.end_seconds)
        weights[mask] = numpy.maximum(weights[mask], float(window.weight))
    if float(numpy.sum(weights)) <= 0:
        return numpy.mean(chroma, axis=1)
    return numpy.average(chroma, axis=1, weights=weights)


def _rank_key_candidates(chroma: tuple[float, ...], *, profile_family: str, numpy: Any) -> tuple[KeyCandidate, ...]:
    profiles = _PROFILE_FAMILIES[profile_family]
    raw_scores: list[tuple[float, str, str]] = []
    for mode, profile in profiles.items():
        for tonic_index, tonic in enumerate(_PITCH_CLASS_NAMES):
            rotated = tuple(profile[(pitch_index - tonic_index) % 12] for pitch_index in range(12))
            raw_scores.append((_correlation(chroma, rotated, numpy=numpy), tonic, mode))
    raw_scores.sort(key=lambda item: item[0], reverse=True)
    confidences = _candidate_confidences(tuple(score for score, _, _ in raw_scores))
    candidates: list[KeyCandidate] = []
    for index, ((_, tonic, mode), confidence) in enumerate(zip(raw_scores, confidences)):
        if index >= MAX_KEY_CANDIDATES:
            break
        candidates.append(
            KeyCandidate(
                tonic=tonic,
                mode=mode,
                camelot=camelot_from_tonic_mode(tonic, mode),
                confidence=_round_float(confidence),
                backend=f"{AUTODJ_CHROMA_KEY_BACKEND}.{profile_family}",
            )
        )
    return tuple(candidates)


def _candidate_confidences(scores: tuple[float, ...]) -> tuple[float, ...]:
    if not scores:
        return ()
    top = scores[0]
    second = scores[1] if len(scores) > 1 else top - 1.0
    gap = max(0.0, top - second)
    top_confidence = _clamp(0.45 + gap * 0.45)
    if len(scores) == 1:
        return (top_confidence,)
    minimum = min(scores)
    maximum = max(scores)
    spread = maximum - minimum
    confidences = [top_confidence]
    for score in scores[1:]:
        relative = 0.0 if spread <= 1e-9 else (score - minimum) / spread
        confidences.append(_clamp(0.05 + relative * 0.55))
    return tuple(confidences)


def _correlation(chroma: tuple[float, ...], profile: tuple[float, ...], *, numpy: Any) -> float:
    chroma_array = numpy.asarray(chroma, dtype=numpy.float32)
    profile_array = numpy.asarray(profile, dtype=numpy.float32)
    chroma_centered = chroma_array - float(numpy.mean(chroma_array))
    profile_centered = profile_array - float(numpy.mean(profile_array))
    denominator = float(numpy.linalg.norm(chroma_centered) * numpy.linalg.norm(profile_centered))
    if denominator <= 1e-12:
        return 0.0
    return float(numpy.dot(chroma_centered, profile_centered) / denominator)


def _previous_power_of_two(value: int) -> int:
    return 1 << max(0, value.bit_length() - 1)


def _dependency_versions(version_resolver: Callable[[str], str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in ("numpy", "librosa"):
        try:
            versions[package_name] = version_resolver(package_name)
        except Exception:
            continue
    return versions


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded


def _elapsed(start: float) -> float:
    return round(max(0.0, time.perf_counter() - start), 6)
