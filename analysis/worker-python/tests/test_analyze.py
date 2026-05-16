import json

from autodj_analysis import analyze_stub, build_analyzed_track_stub


def test_build_analyzed_track_stub_has_expected_top_level_keys() -> None:
    artifact = build_analyzed_track_stub("fixture-track.mp3")

    assert {
        "schemaVersion",
        "trackId",
        "source",
        "analyzer",
        "durationSeconds",
        "tempo",
        "key",
        "beatGrid",
        "sections",
        "energy",
        "vocals",
        "cuePoints",
        "quality",
    }.issubset(artifact.keys())
    assert artifact["schemaVersion"] == "1.0.0"
    assert artifact["tempo"]["normalizedBpm"] == 140.0
    assert artifact["analyzer"]["producer"] == "autodj_analysis.stub"


def test_analyze_stub_writes_analyzed_track_json(tmp_path) -> None:
    output_file = analyze_stub("fixture-track.mp3", tmp_path)

    assert output_file.name == "analyzed-track.json"
    artifact = json.loads(output_file.read_text(encoding="utf-8"))
    assert artifact["trackId"].startswith("track-fixture-track-")
    assert artifact["source"]["sourceUri"] == "fixture-track.mp3"
    assert artifact["quality"]["warnings"]
