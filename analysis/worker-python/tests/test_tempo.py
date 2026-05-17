from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from audio_fixtures import (
    create_140_bpm_click_fixture,
    create_70_bpm_halftime_fixture,
    create_silence_fixture,
)
from autodj_analysis import (
    ANALYZER_VERSION,
    AudioProbe,
    DecodedAudio,
    RepositoryTrack,
    TempoExtractionError,
    TempoFeatures,
    build_analyzed_track_artifact,
    build_beat_grid,
    build_tempo_analysis,
    compute_tempo_features,
    load_audio,
    normalize_dubstep_bpm,
)


def test_normalize_dubstep_bpm_handles_halftime_straight_and_low_confidence_edges() -> None:
    halftime = normalize_dubstep_bpm(70.0)
    straight = normalize_dubstep_bpm(140.0)
    midrange = normalize_dubstep_bpm(110.0)
    outside = normalize_dubstep_bpm(45.0)

    assert halftime.normalized_bpm == 140.0
    assert halftime.tempo_class == "halftime"
    assert halftime.confidence_multiplier == 1.0
    assert straight.normalized_bpm == 140.0
    assert straight.tempo_class == "straight"
    assert midrange.normalized_bpm == 110.0
    assert midrange.confidence_multiplier < 1.0
    assert midrange.warning is not None
    assert outside.normalized_bpm == 180.0
    assert outside.confidence_multiplier < midrange.confidence_multiplier


def test_compute_tempo_features_validates_parameters_before_loading_dependencies() -> None:
    decoded = _decoded([0.1, -0.1])

    invalid_cases = [
        {"hop_length": 0},
        {"start_bpm": 0.0},
        {"min_tempo_bpm": 0.0},
        {"min_tempo_bpm": 140.0, "max_tempo_bpm": 100.0},
    ]

    for invalid_kwargs in invalid_cases:
        with pytest.raises(TempoExtractionError) as exc_info:
            compute_tempo_features(decoded, **invalid_kwargs)
        assert exc_info.value.code == "tempo_invalid_parameters"


def test_compute_tempo_features_reports_missing_numpy_dependency(monkeypatch) -> None:
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

    monkeypatch.setattr("autodj_analysis.tempo.require_optional_dependency", missing_numpy)

    with pytest.raises(TempoExtractionError) as exc_info:
        compute_tempo_features(_decoded([0.1, -0.1, 0.1, -0.1]))

    error = exc_info.value.to_dict()
    assert error["code"] == "tempo_dependency_missing"
    assert error["dependency"] == "numpy"
    assert "analysis" in error["message"]


def test_build_tempo_and_beat_grid_match_analyzed_track_shapes() -> None:
    features = _tempo_features()

    assert build_tempo_analysis(features) == {
        "bpm": 140.0,
        "normalizedBpm": 140.0,
        "confidence": 0.8,
        "tempoClass": "straight",
        "candidates": [{"bpm": 140.0, "confidence": 0.8, "backend": "test"}],
    }
    assert build_beat_grid(features) == {
        "beats": [{"index": 0, "timeSeconds": 0.0, "confidence": 0.8}],
        "downbeats": [],
        "confidence": 0.8,
    }


def test_build_analyzed_track_artifact_can_populate_tempo_features() -> None:
    artifact = build_analyzed_track_artifact(
        _track(),
        _probe(),
        tempo_features=_tempo_features(),
        created_at_utc="2026-05-16T00:00:00Z",
    )

    assert artifact["tempo"]["bpm"] == 140.0
    assert artifact["tempo"]["normalizedBpm"] == 140.0
    assert artifact["tempo"]["confidence"] == 0.8
    assert artifact["beatGrid"]["beats"] == [{"index": 0, "timeSeconds": 0.0, "confidence": 0.8}]
    assert artifact["beatGrid"]["downbeats"] == []
    assert "Downbeats were not emitted." in artifact["quality"]["warnings"]


@pytest.mark.analysis
def test_tempo_features_detect_generated_140_bpm_click_fixture(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_140_bpm_click_fixture(tmp_path, duration_seconds=6.0)
    decoded = load_audio(fixture.path)

    features = compute_tempo_features(decoded)

    assert features.bpm == pytest.approx(140.0, abs=2.0)
    assert features.normalized_bpm == pytest.approx(140.0, abs=2.0)
    assert features.tempo_class == "straight"
    assert features.confidence >= 0.65
    assert features.beat_grid_confidence >= 0.65
    assert len(features.beats) >= 10
    assert features.downbeats == ()
    assert features.candidates
    _assert_beats_near_expected_clicks(features.beats, fixture.expected_beat_times[:8])


@pytest.mark.analysis
def test_tempo_features_normalize_generated_70_bpm_halftime_fixture(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_70_bpm_halftime_fixture(tmp_path, duration_seconds=8.0)
    decoded = load_audio(fixture.path)

    features = compute_tempo_features(decoded)

    assert features.bpm == pytest.approx(70.0, abs=2.0)
    assert features.normalized_bpm == pytest.approx(140.0, abs=3.0)
    assert features.tempo_class == "halftime"
    assert features.confidence >= 0.60
    assert features.beat_grid_confidence >= 0.60
    expected_grid = tuple(index * (60.0 / features.normalized_bpm) for index in range(6))
    _assert_beats_near_expected_clicks(features.beats, expected_grid)


@pytest.mark.analysis
def test_tempo_features_keep_silence_low_confidence(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_silence_fixture(tmp_path, duration_seconds=2.0)
    decoded = load_audio(fixture.path)

    features = compute_tempo_features(decoded)

    assert features.bpm == 140.0
    assert features.normalized_bpm == 140.0
    assert features.confidence == 0.0
    assert features.beat_grid_confidence == 0.0
    assert features.beats == ()
    assert features.downbeats == ()
    assert features.candidates == ()
    assert any("near silence" in warning for warning in features.warnings)


def _tempo_features() -> TempoFeatures:
    return TempoFeatures(
        bpm=140.0,
        normalized_bpm=140.0,
        confidence=0.8,
        tempo_class="straight",
        candidates=({"bpm": 140.0, "confidence": 0.8, "backend": "test"},),
        beats=({"index": 0, "timeSeconds": 0.0, "confidence": 0.8},),
        downbeats=(),
        beat_grid_confidence=0.8,
        warnings=("Downbeats were not emitted.",),
        backend="test",
        hop_length=512,
    )


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


def _assert_beats_near_expected_clicks(
    beats: tuple[dict[str, float | int], ...],
    expected_times: tuple[float, ...],
) -> None:
    emitted_times = [float(beat["timeSeconds"]) for beat in beats[: len(expected_times)]]
    assert len(emitted_times) == len(expected_times)
    for emitted, expected in zip(emitted_times, expected_times):
        assert emitted == pytest.approx(expected, abs=0.06)


def _skip_without_analysis_dependencies() -> None:
    missing = [
        module
        for module in ["numpy", "librosa", "soundfile"]
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        pytest.skip(
            "analysis dependencies are not installed; missing "
            + ", ".join(missing)
            + ". Install the worker with `[analysis]`."
        )
