from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from autodj_analysis import ChromaAnalysisWindow, ChromaProfileKeyBackend
from autodj_analysis.audio_io import DecodedAudio
from autodj_analysis.backends import AnalysisContext
from autodj_analysis.dependencies import DependencyError, OptionalDependencyUnavailable


def test_chroma_profile_key_backend_detects_synthetic_c_major_fixture() -> None:
    _skip_without_key_dependencies()
    import numpy as np

    sample_rate = 22_050
    duration_seconds = 4.0
    times = np.linspace(0.0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    samples = (
        0.35 * np.sin(2.0 * np.pi * 261.625565 * times)
        + 0.28 * np.sin(2.0 * np.pi * 329.627557 * times)
        + 0.32 * np.sin(2.0 * np.pi * 391.995436 * times)
        + 0.18 * np.sin(2.0 * np.pi * 523.251131 * times)
    ).astype(np.float32)

    backend = ChromaProfileKeyBackend(profile_family="krumhansl", hop_length=512, n_fft=2048)
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
    assert result.candidates[0].backend == "autodj-chroma-profile.krumhansl"
    assert result.provenance.parameters["profileFamily"] == "krumhansl"


def test_chroma_profile_key_backend_records_analysis_window_hooks() -> None:
    _skip_without_key_dependencies()
    audio = _c_major_audio()
    backend = ChromaProfileKeyBackend(
        profile_family="edm-weighted",
        hop_length=512,
        n_fft=2048,
        analysis_windows=(ChromaAnalysisWindow(start_seconds=1.0, end_seconds=3.0, weight=2.0),),
    )

    result = backend.analyze_key(audio, _context())

    assert result.ok is True, result.error
    assert result.provenance.parameters["profileFamily"] == "edm-weighted"
    assert result.provenance.parameters["analysisWindows"] == [
        {"startSeconds": 1.0, "endSeconds": 3.0, "weight": 2.0}
    ]


def test_chroma_profile_key_backend_reports_missing_dependencies_structurally() -> None:
    def missing_dependency(*args, **kwargs):
        raise OptionalDependencyUnavailable(
            DependencyError(
                code="analysis_dependency_missing",
                dependency="numpy",
                module_name="numpy",
                install_extra="analysis",
                message="numpy is missing",
            )
        )

    backend = ChromaProfileKeyBackend(dependency_loader=missing_dependency)
    result = backend.analyze_key(_silent_audio(), _context())

    assert result.ok is False
    assert result.status == "unavailable"
    assert result.error is not None
    assert result.error.code == "analysis_dependency_missing"
    assert result.error.backend_name == "autodj-chroma-profile"


def _context() -> AnalysisContext:
    return AnalysisContext(
        track_id="fixture",
        source_path=Path("fixture.mp3"),
        analysis_audio_path=Path("fixture.wav"),
        duration_seconds=4.0,
    )


def _c_major_audio() -> DecodedAudio:
    import numpy as np

    sample_rate = 22_050
    duration_seconds = 4.0
    times = np.linspace(0.0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    samples = (
        0.35 * np.sin(2.0 * np.pi * 261.625565 * times)
        + 0.28 * np.sin(2.0 * np.pi * 329.627557 * times)
        + 0.32 * np.sin(2.0 * np.pi * 391.995436 * times)
        + 0.18 * np.sin(2.0 * np.pi * 523.251131 * times)
    ).astype(np.float32)
    return DecodedAudio(
        samples=samples,
        sample_rate=sample_rate,
        duration_seconds=duration_seconds,
        channels=1,
        source_path=Path("c-major.wav"),
    )


def _silent_audio() -> DecodedAudio:
    return DecodedAudio(
        samples=[0.0, 0.0, 0.0],
        sample_rate=3,
        duration_seconds=1.0,
        channels=1,
        source_path=Path("silent.wav"),
    )


def _skip_without_key_dependencies() -> None:
    missing = [module for module in ("numpy", "librosa") if importlib.util.find_spec(module) is None]
    if missing:
        pytest.skip(f"key analysis dependencies are not installed: {', '.join(missing)}")
