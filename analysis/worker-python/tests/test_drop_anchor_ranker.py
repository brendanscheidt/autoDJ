import json
from pathlib import Path

from autodj_analysis.drop_anchor_ranker import DropAnchorRankerOptions, rank_drop_anchors
from autodj_analysis.evaluation.drop_anchor_benchmark import run_drop_anchor_benchmark


def _analyzed_artifact(*, track_id: str = "drop-track", source_uri: str = "Drop Track.mp3") -> dict:
    beats = [{"index": index, "timeSeconds": index * 0.5} for index in range(160)]
    curve = []
    bass = []
    onset = []
    for index in range(80):
        seconds = index * 1.0
        is_drop = 32.0 <= seconds < 48.0
        curve.append({"timeSeconds": seconds, "value": 0.82 if is_drop else (0.38 if seconds >= 24.0 else 0.18)})
        bass.append({"timeSeconds": seconds, "value": 0.78 if is_drop else (0.30 if seconds >= 24.0 else 0.12)})
        onset.append({"timeSeconds": seconds, "value": 0.95 if abs(seconds - 32.0) < 0.1 else 0.12})
    return {
        "schemaVersion": "1.0.0",
        "trackId": track_id,
        "durationSeconds": 80.0,
        "source": {"sourceUri": source_uri},
        "beatGrid": {"beats": beats, "confidence": 1.0},
        "energy": {
            "curve": curve,
            "bassEnergyCurve": bass,
            "onsetDensityCurve": onset,
        },
        "sections": [],
        "cuePoints": [],
    }


def _half_bar_drop_artifact() -> dict:
    artifact = _analyzed_artifact()
    for point in artifact["energy"]["curve"]:
        seconds = point["timeSeconds"]
        point["value"] = 0.84 if 33.0 <= seconds < 49.0 else (0.38 if seconds >= 25.0 else 0.18)
    for point in artifact["energy"]["bassEnergyCurve"]:
        seconds = point["timeSeconds"]
        point["value"] = 0.80 if 33.0 <= seconds < 49.0 else (0.30 if seconds >= 25.0 else 0.12)
    for point in artifact["energy"]["onsetDensityCurve"]:
        seconds = point["timeSeconds"]
        point["value"] = 0.95 if abs(seconds - 33.0) < 0.1 else 0.12
    return artifact


def _rekordbox_xml(path: Path, audio_path: Path) -> None:
    location = "file://localhost/" + str(audio_path).replace("\\", "/").replace(":", "%3A")
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="1">
    <TRACK Name="Drop Track" Location="{location}" AverageBpm="120.00">
      <TEMPO Inizio="0.000" Bpm="120.00" Metro="4/4" Battito="1" />
      <POSITION_MARK Name="drop_1_start" Type="0" Start="32.000" Num="0" Red="255" Green="0" Blue="0" />
    </TRACK>
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )


def test_rank_drop_anchors_prefers_energy_bass_onset_phrase_entry() -> None:
    ranking = rank_drop_anchors(_analyzed_artifact(), options=DropAnchorRankerOptions(max_candidates=5))

    assert ranking["artifact"] == "drop-anchor-ranking"
    assert ranking["candidates"][0]["timeSeconds"] == 32.0
    assert "energy_jump" in ranking["candidates"][0]["reasons"]
    assert "bass_impact" in ranking["candidates"][0]["reasons"]
    assert "strong_transient" in ranking["candidates"][0]["reasons"]


def test_rank_drop_anchors_allows_half_bar_drop_when_audio_evidence_is_strong() -> None:
    ranking = rank_drop_anchors(_half_bar_drop_artifact(), options=DropAnchorRankerOptions(max_candidates=5))

    assert ranking["candidates"][0]["timeSeconds"] == 33.0
    assert ranking["candidates"][0]["barBeat"] == "17.3"


def test_drop_anchor_benchmark_matches_rekordbox_drop_start(tmp_path: Path) -> None:
    audio_path = tmp_path / "Drop Track.mp3"
    audio_path.write_bytes(b"not used")
    xml_path = tmp_path / "rekordbox.xml"
    _rekordbox_xml(xml_path, audio_path)

    analysis_root = tmp_path / "analysis"
    track_dir = analysis_root / "tracks" / "drop-track"
    track_dir.mkdir(parents=True)
    (track_dir / "analyzed-track.json").write_text(json.dumps(_analyzed_artifact()), encoding="utf-8")

    summary = run_drop_anchor_benchmark(
        xml_path,
        analysis_root,
        tmp_path / "benchmark",
        top_k=3,
        match_tolerance_seconds=0.20,
    )

    assert summary["summary"]["referenceDropCount"] == 1
    assert summary["summary"]["top1HitCount"] == 1
    assert summary["summary"]["top3HitCount"] == 1
    assert summary["summary"]["nearestBeatUpperBoundHitCount"] == 1
    assert summary["summary"]["nearestBeatUpperBoundRecall"] == 1.0
