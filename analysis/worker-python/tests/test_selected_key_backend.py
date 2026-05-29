from pathlib import Path

from autodj_analysis.audio_io import DecodedAudio
from autodj_analysis.backends import (
    AnalysisContext,
    BackendExecutionError,
    CandidateProvenance,
    KeyCandidate,
    KeyCandidateResult,
    SELECTED_KEY_BACKEND,
    SELECTED_KEY_MADMOM_CONFIDENCE_THRESHOLD,
    SelectedKeyBackend,
    register_selected_key_backends,
    BackendRegistry,
)


def _audio() -> DecodedAudio:
    return DecodedAudio(
        samples=[0.0, 0.1, 0.0],
        sample_rate=3,
        duration_seconds=1.0,
        channels=1,
        source_path=Path("fixture.mp3"),
    )


def _context() -> AnalysisContext:
    return AnalysisContext(
        track_id="track-001",
        source_path=Path("fixture.mp3"),
        analysis_audio_path=Path("fixture.mp3"),
        duration_seconds=1.0,
    )


def _key_result(
    backend_name: str,
    camelot: str,
    confidence: float,
    *,
    warning: str | None = None,
) -> KeyCandidateResult:
    tonic = "E" if camelot == "9A" else "F#"
    mode = "minor"
    return KeyCandidateResult(
        status="ok",
        provenance=CandidateProvenance(
            backend_name=backend_name,
            backend_version="test-version",
            processing_seconds=0.01,
            warnings=(warning,) if warning else (),
        ),
        tonic=tonic,
        mode=mode,
        camelot=camelot,
        confidence=confidence,
        candidates=(
            KeyCandidate(
                tonic=tonic,
                mode=mode,
                camelot=camelot,
                confidence=confidence,
                backend=backend_name,
            ),
        ),
    )


def _unavailable(backend_name: str) -> KeyCandidateResult:
    return KeyCandidateResult(
        status="unavailable",
        provenance=CandidateProvenance(backend_name=backend_name),
        error=BackendExecutionError(
            code="missing_dependency",
            message=f"{backend_name} is unavailable",
            backend_name=backend_name,
        ),
    )


class _KeyBackend:
    def __init__(self, result: KeyCandidateResult) -> None:
        self._result = result

    def analyze_key(self, audio, context):
        return self._result


class _UnexpectedKeyBackend:
    def analyze_key(self, audio, context):
        raise AssertionError("key backend should not run")


def test_selected_key_backend_uses_confident_madmom_result() -> None:
    madmom = _key_result("madmom-cnn-key", "9A", SELECTED_KEY_MADMOM_CONFIDENCE_THRESHOLD)
    backend = SelectedKeyBackend(
        madmom_backend_factory=lambda: _KeyBackend(madmom),
        keyfinder_backend_factory=_UnexpectedKeyBackend,
    )

    result = backend.analyze_key(_audio(), _context())

    assert result.ok
    assert result.camelot == "9A"
    assert result.provenance.backend_name == SELECTED_KEY_BACKEND
    assert result.provenance.parameters["selectedBackend"] == "madmom-cnn-key"
    assert result.provenance.parameters["madmomConfidenceThreshold"] == SELECTED_KEY_MADMOM_CONFIDENCE_THRESHOLD
    assert [candidate.camelot for candidate in result.candidates] == ["9A"]
    assert result.provenance.parameters["keyfinder"]["status"] == "deferred"


def test_selected_key_backend_falls_back_to_keyfinder_when_madmom_confidence_is_low() -> None:
    madmom = _key_result("madmom-cnn-key", "9A", 0.12)
    keyfinder = _key_result("keyfinder", "11A", 0.65, warning="GPL-family dependency warning")
    backend = SelectedKeyBackend(
        madmom_backend_factory=lambda: _KeyBackend(madmom),
        keyfinder_backend_factory=lambda: _KeyBackend(keyfinder),
    )

    result = backend.analyze_key(_audio(), _context())

    assert result.ok
    assert result.camelot == "11A"
    assert result.provenance.parameters["selectedBackend"] == "keyfinder"
    assert any("Selected keyfinder" in warning for warning in result.provenance.warnings)
    assert any("distant Camelot" in warning for warning in result.provenance.warnings)
    assert "GPL-family dependency warning" in result.provenance.warnings


def test_selected_key_backend_uses_madmom_when_keyfinder_is_unavailable() -> None:
    madmom = _key_result("madmom-cnn-key", "9A", 0.12)
    backend = SelectedKeyBackend(
        madmom_backend_factory=lambda: _KeyBackend(madmom),
        keyfinder_backend_factory=lambda: _KeyBackend(_unavailable("keyfinder")),
    )

    result = backend.analyze_key(_audio(), _context())

    assert result.ok
    assert result.camelot == "9A"
    assert result.provenance.parameters["selectedBackend"] == "madmom-cnn-key"
    assert any("below the production gate" in warning for warning in result.provenance.warnings)


def test_selected_key_backend_reports_unavailable_when_both_components_fail() -> None:
    backend = SelectedKeyBackend(
        madmom_backend_factory=lambda: _KeyBackend(_unavailable("madmom-cnn-key")),
        keyfinder_backend_factory=lambda: _KeyBackend(_unavailable("keyfinder")),
    )

    result = backend.analyze_key(_audio(), _context())

    assert not result.ok
    assert result.status == "unavailable"
    assert result.error is not None
    assert result.error.code == "selected_key_unavailable"


def test_selected_key_backend_registers_with_key_registry() -> None:
    registry = BackendRegistry()

    register_selected_key_backends(registry)

    assert SELECTED_KEY_BACKEND in registry.key_names()
    assert registry.create_key(SELECTED_KEY_BACKEND).name == SELECTED_KEY_BACKEND
