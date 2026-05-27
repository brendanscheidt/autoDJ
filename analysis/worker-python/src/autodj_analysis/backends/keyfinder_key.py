"""libKeyFinder Python binding backend adapter for key candidates."""

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
from ..key_camelot import CamelotKeyError, parse_camelot
from .base import (
    AnalysisContext,
    BackendExecutionError,
    CandidateProvenance,
    KeyCandidate,
    KeyCandidateResult,
)
from .registry import BackendRegistry


KEYFINDER_KEY_BACKEND = "keyfinder"
KEYFINDER_KEY_MODEL_NAME = "libKeyFinder"
KEYFINDER_KEY_LICENSE_NOTE = (
    "libKeyFinder and keyfinder-py are GPL-family dependencies; distribution licensing must be reviewed before bundling."
)
DEFAULT_KEYFINDER_CONFIDENCE = 0.65


@dataclass(frozen=True)
class KeyFinderKeyFeatures:
    key: str
    camelot: str
    audio_path: str


class KeyFinderKeyBackend:
    """Optional libKeyFinder-backed key detector candidate."""

    name = KEYFINDER_KEY_BACKEND

    def __init__(
        self,
        *,
        dependency_loader: Callable[..., Any] = require_optional_dependency,
        version_resolver: Callable[[str], str] = metadata.version,
        backend_version: str = __version__,
        confidence: float = DEFAULT_KEYFINDER_CONFIDENCE,
    ) -> None:
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("confidence must be between 0 and 1")
        self._dependency_loader = dependency_loader
        self._version_resolver = version_resolver
        self._backend_version = backend_version
        self.confidence = float(confidence)

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
                    code="keyfinder_key_failed",
                    message=str(exc) or exc.__class__.__name__,
                    backend_name=self.name,
                    details={"exceptionType": exc.__class__.__name__},
                ),
            )

    def extract_features(self, context: AnalysisContext) -> KeyFinderKeyFeatures:
        keyfinder = self._dependency_loader(
            "keyfinder",
            module_name="keyfinder",
            install_extra="analysis-wsl",
        )
        audio_path = _select_audio_path(context)
        result = keyfinder.key(str(audio_path))
        key = str(result.standard())
        camelot = str(result.camelot())
        if not key:
            raise ValueError("keyfinder returned an empty key")
        if not camelot:
            raise ValueError("keyfinder returned an empty Camelot key")
        return KeyFinderKeyFeatures(
            key=key,
            camelot=camelot,
            audio_path=str(audio_path),
        )

    def result_from_features(
        self,
        features: KeyFinderKeyFeatures,
        *,
        processing_seconds: float = 0.0,
    ) -> KeyCandidateResult:
        try:
            camelot_key = parse_camelot(features.camelot)
        except CamelotKeyError as exc:
            raise ValueError(exc.message) from exc

        candidate = KeyCandidate(
            tonic=camelot_key.tonic,
            mode=camelot_key.mode,
            camelot=camelot_key.camelot,
            confidence=self.confidence,
            backend="keyfinder-py.libKeyFinder",
        )
        return KeyCandidateResult(
            status="ok",
            provenance=self._provenance(
                parameters={
                    "rawKey": features.key,
                    "rawCamelot": features.camelot,
                    "audioPath": features.audio_path,
                    "confidenceModel": "fixed_wrapper_default",
                    "licenseNote": KEYFINDER_KEY_LICENSE_NOTE,
                },
                processing_seconds=processing_seconds,
                warnings=(KEYFINDER_KEY_LICENSE_NOTE,),
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
            model_name=KEYFINDER_KEY_MODEL_NAME,
            model_version=_dependency_version("keyfinder", self._version_resolver),
            dependency_versions=_dependency_versions(self._version_resolver),
            parameters={
                "confidence": self.confidence,
                "licenseNote": KEYFINDER_KEY_LICENSE_NOTE,
            }
            | (parameters or {}),
            processing_seconds=processing_seconds,
            warnings=warnings,
        )


def register_keyfinder_key_backends(registry: BackendRegistry) -> None:
    """Register libKeyFinder as a key detector candidate."""

    registry.register_key(KEYFINDER_KEY_BACKEND, KeyFinderKeyBackend)


def _select_audio_path(context: AnalysisContext) -> Path:
    for candidate in (context.analysis_audio_path, context.source_path):
        path = Path(candidate)
        if path.exists():
            return path
    raise FileNotFoundError(
        f"No readable audio path for keyfinder backend: {context.analysis_audio_path}"
    )


def _dependency_versions(version_resolver: Callable[[str], str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    version = _dependency_version("keyfinder", version_resolver)
    if version is not None:
        versions["keyfinder"] = version
    return versions


def _dependency_version(package_name: str, version_resolver: Callable[[str], str]) -> str | None:
    try:
        return version_resolver(package_name)
    except Exception:
        return None


def _elapsed(start: float) -> float:
    return round(max(0.0, time.perf_counter() - start), 6)
