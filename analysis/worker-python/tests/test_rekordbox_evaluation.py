from __future__ import annotations

import json
from pathlib import Path

from autodj_analysis import (
    REKORDBOX_EVALUATION_REPORT_TYPE,
    RekordboxEvaluationOptions,
    evaluate_analyzed_artifact_against_rekordbox,
    load_rekordbox_track,
    write_rekordbox_evaluation_report,
)
from autodj_analysis.cli import main


def test_evaluate_analyzed_artifact_reports_tempo_grid_cue_and_section_errors(tmp_path: Path) -> None:
    track = load_rekordbox_track(_write_rekordbox_xml(tmp_path))
    artifact = _analyzed_artifact(beat_offset_seconds=0.005)

    report = evaluate_analyzed_artifact_against_rekordbox(
        artifact,
        track,
        options=RekordboxEvaluationOptions(
            candidate_name="candidate-signal",
            processing_seconds=1.25,
        ),
    )

    assert report["schemaVersion"] == "1.0.0"
    assert report["reportType"] == REKORDBOX_EVALUATION_REPORT_TYPE
    assert report["candidate"]["name"] == "candidate-signal"
    assert report["candidate"]["processingSeconds"] == 1.25
    assert report["reference"]["bpm"] == 150.0
    assert report["reference"]["beatCount"] > 400

    tempo = report["metrics"]["tempo"]
    assert tempo["candidateBpm"] == 150.5
    assert tempo["bpmAbsoluteError"] == 0.5
    assert tempo["normalizedBpmAbsoluteError"] == 0.5

    beat_grid = report["metrics"]["beatGrid"]
    assert beat_grid["candidateBeatCount"] > 400
    assert beat_grid["beatCoverageRatio"] > 0.99
    assert beat_grid["firstBeatOffsetMilliseconds"] == 5.0
    assert beat_grid["medianAbsoluteErrorMilliseconds"] == 5.0
    assert beat_grid["p95AbsoluteErrorMilliseconds"] == 5.0
    assert beat_grid["referenceMedianAbsoluteErrorMilliseconds"] == 5.0
    assert beat_grid["referenceP95AbsoluteErrorMilliseconds"] == 5.0
    assert beat_grid["referenceRecallWithin25Milliseconds"] == 1.0
    assert beat_grid["candidatePrecisionWithin25Milliseconds"] == 1.0
    assert beat_grid["candidateDownbeatCount"] == 1
    assert beat_grid["candidateDownbeats"][0]["rawTimeSeconds"] == 0.103

    drift = report["metrics"]["cueAdjacentDrift"]
    assert drift[0]["cueLabel"] == "A"
    assert drift[0]["cueType"] == "drop"
    assert drift[0]["signedErrorMilliseconds"] == 5.0

    cue_errors = report["metrics"]["cueBoundaryErrors"]
    assert cue_errors[0]["cueLabel"] == "A"
    assert cue_errors[0]["candidateCueId"] == "cue-drop-001"
    assert cue_errors[0]["signedErrorMilliseconds"] == 110.0
    assert cue_errors[1]["signedErrorMilliseconds"] == -100.0

    section_errors = report["metrics"]["sectionBoundaryErrors"]
    assert section_errors[0]["referenceSectionId"] == "section-rekordbox-drop-001"
    assert section_errors[0]["candidateSectionId"] == "section-drop-001"
    assert section_errors[0]["startErrorMilliseconds"] == 100.0
    assert section_errors[0]["endErrorMilliseconds"] == -150.0


def test_timeline_offset_policy_shifts_candidate_times_before_comparison(tmp_path: Path) -> None:
    track = load_rekordbox_track(_write_rekordbox_xml(tmp_path))
    artifact = _analyzed_artifact(
        beat_offset_seconds=0.02,
        cue_offset_seconds=-0.09,
        section_offset_seconds=-0.08,
    )

    report = evaluate_analyzed_artifact_against_rekordbox(
        artifact,
        track,
        options=RekordboxEvaluationOptions(
            timeline_offset_seconds=-0.02,
            timeline_offset_policy="decoded-wav-minus-mp3-delay",
        ),
    )

    assert report["candidate"]["timelineOffsetSeconds"] == -0.02
    assert report["candidate"]["timelineOffsetPolicy"] == "decoded-wav-minus-mp3-delay"
    assert report["metrics"]["beatGrid"]["firstBeatOffsetMilliseconds"] == 0.0
    assert report["metrics"]["cueAdjacentDrift"][0]["signedErrorMilliseconds"] == 0.0
    assert report["metrics"]["cueBoundaryErrors"][0]["signedErrorMilliseconds"] == 0.0
    assert report["metrics"]["sectionBoundaryErrors"][0]["startErrorMilliseconds"] == 0.0
    assert "Candidate timeline was shifted" in report["warnings"][0]


def test_sparse_candidate_grid_reports_low_reference_recall(tmp_path: Path) -> None:
    track = load_rekordbox_track(_write_rekordbox_xml(tmp_path))
    artifact = _analyzed_artifact(beat_offset_seconds=0.0)
    artifact["beatGrid"]["beats"] = artifact["beatGrid"]["beats"][::2]

    report = evaluate_analyzed_artifact_against_rekordbox(artifact, track)

    beat_grid = report["metrics"]["beatGrid"]
    assert beat_grid["candidateBeatCount"] < beat_grid["referenceBeatCount"]
    assert beat_grid["beatCoverageRatio"] < 0.51
    assert beat_grid["medianAbsoluteErrorMilliseconds"] == 0.0
    assert beat_grid["candidatePrecisionWithin25Milliseconds"] == 1.0
    assert beat_grid["referenceRecallWithin25Milliseconds"] < 0.51


def test_missing_candidate_boundaries_are_reported_without_crashing(tmp_path: Path) -> None:
    track = load_rekordbox_track(_write_rekordbox_xml(tmp_path))
    artifact = _analyzed_artifact(beat_offset_seconds=0.0)
    artifact["beatGrid"]["beats"] = []
    artifact["sections"] = []
    artifact["cuePoints"] = []

    report = evaluate_analyzed_artifact_against_rekordbox(artifact, track)

    assert report["metrics"]["beatGrid"]["candidateBeatCount"] == 0
    assert report["metrics"]["beatGrid"]["medianAbsoluteErrorMilliseconds"] is None
    assert report["metrics"]["cueAdjacentDrift"][0]["nearestCandidateBeatTimeSeconds"] is None
    assert report["metrics"]["cueBoundaryErrors"][0]["status"] == "missing_candidate"
    assert report["metrics"]["sectionBoundaryErrors"][0]["status"] == "missing_candidate"
    assert "Candidate artifact has no beat markers" in report["warnings"][0]


def test_write_rekordbox_evaluation_report_writes_json_file(tmp_path: Path) -> None:
    analyzed_path = tmp_path / "analyzed-track.json"
    analyzed_path.write_text(json.dumps(_analyzed_artifact(beat_offset_seconds=0.005)), encoding="utf-8")
    output_path = tmp_path / "benchmark" / "report.json"

    written_path = write_rekordbox_evaluation_report(
        analyzed_path,
        _write_rekordbox_xml(tmp_path),
        output_path,
        options=RekordboxEvaluationOptions(candidate_name="file-candidate"),
    )

    payload = json.loads(written_path.read_text(encoding="utf-8"))
    assert written_path == output_path
    assert payload["candidate"]["name"] == "file-candidate"
    assert payload["metrics"]["beatGrid"]["firstBeatOffsetMilliseconds"] == 5.0


def test_cli_evaluate_rekordbox_writes_report(tmp_path: Path, capsys) -> None:
    analyzed_path = tmp_path / "analyzed-track.json"
    analyzed_path.write_text(json.dumps(_analyzed_artifact(beat_offset_seconds=0.005)), encoding="utf-8")
    output_path = tmp_path / "report.json"

    exit_code = main(
        [
            "evaluate-rekordbox",
            str(analyzed_path),
            str(_write_rekordbox_xml(tmp_path)),
            "--out",
            str(output_path),
            "--candidate-name",
            "cli-candidate",
            "--timeline-offset-seconds",
            "-0.005",
            "--timeline-offset-policy",
            "fixture-offset",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert captured.err == ""
    assert payload["ok"] is True
    assert payload["artifact"] == "rekordbox-evaluation-report"
    assert report["candidate"]["name"] == "cli-candidate"
    assert report["metrics"]["beatGrid"]["firstBeatOffsetMilliseconds"] == 0.0


def _write_rekordbox_xml(tmp_path: Path) -> Path:
    xml_path = tmp_path / "rekordbox.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="1">
    <TRACK Name="Example Track" AverageBpm="150.00" Location="file://localhost/example.mp3">
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


def _analyzed_artifact(
    *,
    beat_offset_seconds: float,
    cue_offset_seconds: float = 0.0,
    section_offset_seconds: float = 0.0,
) -> dict:
    beat_period = 60.0 / 150.0
    beat_start = 0.098 + beat_offset_seconds
    duration_seconds = 185.913469
    beat_count = int((duration_seconds - beat_start) / beat_period) + 1
    beats = [
        {
            "index": index,
            "timeSeconds": round(beat_start + index * beat_period, 6),
            "confidence": 0.9,
        }
        for index in range(beat_count)
    ]
    return {
        "schemaVersion": "1.0.0",
        "trackId": "example-track",
        "source": {"providerMetadata": {}},
        "analyzer": {
            "producer": "test-candidate",
            "producerVersion": "0.1.0",
            "parametersHash": "sha256:test",
        },
        "durationSeconds": duration_seconds,
        "tempo": {
            "bpm": 150.5,
            "normalizedBpm": 150.5,
            "confidence": 0.93,
            "tempoClass": "straight",
            "candidates": [{"bpm": 150.5, "confidence": 0.93, "backend": "test"}],
        },
        "beatGrid": {
            "beats": beats,
            "downbeats": [
                {
                    "index": 0,
                    "timeSeconds": beat_start,
                    "beatInBar": 1,
                    "confidence": 0.9,
                }
            ],
            "confidence": 0.9,
        },
        "sections": [
            {
                "id": "section-drop-001",
                "type": "drop",
                "startSeconds": 51.398 + section_offset_seconds,
                "endSeconds": 76.748 + section_offset_seconds,
                "confidence": 0.7,
            },
            {
                "id": "section-drop-002",
                "type": "drop",
                "startSeconds": 128.098 + section_offset_seconds,
                "endSeconds": 179.298 + section_offset_seconds,
                "confidence": 0.7,
            },
        ],
        "cuePoints": [
            {
                "id": "cue-drop-001",
                "type": "drop",
                "timeSeconds": 51.408 + cue_offset_seconds,
                "confidence": 0.7,
            },
            {
                "id": "cue-mix-out-001",
                "type": "mix_out",
                "timeSeconds": 76.798 + cue_offset_seconds,
                "confidence": 0.7,
            },
            {
                "id": "cue-drop-002",
                "type": "drop",
                "timeSeconds": 128.098 + cue_offset_seconds,
                "confidence": 0.7,
            },
            {
                "id": "cue-mix-out-002",
                "type": "mix_out",
                "timeSeconds": 179.298 + cue_offset_seconds,
                "confidence": 0.7,
            },
        ],
        "quality": {"overallConfidence": 0.8, "warnings": []},
    }
