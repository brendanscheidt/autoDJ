from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from audio_fixtures import create_energy_ramp_fixture
from autodj_analysis import (
    ANALYZER_VERSION,
    DEBUG_WAVEFORM_MODE_RGB_BANDS,
    DEFAULT_DEBUG_WAVEFORM_POINT_COUNT,
    DebugWaveformError,
    build_debug_waveform_artifact,
    compute_debug_waveform,
    load_audio,
    write_debug_waveform_artifact,
)


@pytest.mark.analysis
def test_debug_waveform_builds_rgb_band_points_for_generated_audio(tmp_path: Path) -> None:
    _skip_without_debug_dependencies()
    fixture = create_energy_ramp_fixture(tmp_path, duration_seconds=2.0)
    decoded = load_audio(fixture.path)

    waveform = compute_debug_waveform(decoded, target_point_count=64)

    assert len(waveform.points) == 64
    assert len(waveform.points) <= DEFAULT_DEBUG_WAVEFORM_POINT_COUNT
    assert waveform.sample_rate == 22_050
    assert waveform.duration_seconds == pytest.approx(fixture.duration_seconds)
    assert waveform.peak > 0
    assert waveform.rms > 0
    assert all(0.0 <= point["low"] <= 1.0 for point in waveform.points)
    assert all(0.0 <= point["mid"] <= 1.0 for point in waveform.points)
    assert all(0.0 <= point["high"] <= 1.0 for point in waveform.points)
    assert max(point["transient"] for point in waveform.points) <= 1.0


@pytest.mark.analysis
def test_build_debug_waveform_artifact_has_viewer_shape(tmp_path: Path) -> None:
    _skip_without_debug_dependencies()
    fixture = create_energy_ramp_fixture(tmp_path, duration_seconds=1.0)
    decoded = load_audio(fixture.path)

    artifact = build_debug_waveform_artifact(
        "debug-track",
        decoded,
        analyzer_version=ANALYZER_VERSION,
        created_at_utc="2026-05-17T00:00:00Z",
        target_point_count=32,
    )

    assert artifact["schemaVersion"] == "1.0.0"
    assert artifact["artifactType"] == "debug-waveform"
    assert artifact["trackId"] == "debug-track"
    assert artifact["analyzer"]["producer"] == "autodj_analysis.debug_waveform"
    assert artifact["analyzer"]["producerVersion"] == ANALYZER_VERSION
    assert artifact["analyzer"]["createdAtUtc"] == "2026-05-17T00:00:00Z"
    assert artifact["parameters"]["mode"] == DEBUG_WAVEFORM_MODE_RGB_BANDS
    assert artifact["parameters"]["targetPointCount"] == 32
    assert len(artifact["points"]) == 32
    assert {"timeSeconds", "min", "max", "rms", "low", "mid", "high", "transient"} <= set(
        artifact["points"][0]
    )


@pytest.mark.analysis
def test_write_debug_waveform_artifact_writes_explicit_json_path(tmp_path: Path) -> None:
    _skip_without_debug_dependencies()
    fixture = create_energy_ramp_fixture(tmp_path, duration_seconds=1.0)
    decoded = load_audio(fixture.path)
    artifact = build_debug_waveform_artifact(
        "debug-track",
        decoded,
        analyzer_version=ANALYZER_VERSION,
        target_point_count=8,
    )
    destination = tmp_path / "debug-waveform.json"

    written_path = write_debug_waveform_artifact(destination, artifact)

    assert written_path == destination
    assert json.loads(destination.read_text(encoding="utf-8"))["artifactType"] == "debug-waveform"


def test_debug_waveform_reports_expected_input_errors() -> None:
    _skip_without_debug_dependencies()
    fixture = _decoded([0.1, -0.1, 0.2, -0.2], sample_rate=8_000)

    with pytest.raises(DebugWaveformError) as bad_points:
        compute_debug_waveform(fixture, target_point_count=0)
    with pytest.raises(DebugWaveformError) as bad_low:
        compute_debug_waveform(fixture, low_cutoff_hz=0)
    with pytest.raises(DebugWaveformError) as bad_high:
        compute_debug_waveform(fixture, low_cutoff_hz=2_000, high_cutoff_hz=1_000)
    with pytest.raises(DebugWaveformError) as empty:
        compute_debug_waveform(_decoded([]))

    assert bad_points.value.code == "debug_waveform_invalid_parameters"
    assert bad_low.value.code == "debug_waveform_invalid_parameters"
    assert bad_high.value.code == "debug_waveform_invalid_parameters"
    assert empty.value.code == "debug_waveform_empty_audio"


def _decoded(samples: list[float], *, sample_rate: int = 8_000):
    from autodj_analysis import DecodedAudio

    return DecodedAudio(
        samples=samples,
        sample_rate=sample_rate,
        duration_seconds=0.0 if sample_rate <= 0 else len(samples) / sample_rate,
        channels=1,
        source_path=Path("synthetic.wav"),
    )


def _skip_without_debug_dependencies() -> None:
    missing = [
        module
        for module in ["numpy", "scipy", "soundfile"]
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        pytest.skip(
            "debug waveform dependencies are not installed; missing "
            + ", ".join(missing)
            + ". Install the worker with `[analysis]`."
        )
