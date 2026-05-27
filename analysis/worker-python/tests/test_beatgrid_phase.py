import importlib.util
import math
from pathlib import Path

import pytest

from autodj_analysis import DecodedAudio
from autodj_analysis.beatgrid_phase import (
    BeatgridPhaseOptions,
    PhaseAnchorInput,
    refine_beatgrid_phase,
)


def _skip_without_dependencies() -> None:
    missing = [
        module
        for module in ["numpy", "scipy"]
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        pytest.skip("beatgrid phase dependencies are not installed: " + ", ".join(missing))


def _synthetic_drop_audio() -> DecodedAudio:
    _skip_without_dependencies()
    import numpy

    sample_rate = 44_100
    duration = 5.0
    samples = numpy.zeros(round(sample_rate * duration), dtype=numpy.float32)
    time = numpy.arange(samples.size, dtype=numpy.float32) / sample_rate
    before = time < 2.0
    after = time >= 2.0
    samples[before] = 0.04 * numpy.sin(2.0 * math.pi * 220.0 * time[before])
    samples[after] = (
        0.45 * numpy.sin(2.0 * math.pi * 55.0 * time[after])
        + 0.14 * numpy.sin(2.0 * math.pi * 880.0 * time[after])
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


def _artifact_with_late_grid() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "trackId": "synthetic-drop",
        "durationSeconds": 5.0,
        "beatGrid": {
            "confidence": 0.95,
            "beats": [
                {"index": index, "timeSeconds": round(0.020 + index * 0.5, 6), "confidence": 0.95}
                for index in range(10)
            ],
            "downbeats": [],
        },
        "cuePoints": [
            {
                "id": "cue-drop-001",
                "type": "drop",
                "timeSeconds": 2.0,
                "confidence": 1.0,
                "beatIndex": 4,
                "name": "drop_1_start",
            }
        ],
        "sections": [],
    }


@pytest.mark.analysis
def test_refine_beatgrid_phase_shifts_whole_grid_from_drop_wall() -> None:
    refined, report = refine_beatgrid_phase(
        _artifact_with_late_grid(),
        _synthetic_drop_audio(),
        anchors=(PhaseAnchorInput(label="drop_1_start", time_seconds=2.0),),
        options=BeatgridPhaseOptions(search_window_seconds=0.2),
    )

    assert report["applied"] is True
    selected_wall = report["anchors"][0]["selectedWallTimeSeconds"]
    assert report["phaseShiftMilliseconds"] == pytest.approx((selected_wall - 2.02) * 1000.0, abs=0.001)
    assert report["anchors"][0]["riskProfile"]["dropSwitchSafe"] is True
    assert report["transitionRecommendations"]["dropSwitchSafe"] is True
    assert "drop_switch" in report["transitionRecommendations"]["allowedTransitionFamilies"]
    assert refined["beatGrid"]["beats"][4]["timeSeconds"] == pytest.approx(selected_wall, abs=0.001)
    assert refined["beatGrid"]["phaseRefinement"]["applied"] is True
    assert refined["beatGrid"]["phaseRefinement"]["transitionRecommendations"]["dropSwitchSafe"] is True


@pytest.mark.analysis
def test_refine_beatgrid_phase_rejects_low_score_anchor() -> None:
    refined, report = refine_beatgrid_phase(
        _artifact_with_late_grid(),
        _synthetic_drop_audio(),
        anchors=(PhaseAnchorInput(label="drop_1_start", time_seconds=2.0),),
        options=BeatgridPhaseOptions(search_window_seconds=0.2, min_wall_score=1.1),
    )

    assert report["applied"] is False
    assert report["warnings"]
    assert report["transitionRecommendations"]["verdict"] == "reject_precision"
    assert report["transitionRecommendations"]["allowedTransitionFamilies"] == ["simple_handoff"]
    assert refined["beatGrid"]["beats"][4]["timeSeconds"] == 2.02
