"""Selected production key detector ensemble."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from .. import __version__
from ..audio_io import DecodedAudio
from ..key_camelot import classify_camelot_compatibility
from .base import (
    AnalysisContext,
    BackendExecutionError,
    CandidateProvenance,
    KeyCandidate,
    KeyCandidateResult,
    KeyDetectorBackend,
)
from .keyfinder_key import KEYFINDER_KEY_BACKEND, KeyFinderKeyBackend
from .madmom_key import MADMOM_KEY_BACKEND, MadmomKeyBackend
from .registry import BackendRegistry


SELECTED_KEY_BACKEND = "selected-madmom-keyfinder"
SELECTED_KEY_MODEL_NAME = "Selected Madmom/KeyFinder Ensemble"
SELECTED_KEY_MODEL_VERSION = "confidence-gate-v1"
SELECTED_KEY_MADMOM_CONFIDENCE_THRESHOLD = 0.30

KeyBackendFactory = Callable[[], KeyDetectorBackend]


class SelectedKeyBackend:
    """Production key detector selected from the Spec 008 candidate benchmark."""

    name = SELECTED_KEY_BACKEND

    def __init__(
        self,
        *,
        madmom_backend_factory: KeyBackendFactory = MadmomKeyBackend,
        keyfinder_backend_factory: KeyBackendFactory = KeyFinderKeyBackend,
        madmom_confidence_threshold: float = SELECTED_KEY_MADMOM_CONFIDENCE_THRESHOLD,
        backend_version: str = __version__,
    ) -> None:
        if madmom_confidence_threshold < 0.0 or madmom_confidence_threshold > 1.0:
            raise ValueError("madmom_confidence_threshold must be between 0 and 1")
        self._madmom_backend_factory = madmom_backend_factory
        self._keyfinder_backend_factory = keyfinder_backend_factory
        self.madmom_confidence_threshold = float(madmom_confidence_threshold)
        self._backend_version = backend_version

    def analyze_key(self, audio: DecodedAudio, context: AnalysisContext) -> KeyCandidateResult:
        start = time.perf_counter()
        madmom = _safe_run_backend(self._madmom_backend_factory, audio, context, component_name=MADMOM_KEY_BACKEND)
        if madmom.ok and madmom.confidence >= self.madmom_confidence_threshold:
            keyfinder = _deferred_backend_result(
                KEYFINDER_KEY_BACKEND,
                code="keyfinder_skipped_madmom_confident",
                message=(
                    f"Skipped {KEYFINDER_KEY_BACKEND} because {MADMOM_KEY_BACKEND} confidence "
                    f"{madmom.confidence:.3f} met the production gate."
                ),
            )
            selected, reason = madmom, "madmom_confident"
        else:
            keyfinder = _safe_run_backend(
                self._keyfinder_backend_factory,
                audio,
                context,
                component_name=KEYFINDER_KEY_BACKEND,
            )
            selected, reason = self._select_result(madmom, keyfinder)
        processing_seconds = _elapsed(start)

        if selected is None:
            return KeyCandidateResult(
                status="unavailable",
                provenance=self._provenance(
                    madmom=madmom,
                    keyfinder=keyfinder,
                    processing_seconds=processing_seconds,
                    warnings=(
                        "Selected key ensemble could not produce a usable key; "
                        "both madmom and keyfinder were unavailable or failed.",
                    ),
                ),
                error=BackendExecutionError(
                    code="selected_key_unavailable",
                    message="Selected key ensemble could not produce a usable key.",
                    backend_name=self.name,
                    details={
                        "madmomStatus": madmom.status,
                        "keyfinderStatus": keyfinder.status,
                    },
                ),
            )

        warnings = _selection_warnings(reason, madmom, keyfinder)
        return KeyCandidateResult(
            status="ok",
            provenance=self._provenance(
                madmom=madmom,
                keyfinder=keyfinder,
                selected_backend=selected.provenance.backend_name,
                processing_seconds=processing_seconds,
                warnings=warnings,
            ),
            tonic=selected.tonic,
            mode=selected.mode,
            camelot=selected.camelot,
            confidence=selected.confidence,
            candidates=_combined_candidates(selected, madmom, keyfinder),
        )

    def _select_result(
        self,
        madmom: KeyCandidateResult,
        keyfinder: KeyCandidateResult,
    ) -> tuple[KeyCandidateResult | None, str]:
        if madmom.ok and madmom.confidence >= self.madmom_confidence_threshold:
            return madmom, "madmom_confident"
        if keyfinder.ok:
            return keyfinder, "keyfinder_fallback"
        if madmom.ok:
            return madmom, "madmom_only_below_threshold"
        return None, "no_usable_key"

    def _provenance(
        self,
        *,
        madmom: KeyCandidateResult,
        keyfinder: KeyCandidateResult,
        selected_backend: str | None = None,
        processing_seconds: float = 0.0,
        warnings: tuple[str, ...] = (),
    ) -> CandidateProvenance:
        return CandidateProvenance(
            backend_name=self.name,
            backend_version=self._backend_version,
            model_name=SELECTED_KEY_MODEL_NAME,
            model_version=SELECTED_KEY_MODEL_VERSION,
            dependency_versions={
                **madmom.provenance.dependency_versions,
                **keyfinder.provenance.dependency_versions,
            },
            parameters={
                "madmomConfidenceThreshold": self.madmom_confidence_threshold,
                "selectedBackend": selected_backend,
                "madmom": _result_summary(madmom),
                "keyfinder": _result_summary(keyfinder),
            },
            processing_seconds=processing_seconds,
            warnings=warnings,
        )


def register_selected_key_backends(registry: BackendRegistry) -> None:
    """Register the selected production key detector ensemble."""

    registry.register_key(SELECTED_KEY_BACKEND, SelectedKeyBackend)


def _safe_run_backend(
    backend_factory: KeyBackendFactory,
    audio: DecodedAudio,
    context: AnalysisContext,
    *,
    component_name: str,
) -> KeyCandidateResult:
    try:
        backend = backend_factory()
        return backend.analyze_key(audio, context)
    except Exception as exc:
        return KeyCandidateResult(
            status="failed",
            provenance=CandidateProvenance(backend_name=component_name, backend_version=__version__),
            error=BackendExecutionError(
                code="selected_key_component_failed",
                message=str(exc) or exc.__class__.__name__,
                backend_name=component_name,
                details={"exceptionType": exc.__class__.__name__},
            ),
        )


def _deferred_backend_result(component_name: str, *, code: str, message: str) -> KeyCandidateResult:
    return KeyCandidateResult(
        status="deferred",
        provenance=CandidateProvenance(backend_name=component_name, backend_version=__version__),
        error=BackendExecutionError(
            code=code,
            message=message,
            backend_name=component_name,
        ),
    )


def _selection_warnings(
    reason: str,
    madmom: KeyCandidateResult,
    keyfinder: KeyCandidateResult,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if reason == "madmom_confident":
        warnings.append(
            f"Selected {MADMOM_KEY_BACKEND} because confidence {madmom.confidence:.3f} met the production gate."
        )
    elif reason == "keyfinder_fallback":
        warnings.append(
            f"Selected {KEYFINDER_KEY_BACKEND} because {MADMOM_KEY_BACKEND} confidence "
            f"{madmom.confidence:.3f} was below the production gate or unavailable."
        )
    elif reason == "madmom_only_below_threshold":
        warnings.append(
            f"Selected {MADMOM_KEY_BACKEND} below the production gate because {KEYFINDER_KEY_BACKEND} "
            "was unavailable."
        )
    warnings.extend(madmom.provenance.warnings)
    warnings.extend(keyfinder.provenance.warnings)
    if madmom.ok and keyfinder.ok and madmom.camelot is not None and keyfinder.camelot is not None:
        compatibility = classify_camelot_compatibility(madmom.camelot, keyfinder.camelot)
        if compatibility.classification == "clash":
            warnings.append(
                f"Selected key ensemble candidates disagree by a distant Camelot relationship: "
                f"{MADMOM_KEY_BACKEND}={madmom.camelot}, {KEYFINDER_KEY_BACKEND}={keyfinder.camelot}."
            )
    return tuple(warnings)


def _combined_candidates(
    selected: KeyCandidateResult,
    madmom: KeyCandidateResult,
    keyfinder: KeyCandidateResult,
) -> tuple[KeyCandidate, ...]:
    combined: list[KeyCandidate] = []
    seen: set[tuple[str | None, str | None]] = set()
    for result in (selected, madmom, keyfinder):
        for candidate in result.candidates:
            key = (candidate.camelot, candidate.backend)
            if key in seen:
                continue
            seen.add(key)
            combined.append(candidate)
    return tuple(combined)


def _result_summary(result: KeyCandidateResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": result.status,
        "backendName": result.provenance.backend_name,
        "camelot": result.camelot,
        "confidence": result.confidence,
    }
    if result.error is not None:
        payload["errorCode"] = result.error.code
        payload["errorMessage"] = result.error.message
    return payload


def _elapsed(start: float) -> float:
    return round(time.perf_counter() - start, 6)
