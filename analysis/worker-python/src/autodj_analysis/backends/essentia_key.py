"""Essentia KeyExtractor backend adapter for key candidates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
import time
from typing import Any

from .. import __version__
from ..audio_io import DecodedAudio
from ..dependencies import OptionalDependencyUnavailable, require_optional_dependency
from ..key_camelot import CamelotKeyError, camelot_from_tonic_mode
from .base import (
    AnalysisContext,
    BackendExecutionError,
    CandidateProvenance,
    KeyCandidate,
    KeyCandidateResult,
)
from .registry import BackendRegistry


ESSENTIA_KEY_BACKEND = "essentia-key"
ESSENTIA_KEY_MODEL_NAME = "Essentia KeyExtractor"
ESSENTIA_KEY_LICENSE_NOTE = "Essentia is AGPLv3 for non-commercial use; commercial licensing must be reviewed before distribution."
DEFAULT_ESSENTIA_KEY_PROFILE_TYPE = "bgate"
DEFAULT_ESSENTIA_KEY_ANALYSIS_SAMPLE_RATE = 44_100
DEFAULT_ESSENTIA_KEY_FRAME_SIZE = 4096
DEFAULT_ESSENTIA_KEY_HOP_SIZE = 4096


@dataclass(frozen=True)
class EssentiaKeyFeatures:
    key: str
    scale: str
    strength: float
    source_sample_rate: int
    analysis_sample_rate: int
    profile_type: str
    frame_size: int
    hop_size: int
    resampled: bool


class EssentiaKeyBackend:
    """Optional Essentia-backed key detector candidate."""

    name = ESSENTIA_KEY_BACKEND

    def __init__(
        self,
        *,
        profile_type: str = DEFAULT_ESSENTIA_KEY_PROFILE_TYPE,
        analysis_sample_rate: int = DEFAULT_ESSENTIA_KEY_ANALYSIS_SAMPLE_RATE,
        frame_size: int = DEFAULT_ESSENTIA_KEY_FRAME_SIZE,
        hop_size: int = DEFAULT_ESSENTIA_KEY_HOP_SIZE,
        dependency_loader: Callable[..., Any] = require_optional_dependency,
        version_resolver: Callable[[str], str] = metadata.version,
        backend_version: str = __version__,
    ) -> None:
        if not profile_type:
            raise ValueError("profile_type must not be empty")
        if analysis_sample_rate <= 0:
            raise ValueError("analysis_sample_rate must be greater than zero")
        if frame_size <= 0:
            raise ValueError("frame_size must be greater than zero")
        if hop_size <= 0:
            raise ValueError("hop_size must be greater than zero")
        self.profile_type = profile_type
        self.analysis_sample_rate = int(analysis_sample_rate)
        self.frame_size = int(frame_size)
        self.hop_size = int(hop_size)
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
                    code="essentia_key_failed",
                    message=str(exc) or exc.__class__.__name__,
                    backend_name=self.name,
                    details={"exceptionType": exc.__class__.__name__},
                ),
            )

    def extract_features(self, audio: DecodedAudio) -> EssentiaKeyFeatures:
        numpy = self._dependency_loader("numpy", module_name="numpy", install_extra="analysis-wsl")
        essentia_standard = self._dependency_loader(
            "essentia",
            module_name="essentia.standard",
            install_extra="analysis-wsl",
        )
        samples = numpy.asarray(audio.samples, dtype=numpy.float32).reshape(-1)
        if int(samples.size) == 0:
            raise ValueError("Decoded audio contains no samples")

        resampled = False
        if audio.sample_rate != self.analysis_sample_rate:
            samples = essentia_standard.Resample(
                inputSampleRate=float(audio.sample_rate),
                outputSampleRate=float(self.analysis_sample_rate),
            )(samples).astype(numpy.float32, copy=False)
            resampled = True

        extractor = essentia_standard.KeyExtractor(
            sampleRate=float(self.analysis_sample_rate),
            profileType=self.profile_type,
            frameSize=int(self.frame_size),
            hopSize=int(self.hop_size),
        )
        key, scale, strength = extractor(samples)
        return EssentiaKeyFeatures(
            key=str(key),
            scale=str(scale),
            strength=float(strength),
            source_sample_rate=int(audio.sample_rate),
            analysis_sample_rate=self.analysis_sample_rate,
            profile_type=self.profile_type,
            frame_size=self.frame_size,
            hop_size=self.hop_size,
            resampled=resampled,
        )

    def result_from_features(
        self,
        features: EssentiaKeyFeatures,
        *,
        processing_seconds: float = 0.0,
    ) -> KeyCandidateResult:
        mode = _scale_to_mode(features.scale)
        try:
            camelot = camelot_from_tonic_mode(features.key, mode)
        except CamelotKeyError as exc:
            raise ValueError(exc.message) from exc
        confidence = _clamp(features.strength)
        candidate = KeyCandidate(
            tonic=_canonical_tonic(features.key),
            mode=mode,
            camelot=camelot,
            confidence=confidence,
            backend="essentia.KeyExtractor",
        )
        return KeyCandidateResult(
            status="ok",
            provenance=self._provenance(
                parameters={
                    "profileType": features.profile_type,
                    "sourceSampleRate": features.source_sample_rate,
                    "analysisSampleRate": features.analysis_sample_rate,
                    "frameSize": features.frame_size,
                    "hopSize": features.hop_size,
                    "resampled": features.resampled,
                    "rawStrength": features.strength,
                },
                processing_seconds=processing_seconds,
                warnings=_warnings(features),
            ),
            tonic=candidate.tonic,
            mode=candidate.mode,
            camelot=candidate.camelot,
            confidence=candidate.confidence,
            candidates=(candidate,),
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
            model_name=ESSENTIA_KEY_MODEL_NAME,
            model_version=_dependency_version("essentia", self._version_resolver),
            dependency_versions=_dependency_versions(self._version_resolver),
            parameters={
                "profileType": self.profile_type,
                "analysisSampleRate": self.analysis_sample_rate,
                "frameSize": self.frame_size,
                "hopSize": self.hop_size,
                "licenseNote": ESSENTIA_KEY_LICENSE_NOTE,
            }
            | (parameters or {}),
            processing_seconds=processing_seconds,
            warnings=warnings,
        )


def register_essentia_key_backends(registry: BackendRegistry) -> None:
    """Register Essentia KeyExtractor as a key detector candidate."""

    registry.register_key(ESSENTIA_KEY_BACKEND, EssentiaKeyBackend)


def _scale_to_mode(scale: str) -> str:
    normalized = scale.strip().lower()
    if normalized in {"major", "minor"}:
        return normalized
    raise ValueError(f"Unsupported Essentia scale value: {scale!r}")


def _canonical_tonic(value: str) -> str:
    aliases = {
        "Ab": "A-flat",
        "Bb": "B-flat",
        "Db": "D-flat",
        "Eb": "E-flat",
        "F#": "F-sharp",
        "Gb": "F-sharp",
    }
    return aliases.get(value.strip(), value.strip())


def _warnings(features: EssentiaKeyFeatures) -> tuple[str, ...]:
    warnings = [ESSENTIA_KEY_LICENSE_NOTE]
    if features.resampled:
        warnings.append(
            f"Audio was resampled from {features.source_sample_rate} Hz to "
            f"{features.analysis_sample_rate} Hz for Essentia key analysis."
        )
    return tuple(warnings)


def _dependency_versions(version_resolver: Callable[[str], str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in ("essentia", "numpy"):
        version = _dependency_version(package_name, version_resolver)
        if version is not None:
            versions[package_name] = version
    return versions


def _dependency_version(package_name: str, version_resolver: Callable[[str], str]) -> str | None:
    try:
        return version_resolver(package_name)
    except Exception:
        return None


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _elapsed(start: float) -> float:
    return round(max(0.0, time.perf_counter() - start), 6)
