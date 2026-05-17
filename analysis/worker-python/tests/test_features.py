from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from audio_fixtures import (
    create_140_bpm_click_fixture,
    create_energy_ramp_fixture,
    create_silence_fixture,
)
from autodj_analysis import (
    ANALYZER_VERSION,
    AudioProbe,
    DecodedAudio,
    EnergyFeatures,
    FeatureExtractionError,
    RepositoryTrack,
    build_analyzed_track_artifact,
    build_energy_analysis,
    compute_energy_features,
    load_audio,
)


def test_compute_energy_features_validates_parameters_before_loading_dependencies() -> None:
    decoded = _decoded([0.1, -0.1])

    invalid_cases = [
        {"frame_length": 0},
        {"hop_length": 0},
        {"curve_point_count": 0},
        {"bass_cutoff_hz": 0.0},
        {"onset_density_window_seconds": 0.0},
    ]

    for invalid_kwargs in invalid_cases:
        with pytest.raises(FeatureExtractionError) as exc_info:
            compute_energy_features(decoded, **invalid_kwargs)
        assert exc_info.value.code == "feature_invalid_parameters"


def test_compute_energy_features_reports_missing_numpy_dependency(monkeypatch) -> None:
    from autodj_analysis.dependencies import DependencyError, OptionalDependencyUnavailable

    def missing_numpy(*args, **kwargs):
        raise OptionalDependencyUnavailable(
            DependencyError(
                code="analysis_dependency_missing",
                dependency="numpy",
                module_name="numpy",
                install_extra="analysis",
                message="Install the worker with the 'analysis' extra and retry.",
            )
        )

    monkeypatch.setattr("autodj_analysis.features.require_optional_dependency", missing_numpy)

    with pytest.raises(FeatureExtractionError) as exc_info:
        compute_energy_features(_decoded([0.1, -0.1]))

    error = exc_info.value.to_dict()
    assert error["code"] == "feature_dependency_missing"
    assert error["dependency"] == "numpy"
    assert "analysis" in error["message"]


def test_build_energy_analysis_matches_analyzed_track_energy_shape() -> None:
    features = EnergyFeatures(
        global_energy=0.25,
        curve=({"timeSeconds": 0.0, "value": 0.1},),
        bass_energy_curve=({"timeSeconds": 0.0, "value": 0.2},),
        onset_density_curve=({"timeSeconds": 0.0, "value": 0.3},),
        warnings=("Energy estimate is coarse.",),
        frame_length=2048,
        hop_length=512,
        curve_point_count=512,
        bass_cutoff_hz=180.0,
    )

    energy = build_energy_analysis(features)

    assert energy == {
        "globalEnergy": 0.25,
        "curve": [{"timeSeconds": 0.0, "value": 0.1}],
        "bassEnergyCurve": [{"timeSeconds": 0.0, "value": 0.2}],
        "onsetDensityCurve": [{"timeSeconds": 0.0, "value": 0.3}],
    }


def test_build_analyzed_track_artifact_can_populate_energy_features() -> None:
    features = EnergyFeatures(
        global_energy=0.25,
        curve=({"timeSeconds": 0.0, "value": 0.1},),
        bass_energy_curve=({"timeSeconds": 0.0, "value": 0.2},),
        onset_density_curve=({"timeSeconds": 0.0, "value": 0.3},),
        warnings=("Energy estimate is coarse.",),
        frame_length=2048,
        hop_length=512,
        curve_point_count=512,
        bass_cutoff_hz=180.0,
    )

    artifact = build_analyzed_track_artifact(
        _track(),
        _probe(),
        energy_features=features,
        created_at_utc="2026-05-16T00:00:00Z",
    )

    assert artifact["energy"]["globalEnergy"] == 0.25
    assert artifact["energy"]["curve"] == [{"timeSeconds": 0.0, "value": 0.1}]
    assert artifact["energy"]["bassEnergyCurve"] == [{"timeSeconds": 0.0, "value": 0.2}]
    assert artifact["energy"]["onsetDensityCurve"] == [{"timeSeconds": 0.0, "value": 0.3}]
    assert "Energy estimate is coarse." in artifact["quality"]["warnings"]


@pytest.mark.analysis
def test_energy_features_follow_generated_energy_ramp(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_energy_ramp_fixture(tmp_path, duration_seconds=6.0)
    decoded = load_audio(fixture.path)

    features = compute_energy_features(
        decoded,
        frame_length=1024,
        hop_length=512,
        curve_point_count=48,
    )

    assert 0.0 < features.global_energy < 1.0
    assert len(features.curve) == 48
    assert len(features.bass_energy_curve) == 48
    assert len(features.onset_density_curve) == 48
    _assert_curve_is_bounded(features.curve)
    _assert_curve_is_bounded(features.bass_energy_curve)
    _assert_curve_is_bounded(features.onset_density_curve)
    assert _mean_value(features.curve[:12]) < _mean_value(features.curve[-12:])
    assert _mean_value(features.bass_energy_curve[:12]) < _mean_value(features.bass_energy_curve[-12:])


@pytest.mark.analysis
def test_onset_density_responds_to_generated_click_track(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_140_bpm_click_fixture(tmp_path, duration_seconds=4.0)
    decoded = load_audio(fixture.path)

    features = compute_energy_features(
        decoded,
        frame_length=1024,
        hop_length=512,
        curve_point_count=64,
    )

    assert features.onset_density_curve
    assert max(point["value"] for point in features.onset_density_curve) > 0.25
    assert not any("Onset density estimate is weak" in warning for warning in features.warnings)


@pytest.mark.analysis
def test_silence_energy_features_have_low_confidence_warnings(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_silence_fixture(tmp_path, duration_seconds=2.0)
    decoded = load_audio(fixture.path)

    features = compute_energy_features(
        decoded,
        frame_length=1024,
        hop_length=512,
        curve_point_count=16,
    )

    assert features.global_energy == 0.0
    assert all(point["value"] == 0.0 for point in features.curve)
    assert all(point["value"] == 0.0 for point in features.bass_energy_curve)
    assert all(point["value"] == 0.0 for point in features.onset_density_curve)
    assert any("near silence" in warning for warning in features.warnings)
    assert any("Onset density estimate is weak" in warning for warning in features.warnings)


def _decoded(samples: list[float], *, sample_rate: int = 22_050) -> DecodedAudio:
    return DecodedAudio(
        samples=samples,
        sample_rate=sample_rate,
        duration_seconds=len(samples) / sample_rate,
        channels=1,
        source_path=Path("synthetic.wav"),
    )


def _track() -> RepositoryTrack:
    return RepositoryTrack(
        track_id="track-drop-001",
        repository_id="local-test-repo",
        source_uri="track.wav",
        source_path=Path("track.wav"),
        content_hash="sha256:source-a",
        format_hint="wav",
        title="Track",
        artist=None,
        album=None,
        duration_seconds=2.0,
        sample_rate=22_050,
        channels=1,
        provider_metadata={},
    )


def _probe() -> AudioProbe:
    return AudioProbe(
        duration_seconds=2.0,
        sample_rate=22_050,
        channels=1,
        codec_name="pcm_s16le",
        codec_long_name="PCM signed 16-bit little-endian",
        bit_rate=705600,
        format_name="wav",
        format_long_name="WAV / WAVE",
        tags={},
        raw={"streams": [], "format": {}},
    )


def _assert_curve_is_bounded(curve: tuple[dict[str, float], ...]) -> None:
    assert curve
    assert all(0.0 <= point["value"] <= 1.0 for point in curve)
    assert all(point["timeSeconds"] >= 0.0 for point in curve)


def _mean_value(points: tuple[dict[str, float], ...]) -> float:
    return sum(point["value"] for point in points) / len(points)


def _skip_without_analysis_dependencies() -> None:
    missing = [
        module
        for module in ["numpy", "scipy", "librosa", "soundfile"]
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        pytest.skip(
            "analysis dependencies are not installed; missing "
            + ", ".join(missing)
            + ". Install the worker with `[analysis]`."
        )
