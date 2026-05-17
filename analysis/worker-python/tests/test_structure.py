from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from audio_fixtures import create_energy_ramp_fixture, create_silence_fixture
from autodj_analysis import (
    AudioProbe,
    EnergyFeatures,
    RepositoryTrack,
    StructureExtractionError,
    StructureFeatures,
    TempoFeatures,
    build_analyzed_track_artifact,
    build_cue_points,
    build_sections,
    compute_energy_features,
    compute_structure_features,
    load_audio,
)


def test_compute_structure_features_detects_conservative_sections_and_cues() -> None:
    features = compute_structure_features(_energy_features())

    assert [section["type"] for section in features.sections] == ["intro", "build", "drop"]
    assert [cue["type"] for cue in features.cue_points] == ["mix_in", "build_start", "drop"]
    assert features.sections[0]["startSeconds"] == 0.0
    assert features.sections[0]["endSeconds"] == 3.0
    assert features.sections[1]["startSeconds"] == 3.0
    assert features.sections[1]["endSeconds"] == 5.08
    assert features.sections[2]["startSeconds"] == 5.08
    assert features.sections[2]["confidence"] < 0.85
    assert features.cue_points[-1]["sectionId"] == "section-drop-001"
    assert any("heuristic" in warning for warning in features.warnings)


def test_compute_structure_features_snaps_cues_to_high_confidence_beat_grid() -> None:
    features = compute_structure_features(
        _energy_features(),
        tempo_features=_tempo_features(confidence=0.9),
    )

    drop_cue = next(cue for cue in features.cue_points if cue["type"] == "drop")
    build_cue = next(cue for cue in features.cue_points if cue["type"] == "build_start")

    assert drop_cue["timeSeconds"] == 5.0
    assert drop_cue["beatIndex"] == 5
    assert "beat_snapped" in drop_cue["tags"]
    assert build_cue["timeSeconds"] == 3.0
    assert build_cue["beatIndex"] == 3
    drop_section = next(section for section in features.sections if section["type"] == "drop")
    assert drop_section["startBeatIndex"] == 5


def test_compute_structure_features_does_not_snap_low_confidence_beat_grid() -> None:
    features = compute_structure_features(
        _energy_features(),
        tempo_features=_tempo_features(confidence=0.4),
    )

    drop_cue = next(cue for cue in features.cue_points if cue["type"] == "drop")

    assert drop_cue["timeSeconds"] == 5.08
    assert "beatIndex" not in drop_cue
    assert "beat_snapped" not in drop_cue["tags"]


def test_compute_structure_features_prefers_empty_outputs_for_weak_evidence() -> None:
    features = compute_structure_features(
        _energy_features(values=(0.04, 0.05, 0.04, 0.05), times=(0.0, 1.0, 2.0, 3.0)),
        duration_seconds=4.0,
    )

    assert features.sections == ()
    assert features.cue_points == ()
    assert any("weak energy contrast" in warning for warning in features.warnings)
    assert any("not production-grade" in warning for warning in features.warnings)


def test_compute_structure_features_validates_parameters() -> None:
    invalid_cases = [
        {"high_energy_threshold": 0.0},
        {"low_energy_threshold": 1.0},
        {"low_energy_threshold": 0.8, "high_energy_threshold": 0.7},
        {"min_section_seconds": 0.0},
        {"cue_snap_seconds": -0.1},
    ]

    for invalid_kwargs in invalid_cases:
        with pytest.raises(StructureExtractionError) as exc_info:
            compute_structure_features(_energy_features(), **invalid_kwargs)
        assert exc_info.value.code == "structure_invalid_parameters"


def test_build_sections_and_cue_points_match_analyzed_track_shapes() -> None:
    features = compute_structure_features(_energy_features())

    sections = build_sections(features)
    cue_points = build_cue_points(features)

    assert sections[0]["id"] == "section-intro-001"
    assert {"id", "type", "startSeconds", "endSeconds", "confidence"}.issubset(sections[0])
    assert cue_points[-1]["id"] == "cue-drop-001"
    assert {"id", "type", "timeSeconds", "confidence"}.issubset(cue_points[-1])


def test_build_analyzed_track_artifact_can_populate_structure_features() -> None:
    structure_features = StructureFeatures(
        sections=(
            {
                "id": "section-drop-001",
                "type": "drop",
                "startSeconds": 5.0,
                "endSeconds": 8.0,
                "confidence": 0.65,
            },
        ),
        cue_points=(
            {
                "id": "cue-drop-001",
                "type": "drop",
                "timeSeconds": 5.0,
                "sectionId": "section-drop-001",
                "confidence": 0.65,
            },
        ),
        warnings=("Rough sections and cue candidates are heuristic.",),
        backend="test",
        high_energy_threshold=0.65,
        low_energy_threshold=0.35,
    )

    artifact = build_analyzed_track_artifact(
        _track(),
        _probe(),
        structure_features=structure_features,
        created_at_utc="2026-05-16T00:00:00Z",
    )

    assert artifact["sections"] == list(structure_features.sections)
    assert artifact["cuePoints"] == list(structure_features.cue_points)
    assert "Rough sections and cue candidates are heuristic." in artifact["quality"]["warnings"]


@pytest.mark.analysis
def test_structure_features_use_generated_energy_ramp_fixture(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_energy_ramp_fixture(tmp_path, duration_seconds=6.0)
    decoded = load_audio(fixture.path)
    energy = compute_energy_features(decoded, frame_length=1024, hop_length=512, curve_point_count=48)

    structure = compute_structure_features(energy, duration_seconds=decoded.duration_seconds)

    assert any(section["type"] == "drop" for section in structure.sections)
    assert any(cue["type"] == "drop" for cue in structure.cue_points)
    drop_section = next(section for section in structure.sections if section["type"] == "drop")
    assert drop_section["startSeconds"] >= 3.0
    assert drop_section["confidence"] < 0.85
    assert any("heuristic" in warning for warning in structure.warnings)


@pytest.mark.analysis
def test_structure_features_keep_generated_silence_empty_with_warning(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_silence_fixture(tmp_path, duration_seconds=2.0)
    decoded = load_audio(fixture.path)
    energy = compute_energy_features(decoded, frame_length=1024, hop_length=512, curve_point_count=16)

    structure = compute_structure_features(energy, duration_seconds=decoded.duration_seconds)

    assert structure.sections == ()
    assert structure.cue_points == ()
    assert any("weak energy contrast" in warning for warning in structure.warnings)


def _energy_features(
    *,
    values: tuple[float, ...] = (0.10, 0.10, 0.20, 0.40, 0.55, 0.75, 0.85, 0.80),
    times: tuple[float, ...] = (0.0, 1.0, 2.0, 3.0, 4.08, 5.08, 6.08, 7.08),
) -> EnergyFeatures:
    curve = tuple({"timeSeconds": time, "value": value} for time, value in zip(times, values))
    bass_curve = tuple({"timeSeconds": point["timeSeconds"], "value": point["value"]} for point in curve)
    onset_curve = tuple(
        {"timeSeconds": point["timeSeconds"], "value": 1.0 if point["timeSeconds"] >= 5.0 else 0.1}
        for point in curve
    )
    return EnergyFeatures(
        global_energy=sum(values) / len(values),
        curve=curve,
        bass_energy_curve=bass_curve,
        onset_density_curve=onset_curve,
        warnings=(),
        frame_length=2048,
        hop_length=512,
        curve_point_count=512,
        bass_cutoff_hz=180.0,
    )


def _tempo_features(*, confidence: float) -> TempoFeatures:
    beats = tuple(
        {"index": index, "timeSeconds": float(index), "confidence": confidence}
        for index in range(9)
    )
    return TempoFeatures(
        bpm=140.0,
        normalized_bpm=140.0,
        confidence=confidence,
        tempo_class="straight",
        candidates=({"bpm": 140.0, "confidence": confidence, "backend": "test"},),
        beats=beats,
        downbeats=(),
        beat_grid_confidence=confidence,
        warnings=(),
        backend="test",
        hop_length=512,
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
        duration_seconds=8.0,
        sample_rate=22_050,
        channels=1,
        provider_metadata={},
    )


def _probe() -> AudioProbe:
    return AudioProbe(
        duration_seconds=8.0,
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
