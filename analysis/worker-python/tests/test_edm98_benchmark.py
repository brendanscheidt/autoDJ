from autodj_analysis.edm98 import edm98_segments_to_drop_candidates


def test_edm98_segments_to_drop_candidates_prefers_drop_starts() -> None:
    segments = [
        {"label": "intro", "start": 0.0, "end": 16.0},
        {"label": "buildup", "start": 16.0, "end": 32.0},
        {"label": "drop", "start": 32.0, "end": 64.0},
    ]

    candidates = edm98_segments_to_drop_candidates(segments)

    assert candidates[0]["timeSeconds"] == 32.0
    assert candidates[0]["score"] == 1.0
    assert candidates[0]["reason"] == "edmformer_drop_start"
    assert len(candidates) == 1


def test_edm98_segments_to_drop_candidates_uses_buildup_end_fallback() -> None:
    segments = [
        {"label": "intro", "start": 0.0, "end": 16.0},
        {"label": "buildup", "start": 16.0, "end": 32.0},
        {"label": "breakdown", "start": 32.0, "end": 48.0},
    ]

    candidates = edm98_segments_to_drop_candidates(segments)

    assert candidates == [
        {
            "timeSeconds": 32.0,
            "score": 0.72,
            "sourceLabel": "buildup",
            "sourceSegmentIndex": 1,
            "reason": "edmformer_buildup_end",
            "rank": 1,
        }
    ]


def test_edm98_segments_to_drop_candidates_collapses_contiguous_drop_blocks() -> None:
    segments = [
        {"label": "buildup", "start": 0.0, "end": 16.0},
        {"label": "drop", "start": 16.0, "end": 32.0},
        {"label": "drop", "start": 32.0, "end": 48.0},
        {"label": "breakdown", "start": 48.0, "end": 64.0},
        {"label": "drop", "start": 64.0, "end": 80.0},
    ]

    candidates = edm98_segments_to_drop_candidates(segments)

    assert [candidate["timeSeconds"] for candidate in candidates] == [16.0, 64.0]
