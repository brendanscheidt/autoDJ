"""madmom CNN key recognition backend adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
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


MADMOM_KEY_BACKEND = "madmom-cnn-key"
MADMOM_KEY_MODEL_NAME = "madmom CNNKeyRecognitionProcessor"
MADMOM_KEY_MODEL_REFERENCE = "Korzeniowski/Widmer genre-agnostic CNN key recognition"
MAX_MADMOM_KEY_CANDIDATES = 8


@dataclass(frozen=True)
class MadmomKeyFeatures:
    labels: tuple[str, ...]
    probabilities: tuple[float, ...]
    audio_path: str


class MadmomKeyBackend:
    """Optional madmom CNN global-key detector candidate."""

    name = MADMOM_KEY_BACKEND

    def __init__(
        self,
        *,
        dependency_loader: Callable[..., Any] = require_optional_dependency,
        version_resolver: Callable[[str], str] = metadata.version,
        backend_version: str = __version__,
    ) -> None:
        self._dependency_loader = dependency_loader
        self._version_resolver = version_resolver
        self._backend_version = backend_version

    def analyze_key(self, audio: DecodedAudio, context: AnalysisContext) -> KeyCandidateResult:
        del audio
        start = time.perf_counter()
        try:
            features = self.extract_features(context)
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
                    code="madmom_key_failed",
                    message=str(exc) or exc.__class__.__name__,
                    backend_name=self.name,
                    details={"exceptionType": exc.__class__.__name__},
                ),
            )

    def extract_features(self, context: AnalysisContext) -> MadmomKeyFeatures:
        numpy = self._dependency_loader("numpy", module_name="numpy", install_extra="all-in-one")
        key_module = self._dependency_loader(
            "madmom",
            module_name="madmom.features.key",
            install_extra="all-in-one",
        )
        audio_path = _existing_audio_path(context)
        processor = key_module.CNNKeyRecognitionProcessor()
        raw = processor(str(audio_path))
        probabilities = numpy.asarray(raw, dtype=numpy.float32)
        if probabilities.ndim == 2:
            probabilities = numpy.mean(probabilities, axis=0)
        if probabilities.ndim != 1 or probabilities.size != len(key_module.KEY_LABELS):
            raise ValueError("madmom returned an unexpected key probability shape")
        total = float(numpy.sum(probabilities))
        if total > 0:
            probabilities = probabilities / total
        return MadmomKeyFeatures(
            labels=tuple(str(label) for label in key_module.KEY_LABELS),
            probabilities=tuple(float(value) for value in probabilities),
            audio_path=str(audio_path),
        )

    def result_from_features(
        self,
        features: MadmomKeyFeatures,
        *,
        processing_seconds: float = 0.0,
    ) -> KeyCandidateResult:
        candidates = _candidates_from_probabilities(features)
        if not candidates:
            raise ValueError("No madmom key candidates were produced")
        selected = candidates[0]
        return KeyCandidateResult(
            status="ok",
            provenance=self._provenance(
                parameters={
                    "audioPath": features.audio_path,
                    "classCount": len(features.labels),
                    "modelReference": MADMOM_KEY_MODEL_REFERENCE,
                },
                processing_seconds=processing_seconds,
            ),
            tonic=selected.tonic,
            mode=selected.mode,
            camelot=selected.camelot,
            confidence=selected.confidence,
            candidates=candidates,
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
            model_name=MADMOM_KEY_MODEL_NAME,
            model_version=_dependency_version("madmom", self._version_resolver),
            dependency_versions=_dependency_versions(self._version_resolver),
            parameters=parameters or {},
            processing_seconds=processing_seconds,
            warnings=warnings,
        )


def register_madmom_key_backends(registry: BackendRegistry) -> None:
    """Register madmom CNN key recognition as a key detector candidate."""

    registry.register_key(MADMOM_KEY_BACKEND, MadmomKeyBackend)


def _existing_audio_path(context: AnalysisContext) -> Path:
    for candidate in (context.analysis_audio_path, context.source_path):
        path = Path(candidate)
        if path.exists():
            return path
    raise ValueError("madmom key analysis requires an existing audio file path")


def _candidates_from_probabilities(features: MadmomKeyFeatures) -> tuple[KeyCandidate, ...]:
    ranked = sorted(
        zip(features.labels, features.probabilities),
        key=lambda item: item[1],
        reverse=True,
    )
    candidates: list[KeyCandidate] = []
    for label, probability in ranked[:MAX_MADMOM_KEY_CANDIDATES]:
        tonic, mode = _parse_label(label)
        candidates.append(
            KeyCandidate(
                tonic=_canonical_tonic(tonic),
                mode=mode,
                camelot=camelot_from_tonic_mode(tonic, mode),
                confidence=_round_float(_clamp(probability)),
                backend="madmom.CNNKeyRecognitionProcessor",
            )
        )
    return tuple(candidates)


def _parse_label(label: str) -> tuple[str, str]:
    parts = label.strip().split()
    if len(parts) != 2 or parts[1].lower() not in {"major", "minor"}:
        raise ValueError(f"Unexpected madmom key label: {label!r}")
    return parts[0], parts[1].lower()


def _canonical_tonic(value: str) -> str:
    aliases = {
        "Ab": "A-flat",
        "Bb": "B-flat",
        "C#": "D-flat",
        "Db": "D-flat",
        "D#": "E-flat",
        "Eb": "E-flat",
        "F#": "F-sharp",
        "Gb": "F-sharp",
        "G#": "A-flat",
    }
    return aliases.get(value.strip(), value.strip())


def _dependency_versions(version_resolver: Callable[[str], str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in ("madmom", "numpy"):
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


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded


def _elapsed(start: float) -> float:
    return round(max(0.0, time.perf_counter() - start), 6)
