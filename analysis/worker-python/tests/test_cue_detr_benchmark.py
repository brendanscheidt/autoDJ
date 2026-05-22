from autodj_analysis.evaluation.cue_detr_benchmark import snap_cue_candidates_to_beat_grid


def test_snap_cue_candidates_to_nearest_beat_grid_keeps_score_order() -> None:
    candidates = [
        {"rank": 1, "timeSeconds": 10.08, "score": 0.8},
        {"rank": 2, "timeSeconds": 19.72, "score": 0.95},
    ]
    beats = ((100, 10.0), (200, 20.0))

    snapped = snap_cue_candidates_to_beat_grid(candidates, beats, snap_window_seconds=0.4)

    assert [candidate["timeSeconds"] for candidate in snapped] == [20.0, 10.0]
    assert [candidate["rank"] for candidate in snapped] == [1, 2]
    assert snapped[0]["sourceTimeSeconds"] == 19.72
    assert snapped[0]["snappedToBeatGrid"] is True
    assert snapped[0]["beatIndex"] == 200


def test_snap_cue_candidates_leaves_far_candidates_unsnapped() -> None:
    candidates = [{"rank": 1, "timeSeconds": 10.8, "score": 0.9}]
    beats = ((100, 10.0),)

    snapped = snap_cue_candidates_to_beat_grid(candidates, beats, snap_window_seconds=0.25)

    assert snapped[0]["timeSeconds"] == 10.8
    assert snapped[0]["snappedToBeatGrid"] is False
    assert snapped[0]["snapErrorMilliseconds"] is None
