from autodj_analysis import classify_stub


def test_classify_stub_returns_dubstep_verdict() -> None:
    verdict = classify_stub("example-track.wav")

    assert verdict["trackId"].startswith("track-example-track-")
    assert verdict["primaryGenre"] == "dubstep"
    assert verdict["confidence"] == 1.0
    assert verdict["allowedForAutoDj"] is True
    assert verdict["candidateGenres"] == [{"genre": "dubstep", "confidence": 1.0}]
