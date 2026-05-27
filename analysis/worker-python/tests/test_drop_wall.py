import importlib.util
import json
import math
from pathlib import Path

import pytest

from autodj_analysis import DecodedAudio
from autodj_analysis.drop_wall import DropWallOptions, detect_drop_wall, drop_wall_svg, write_drop_wall_svg


def _skip_without_drop_wall_dependencies() -> None:
    missing = [
        module
        for module in ["numpy", "scipy"]
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        pytest.skip("drop-wall dependencies are not installed: " + ", ".join(missing))


def _synthetic_drop_audio() -> DecodedAudio:
    _skip_without_drop_wall_dependencies()
    import numpy

    sample_rate = 44_100
    duration = 4.0
    samples = numpy.zeros(round(sample_rate * duration), dtype=numpy.float32)
    time = numpy.arange(samples.size, dtype=numpy.float32) / sample_rate
    before = time < 2.0
    after = time >= 2.0
    samples[before] = 0.08 * numpy.sin(2.0 * math.pi * 220.0 * time[before])
    samples[after] = (
        0.50 * numpy.sin(2.0 * math.pi * 55.0 * time[after])
        + 0.18 * numpy.sin(2.0 * math.pi * 880.0 * time[after])
    )
    impulse_start = round(2.0 * sample_rate)
    samples[impulse_start : impulse_start + 128] += numpy.hanning(128).astype(numpy.float32) * 0.9
    return DecodedAudio(
        samples=samples,
        sample_rate=sample_rate,
        duration_seconds=duration,
        channels=1,
        source_path=Path("synthetic-drop.wav"),
    )


@pytest.mark.analysis
def test_detect_drop_wall_selects_energy_wall_near_approximate_time() -> None:
    artifact = detect_drop_wall(
        _synthetic_drop_audio(),
        approximate_time_seconds=2.012,
        track_id="synthetic-drop",
        options=DropWallOptions(search_window_seconds=0.25, max_candidates=5),
    )

    assert artifact["artifact"] == "drop-wall-debug"
    assert artifact["selectedWall"]["selected"] is True
    assert abs(artifact["selectedWall"]["timeSeconds"] - 2.0) < 0.01
    assert artifact["selectedWall"]["score"] > 0.45
    assert artifact["riskProfile"]["verdict"] in {"strong", "usable"}
    assert "drop_switch" in artifact["riskProfile"]["allowedTransitionFamilies"]
    assert artifact["candidates"][0]["selected"] is True
    assert artifact["envelopes"]


@pytest.mark.analysis
def test_drop_wall_svg_contains_selected_marker(tmp_path: Path) -> None:
    artifact = detect_drop_wall(
        _synthetic_drop_audio(),
        approximate_time_seconds=2.0,
        track_id="synthetic-drop",
        options=DropWallOptions(search_window_seconds=0.2, max_candidates=3),
    )
    svg = drop_wall_svg(artifact)
    output_path = write_drop_wall_svg(tmp_path / "drop-wall.svg", artifact)

    assert "selected wall" in svg
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8").startswith("<svg")


@pytest.mark.analysis
def test_drop_wall_artifact_is_json_serializable() -> None:
    artifact = detect_drop_wall(
        _synthetic_drop_audio(),
        approximate_time_seconds=2.0,
        track_id="synthetic-drop",
        options=DropWallOptions(search_window_seconds=0.2, max_candidates=3),
    )

    assert json.loads(json.dumps(artifact))["trackId"] == "synthetic-drop"
