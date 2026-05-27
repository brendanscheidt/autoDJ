from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from autodj_analysis import EssentiaKeyBackend, EssentiaKeyFeatures
from autodj_analysis.audio_io import DecodedAudio
from autodj_analysis.backends import AnalysisContext
from autodj_analysis.dependencies import DependencyError, OptionalDependencyUnavailable


def test_essentia_key_result_maps_tonic_mode_to_camelot() -> None:
    backend = EssentiaKeyBackend()

    result = backend.result_from_features(
        EssentiaKeyFeatures(
            key="C",
            scale="major",
            strength=0.87,
            source_sample_rate=44_100,
            analysis_sample_rate=44_100,
            profile_type="bgate",
            frame_size=4096,
            hop_size=4096,
            resampled=False,
        )
    )

    assert result.ok is True
    assert result.tonic == "C"
    assert result.mode == "major"
    assert result.camelot == "8B"
    assert result.confidence == 0.87
    assert result.candidates[0].backend == "essentia.KeyExtractor"


def test_essentia_key_backend_reports_missing_dependency_structurally() -> None:
    def missing_dependency(*args, **kwargs):
        raise OptionalDependencyUnavailable(
            DependencyError(
                code="analysis_dependency_missing",
                dependency="essentia",
                module_name="essentia.standard",
                install_extra="analysis-wsl",
                message="essentia is missing",
            )
        )

    backend = EssentiaKeyBackend(dependency_loader=missing_dependency)
    result = backend.analyze_key(_silent_audio(), _context())

    assert result.ok is False
    assert result.status == "unavailable"
    assert result.error is not None
    assert result.error.code == "analysis_dependency_missing"
    assert result.error.backend_name == "essentia-key"


@pytest.mark.analysis_wsl
def test_essentia_key_backend_smoke_detects_synthetic_c_major_fixture() -> None:
    _skip_without_essentia_dependencies()
    import numpy as np

    sample_rate = 44_100
    duration_seconds = 4.0
    times = np.linspace(0.0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    samples = (
        0.35 * np.sin(2.0 * np.pi * 261.625565 * times)
        + 0.28 * np.sin(2.0 * np.pi * 329.627557 * times)
        + 0.32 * np.sin(2.0 * np.pi * 391.995436 * times)
        + 0.18 * np.sin(2.0 * np.pi * 523.251131 * times)
    ).astype(np.float32)

    backend = EssentiaKeyBackend()
    result = backend.analyze_key(
        DecodedAudio(
            samples=samples,
            sample_rate=sample_rate,
            duration_seconds=duration_seconds,
            channels=1,
            source_path=Path("c-major.wav"),
        ),
        _context(),
    )

    assert result.ok is True, result.error
    assert result.tonic == "C"
    assert result.mode == "major"
    assert result.camelot == "8B"


def _context() -> AnalysisContext:
    return AnalysisContext(
        track_id="fixture",
        source_path=Path("fixture.mp3"),
        analysis_audio_path=Path("fixture.wav"),
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


def _skip_without_essentia_dependencies() -> None:
    missing = [module for module in ("numpy", "essentia.standard") if importlib.util.find_spec(module) is None]
    if missing:
        pytest.skip(f"Essentia key dependencies are not installed: {', '.join(missing)}")
