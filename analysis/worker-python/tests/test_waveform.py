from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

from audio_fixtures import create_energy_ramp_fixture
from autodj_analysis import (
    ANALYZER_VERSION,
    DEFAULT_WAVEFORM_POINT_COUNT,
    WAVEFORM_MODE_PEAK_RMS,
    DecodedAudio,
    WaveformError,
    build_waveform_artifact,
    compute_waveform_overview,
    load_audio,
    waveform_path,
    write_waveform_artifact,
)


def test_compute_waveform_overview_builds_stable_peak_rms_points() -> None:
    decoded = _decoded([-0.5, 0.25, 0.75, -0.25, 0.0, 1.0, -1.0, 0.5], sample_rate=4)

    overview = compute_waveform_overview(decoded, target_point_count=4)
    repeat = compute_waveform_overview(decoded, target_point_count=4)

    assert overview == repeat
    assert overview.sample_rate == 4
    assert overview.duration_seconds == 2.0
    assert overview.peak == 1.0
    assert overview.rms == pytest.approx(math.sqrt(3.1875 / 8.0), abs=1e-6)
    assert overview.points == (
        {"timeSeconds": 0.0, "min": -0.5, "max": 0.25, "rms": 0.395285},
        {"timeSeconds": 0.5, "min": -0.25, "max": 0.75, "rms": 0.559017},
        {"timeSeconds": 1.0, "min": 0.0, "max": 1.0, "rms": 0.707107},
        {"timeSeconds": 1.5, "min": -1.0, "max": 0.5, "rms": 0.790569},
    )


def test_compute_waveform_overview_bounds_point_count_to_target() -> None:
    samples = [0.1, -0.1] * 20 + [0.8, -0.8] * 20
    overview = compute_waveform_overview(_decoded(samples, sample_rate=20), target_point_count=8)

    assert len(overview.points) == 8
    assert len(overview.points) <= DEFAULT_WAVEFORM_POINT_COUNT
    assert overview.points[-1]["rms"] > overview.points[0]["rms"]
    assert overview.points[-1]["max"] > overview.points[0]["max"]


def test_build_waveform_artifact_has_plain_cache_shape() -> None:
    artifact = build_waveform_artifact(
        "track-drop-001",
        _decoded([-0.25, 0.25, -0.75, 0.75], sample_rate=2),
        analyzer_producer="autodj_analysis.signal",
        analyzer_version=ANALYZER_VERSION,
        source_content_hash="sha256:source-a",
        parameters_hash="sha256:params-a",
        created_at_utc="2026-05-16T00:00:00Z",
        target_point_count=2,
    )

    assert artifact["schemaVersion"] == "1.0.0"
    assert artifact["trackId"] == "track-drop-001"
    assert artifact["analyzer"] == {
        "producer": "autodj_analysis.signal",
        "producerVersion": ANALYZER_VERSION,
        "createdAtUtc": "2026-05-16T00:00:00Z",
        "sourceContentHash": "sha256:source-a",
        "parametersHash": "sha256:params-a",
    }
    assert artifact["durationSeconds"] == 2.0
    assert artifact["sampleRate"] == 2
    assert artifact["parameters"] == {
        "targetPointCount": 2,
        "mode": WAVEFORM_MODE_PEAK_RMS,
    }
    assert artifact["summary"] == {"peak": 0.75, "rms": 0.559017}
    assert artifact["points"] == [
        {"timeSeconds": 0.0, "min": -0.25, "max": 0.25, "rms": 0.25},
        {"timeSeconds": 1.0, "min": -0.75, "max": 0.75, "rms": 0.75},
    ]


def test_write_waveform_artifact_writes_to_track_cache_atomically(tmp_path: Path) -> None:
    artifact = build_waveform_artifact(
        "track-drop-001",
        _decoded([-0.5, 0.5]),
        analyzer_producer="autodj_analysis.signal",
        analyzer_version=ANALYZER_VERSION,
        source_content_hash="sha256:source-a",
        parameters_hash="sha256:params-a",
        created_at_utc="2026-05-16T00:00:00Z",
        target_point_count=1,
    )

    written_path = write_waveform_artifact(tmp_path, "track-drop-001", artifact)

    assert written_path == waveform_path(tmp_path, "track-drop-001")
    assert json.loads(written_path.read_text(encoding="utf-8"))["trackId"] == "track-drop-001"
    assert not list(written_path.parent.glob("*.tmp"))
    assert not (written_path.parent / "analyzed-track.json").exists()


def test_waveform_helpers_report_expected_input_errors() -> None:
    with pytest.raises(WaveformError) as bad_target:
        compute_waveform_overview(_decoded([0.1]), target_point_count=0)
    with pytest.raises(WaveformError) as bad_mode:
        compute_waveform_overview(_decoded([0.1]), mode="unknown")
    with pytest.raises(WaveformError) as bad_audio:
        compute_waveform_overview(_decoded([0.1], sample_rate=0))
    with pytest.raises(WaveformError) as empty_audio:
        compute_waveform_overview(_decoded([]))
    with pytest.raises(WaveformError) as missing_hash:
        build_waveform_artifact(
            "track-drop-001",
            _decoded([0.1]),
            analyzer_producer="autodj_analysis.signal",
            analyzer_version=ANALYZER_VERSION,
            source_content_hash="",
            parameters_hash="sha256:params-a",
        )

    assert bad_target.value.code == "waveform_invalid_parameters"
    assert bad_mode.value.code == "waveform_invalid_parameters"
    assert bad_audio.value.code == "waveform_invalid_audio"
    assert empty_audio.value.code == "waveform_empty_audio"
    assert missing_hash.value.code == "waveform_source_content_hash_missing"


@pytest.mark.analysis
def test_waveform_overview_uses_loaded_generated_audio_signal(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_energy_ramp_fixture(tmp_path, duration_seconds=3.0)
    decoded = load_audio(fixture.path)

    overview = compute_waveform_overview(decoded, target_point_count=12)

    assert len(overview.points) == 12
    assert overview.sample_rate == 22_050
    assert overview.duration_seconds == pytest.approx(fixture.duration_seconds)
    assert overview.points[-1]["rms"] > overview.points[0]["rms"]


def _decoded(samples: list[float], *, sample_rate: int = 4) -> DecodedAudio:
    duration_seconds = 0.0 if sample_rate <= 0 else len(samples) / sample_rate
    return DecodedAudio(
        samples=samples,
        sample_rate=sample_rate,
        duration_seconds=duration_seconds,
        channels=1,
        source_path=Path("synthetic.wav"),
    )


def _skip_without_analysis_dependencies() -> None:
    missing = [module for module in ["numpy", "soundfile"] if importlib.util.find_spec(module) is None]
    if missing:
        pytest.skip(
            "analysis dependencies are not installed; missing "
            + ", ".join(missing)
            + ". Install the worker with `[analysis]`."
        )
