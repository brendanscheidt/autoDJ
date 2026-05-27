from __future__ import annotations

import json
from pathlib import Path

from autodj_analysis import (
    apply_rekordbox_overrides,
    apply_rekordbox_semantic_overrides,
    apply_rekordbox_semantic_xml_file,
    apply_rekordbox_xml_file,
    build_rekordbox_xml_from_analyzed_track,
    export_analyzed_track_to_rekordbox_xml_file,
    load_rekordbox_track,
    parse_semantic_cue_label,
)


def test_load_rekordbox_track_parses_tempo_and_position_marks(tmp_path: Path) -> None:
    xml_path = _write_rekordbox_xml(tmp_path)

    track = load_rekordbox_track(xml_path)

    assert track.name == "Example Track"
    assert track.average_bpm == 150.0
    assert track.tonality == "9A"
    assert track.tempos[0].start_seconds == 0.098
    assert track.tempos[0].bpm == 150.0
    assert [cue.start_seconds for cue in track.cues] == [51.298, 76.898, 128.098, 179.298]
    assert [cue.num for cue in track.cues] == [0, 1, 2, 3]


def test_apply_rekordbox_overrides_replaces_tempo_grid_sections_and_cues(tmp_path: Path) -> None:
    track = load_rekordbox_track(_write_rekordbox_xml(tmp_path))
    analyzed = _analyzed_artifact()
    analyzed["key"] = {"tonic": "unknown", "mode": "unknown", "confidence": 0.0, "candidates": []}

    artifact = apply_rekordbox_overrides(analyzed, track)

    assert artifact["tempo"]["bpm"] == 150.0
    assert artifact["tempo"]["normalizedBpm"] == 150.0
    assert artifact["tempo"]["confidence"] == 1.0
    assert artifact["tempo"]["candidates"][0]["backend"] == "rekordbox.xml"
    assert artifact["beatGrid"]["confidence"] == 1.0
    assert artifact["beatGrid"]["beats"][0] == {
        "index": 0,
        "timeSeconds": 0.098,
        "confidence": 1.0,
    }
    assert artifact["beatGrid"]["beats"][128]["timeSeconds"] == 51.298
    assert artifact["sections"] == [
        {
            "id": "section-rekordbox-drop-001",
            "type": "drop",
            "startSeconds": 51.298,
            "endSeconds": 76.898,
            "confidence": 1.0,
            "startBeatIndex": 128,
            "endBeatIndex": 192,
            "source": "rekordbox.xml",
        },
        {
            "id": "section-rekordbox-drop-002",
            "type": "drop",
            "startSeconds": 128.098,
            "endSeconds": 179.298,
            "confidence": 1.0,
            "startBeatIndex": 320,
            "endBeatIndex": 448,
            "source": "rekordbox.xml",
        },
    ]
    assert [cue["type"] for cue in artifact["cuePoints"]] == ["drop", "mix_out", "drop", "mix_out"]
    assert [cue["beatIndex"] for cue in artifact["cuePoints"]] == [128, 192, 320, 448]
    assert artifact["cuePoints"][0]["tags"] == ["rekordbox_xml", "hot_cue_A"]
    assert artifact["key"] == analyzed["key"]
    assert artifact["quality"]["overallConfidence"] == 0.95
    assert "Rekordbox XML" in artifact["quality"]["warnings"][0]


def test_apply_rekordbox_xml_file_writes_overridden_artifact(tmp_path: Path) -> None:
    analyzed_path = tmp_path / "analyzed-track.json"
    analyzed_path.write_text(json.dumps(_analyzed_artifact()), encoding="utf-8")
    output_path = tmp_path / "overridden.json"

    written_path = apply_rekordbox_xml_file(analyzed_path, _write_rekordbox_xml(tmp_path), output_path)

    payload = json.loads(written_path.read_text(encoding="utf-8"))
    assert written_path == output_path
    assert payload["tempo"]["bpm"] == 150.0
    assert payload["cuePoints"][2]["timeSeconds"] == 128.098


def test_apply_rekordbox_semantic_overrides_preserves_autodj_tempo_grid_and_key(tmp_path: Path) -> None:
    track = load_rekordbox_track(_write_named_rekordbox_xml(tmp_path))
    analyzed = _analyzed_artifact()
    analyzed["key"] = {"camelot": "7A", "confidence": 0.91}
    analyzed["beatGrid"] = {
        "beats": [
            {"index": 41, "timeSeconds": 32.0, "confidence": 0.9},
            {"index": 77, "timeSeconds": 48.1, "confidence": 0.9},
            {"index": 145, "timeSeconds": 80.0, "confidence": 0.9},
        ],
        "downbeats": [],
        "confidence": 0.73,
    }

    artifact = apply_rekordbox_semantic_overrides(analyzed, track)

    assert artifact["tempo"] == analyzed["tempo"]
    assert artifact["beatGrid"] == analyzed["beatGrid"]
    assert artifact["key"] == analyzed["key"]
    assert [section["type"] for section in artifact["sections"]] == ["intro", "build", "drop", "break"]
    assert artifact["sections"][2]["startBeatIndex"] == 77
    assert artifact["cuePoints"][2]["beatIndex"] == 77
    assert "rekordboxSemanticXml" in artifact["source"]["providerMetadata"]
    assert "rekordboxXml" not in artifact["source"]["providerMetadata"]


def test_apply_rekordbox_semantic_xml_file_writes_semantic_only_artifact(tmp_path: Path) -> None:
    analyzed_path = tmp_path / "analyzed-track.json"
    analyzed = _analyzed_artifact()
    analyzed["beatGrid"] = {
        "beats": [{"index": 77, "timeSeconds": 48.1, "confidence": 0.9}],
        "downbeats": [],
        "confidence": 0.73,
    }
    analyzed_path.write_text(json.dumps(analyzed), encoding="utf-8")
    output_path = tmp_path / "semantic-overridden.json"

    written_path = apply_rekordbox_semantic_xml_file(
        analyzed_path,
        _write_named_rekordbox_xml(tmp_path),
        output_path,
    )

    payload = json.loads(written_path.read_text(encoding="utf-8"))
    assert written_path == output_path
    assert payload["tempo"]["candidates"][0]["backend"] == "test"
    assert payload["cuePoints"][2]["timeSeconds"] == 48.098
    assert payload["cuePoints"][2]["beatIndex"] == 77


def test_parse_semantic_cue_label_supports_named_boundaries() -> None:
    parsed = parse_semantic_cue_label("drop_2_start", provider_name="rekordbox")

    assert parsed is not None
    assert parsed.section_type == "drop"
    assert parsed.ordinal == 2
    assert parsed.boundary == "start"


def test_apply_rekordbox_overrides_uses_named_semantic_cues_when_present(tmp_path: Path) -> None:
    track = load_rekordbox_track(_write_named_rekordbox_xml(tmp_path))

    artifact = apply_rekordbox_overrides(_analyzed_artifact(), track)

    assert [section["type"] for section in artifact["sections"]] == ["intro", "build", "drop", "break"]
    assert artifact["sections"][1]["startSeconds"] == 32.098
    assert artifact["sections"][1]["endSeconds"] == 48.098
    assert artifact["sections"][2]["id"] == "section-rekordbox.xml-drop-001"
    assert artifact["sections"][2]["sourceCueName"] == "drop_1_start"
    assert [cue["type"] for cue in artifact["cuePoints"]] == ["intro", "build", "drop", "mix_out", "break"]
    assert artifact["cuePoints"][2]["sourceCueName"] == "drop_1_start"


def test_build_rekordbox_xml_from_analyzed_track_exports_grid_and_sections(tmp_path: Path) -> None:
    artifact = _analyzed_artifact()
    artifact["title"] = "AutoDJ Export Track"
    artifact["beatGrid"]["beats"] = [{"index": 0, "timeSeconds": 0.029, "confidence": 0.98}]
    artifact["sections"] = [
        {
            "id": "section-build-001",
            "type": "build",
            "startSeconds": 48.0,
            "endSeconds": 61.714,
            "confidence": 0.8,
        },
        {
            "id": "section-drop-001",
            "type": "drop",
            "startSeconds": 61.714,
            "endSeconds": 85.714,
            "confidence": 0.9,
        },
    ]
    xml_text = build_rekordbox_xml_from_analyzed_track(
        artifact,
        source_uri="C:\\Music\\AutoDJ Export Track.mp3",
    )
    xml_path = tmp_path / "autodj-rekordbox.xml"
    xml_path.write_text(xml_text, encoding="utf-8")

    track = load_rekordbox_track(xml_path)

    assert track.name == "AutoDJ Export Track"
    assert track.average_bpm == 150.0
    assert track.location == "file://localhost/C:/Music/AutoDJ%20Export%20Track.mp3"
    assert track.tempos[0].start_seconds == 0.029
    assert track.tempos[0].bpm == 150.0
    assert [cue.name for cue in track.cues] == [
        "build_1_start",
        "build_1_end",
        "drop_1_start",
        "drop_1_end",
    ]


def test_build_rekordbox_xml_caps_transition_hot_cues_to_important_eight(tmp_path: Path) -> None:
    artifact = _analyzed_artifact()
    artifact["sections"] = [
        {"id": "intro", "type": "intro", "startSeconds": 0.0, "endSeconds": 16.0},
        {"id": "build-1", "type": "build", "startSeconds": 16.0, "endSeconds": 32.0},
        {"id": "drop-1", "type": "drop", "startSeconds": 32.0, "endSeconds": 64.0},
        {"id": "build-2", "type": "build", "startSeconds": 96.0, "endSeconds": 112.0},
        {"id": "drop-2", "type": "drop", "startSeconds": 112.0, "endSeconds": 144.0},
        {"id": "build-3", "type": "build", "startSeconds": 176.0, "endSeconds": 192.0},
        {"id": "drop-3", "type": "drop", "startSeconds": 192.0, "endSeconds": 224.0},
        {"id": "outro", "type": "outro", "startSeconds": 224.0, "endSeconds": 240.0},
    ]
    xml_path = tmp_path / "transition-8.xml"
    xml_path.write_text(
        build_rekordbox_xml_from_analyzed_track(artifact, source_uri="C:/Music/test.mp3"),
        encoding="utf-8",
    )

    track = load_rekordbox_track(xml_path)

    assert len(track.cues) == 8
    assert [cue.name for cue in track.cues] == [
        "build_1_start",
        "drop_1_start",
        "drop_1_end",
        "build_2_start",
        "drop_2_start",
        "drop_2_end",
        "build_3_start",
        "drop_3_start",
    ]


def test_export_analyzed_track_to_rekordbox_xml_file_writes_xml(tmp_path: Path) -> None:
    artifact = _analyzed_artifact()
    artifact["beatGrid"]["beats"] = [{"index": 0, "timeSeconds": 0.1, "confidence": 1.0}]
    artifact["sections"] = [{"id": "section-intro-001", "type": "intro", "startSeconds": 0.1, "endSeconds": 16.1}]
    analyzed_path = tmp_path / "analyzed-track.json"
    analyzed_path.write_text(json.dumps(artifact), encoding="utf-8")

    output_path = export_analyzed_track_to_rekordbox_xml_file(
        analyzed_path,
        tmp_path / "rekordbox-export.xml",
        source_uri="/mnt/c/Music/test.mp3",
        track_name="Exported From File",
    )

    assert output_path.exists()
    track = load_rekordbox_track(output_path)
    assert track.name == "Exported From File"
    assert track.location == "file://localhost/C:/Music/test.mp3"
    assert track.cues[0].name == "intro_1_start"


def _write_rekordbox_xml(tmp_path: Path) -> Path:
    xml_path = tmp_path / "rekordbox.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="1">
    <TRACK Name="Example Track" AverageBpm="150.00" Tonality="9A" Location="file://localhost/example.mp3">
      <TEMPO Inizio="0.098" Bpm="150.00" Metro="4/4" Battito="1"/>
      <POSITION_MARK Name="" Type="0" Start="51.298" Num="0" Red="255" Green="55" Blue="111"/>
      <POSITION_MARK Name="" Type="0" Start="76.898" Num="1" Red="69" Green="172" Blue="219"/>
      <POSITION_MARK Name="" Type="0" Start="128.098" Num="2" Red="125" Green="193" Blue="61"/>
      <POSITION_MARK Name="" Type="0" Start="179.298" Num="3" Red="170" Green="114" Blue="255"/>
    </TRACK>
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )
    return xml_path


def _write_named_rekordbox_xml(tmp_path: Path) -> Path:
    xml_path = tmp_path / "rekordbox-named.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="1">
    <TRACK Name="Example Track" AverageBpm="150.00" Tonality="9A" Location="file://localhost/example.mp3">
      <TEMPO Inizio="0.098" Bpm="150.00" Metro="4/4" Battito="1"/>
      <POSITION_MARK Name="intro_1_start" Type="0" Start="0.098" Num="0" Red="90" Green="160" Blue="255"/>
      <POSITION_MARK Name="build_1_start" Type="0" Start="32.098" Num="1" Red="255" Green="194" Blue="66"/>
      <POSITION_MARK Name="drop_1_start" Type="0" Start="48.098" Num="2" Red="255" Green="55" Blue="111"/>
      <POSITION_MARK Name="drop_1_end" Type="0" Start="80.098" Num="3" Red="178" Green="38" Blue="78"/>
      <POSITION_MARK Name="break_1_start" Type="0" Start="80.098" Num="4" Red="125" Green="193" Blue="61"/>
    </TRACK>
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )
    return xml_path


def _analyzed_artifact() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "trackId": "headache",
        "source": {"providerMetadata": {}},
        "analyzer": {},
        "durationSeconds": 185.913469,
        "tempo": {
            "bpm": 150.0,
            "normalizedBpm": 150.0,
            "confidence": 0.93,
            "tempoClass": "straight",
            "candidates": [{"bpm": 150.0, "confidence": 0.93, "backend": "test"}],
        },
        "beatGrid": {"beats": [], "downbeats": [], "confidence": 0.0},
        "sections": [],
        "cuePoints": [],
        "quality": {"overallConfidence": 0.8, "warnings": []},
    }
