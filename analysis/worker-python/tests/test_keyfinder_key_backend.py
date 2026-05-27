from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from autodj_analysis import KeyFinderKeyBackend, KeyFinderKeyFeatures
from autodj_analysis.audio_io import DecodedAudio
from autodj_analysis.backends import AnalysisContext
from autodj_analysis.dependencies import DependencyError, OptionalDependencyUnavailable


def test_keyfinder_key_result_maps_camelot_to_project_key_shape() -> None:
    result = KeyFinderKeyBackend().result_from_features(
        KeyFinderKeyFeatures(
            key="Em",
            camelot="9A",
            audio_path="fixture.wav",
        )
    )

    assert result.ok is True
    assert result.tonic == "E"
    assert result.mode == "minor"
    assert result.camelot == "9A"
    assert result.confidence == 0.65
    assert result.candidates[0].backend == "keyfinder-py.libKeyFinder"


def test_keyfinder_key_backend_reports_missing_dependency_structurally() -> None:
    def missing_dependency(*args, **kwargs):
        raise OptionalDependencyUnavailable(
            DependencyError(
                code="analysis_dependency_missing",
                dependency="keyfinder",
                module_name="keyfinder",
                install_extra="analysis-wsl",
                message="keyfinder is missing",
            )
        )

    backend = KeyFinderKeyBackend(dependency_loader=missing_dependency)
    result = backend.analyze_key(_silent_audio(), _context(Path("missing.wav")))

    assert result.ok is False
    assert result.status == "unavailable"
    assert result.error is not None
    assert result.error.code == "analysis_dependency_missing"
    assert result.error.backend_name == "keyfinder"


@pytest.mark.analysis_wsl
def test_keyfinder_key_backend_smoke_runs_on_synthetic_fixture(tmp_path: Path) -> None:
    _skip_without_keyfinder_dependencies()
    import numpy as np
    import soundfile as sf

    sample_rate = 44_100
    duration_seconds = 8.0
    times = np.linspace(0.0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    samples = (
        0.35 * np.sin(2.0 * np.pi * 261.625565 * times)
        + 0.28 * np.sin(2.0 * np.pi * 329.627557 * times)
        + 0.32 * np.sin(2.0 * np.pi * 391.995436 * times)
        + 0.18 * np.sin(2.0 * np.pi * 523.251131 * times)
    ).astype(np.float32)
    audio_path = tmp_path / "c-major.wav"
    sf.write(audio_path, samples, sample_rate)

    result = KeyFinderKeyBackend().analyze_key(
        DecodedAudio(
            samples=samples,
            sample_rate=sample_rate,
            duration_seconds=duration_seconds,
            channels=1,
            source_path=audio_path,
        ),
        _context(audio_path),
    )

    assert result.ok is True, result.error
    assert result.camelot is not None
    assert result.provenance.model_name == "libKeyFinder"


def _context(audio_path: Path) -> AnalysisContext:
    return AnalysisContext(
        track_id="fixture",
        source_path=audio_path,
        analysis_audio_path=audio_path,
        duration_seconds=4.0,
    )


def _silent_audio() -> DecodedAudio:
    return DecodedAudio(
        samples=[0.0, 0.0, 0.0],
        sample_rate=3,
        duration_seconds=1.0,
        channels=1,
        source_path=Path("silent.wav"),
    )


def _skip_without_keyfinder_dependencies() -> None:
    missing = [module for module in ("numpy", "soundfile", "keyfinder") if importlib.util.find_spec(module) is None]
    if missing:
        pytest.skip(f"keyfinder dependencies are not installed: {', '.join(missing)}")
