import json
import importlib.util
import math
from pathlib import Path
import subprocess
import wave

import pytest

from audio_fixtures import create_energy_ramp_fixture
from autodj_analysis import (
    ANALYZER_PRODUCER,
    ANALYZER_VERSION,
    EnergyFeatures,
    SignalAnalysisResult,
    StructureFeatures,
    TempoFeatures,
    analyzed_track_path,
    waveform_path,
)
from autodj_analysis.cli import main


def test_cli_classify_prints_json(capsys) -> None:
    exit_code = main(["classify", "cli-track.wav"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["primaryGenre"] == "dubstep"


def test_cli_analyze_writes_artifact_and_prints_path(tmp_path, capsys) -> None:
    exit_code = main(["analyze", "cli-track.wav", "--out", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert (tmp_path / "analyzed-track.json").exists()


def _completed(command, payload: dict, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=list(command),
        returncode=returncode,
        stdout=json.dumps(payload),
        stderr=stderr,
    )


def _ffprobe_payload(duration: float = 12.5) -> dict:
    return {
        "streams": [
            {
                "index": 0,
                "codec_type": "audio",
                "codec_name": "mp3",
                "sample_rate": "48000",
                "channels": 2,
                "duration": f"{duration:.6f}",
            }
        ],
        "format": {
            "duration": f"{duration:.6f}",
            "format_name": "mp3",
        },
    }


def _runner(payload: dict, seen_commands: list[list[str]] | None = None):
    def run(command):
        if seen_commands is not None:
            seen_commands.append(list(command))
        return _completed(command, payload)

    return run


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


def _signal_analyzer():
    def analyze(track, identity, created_at_utc):
        return SignalAnalysisResult(
            waveform_artifact={
                "schemaVersion": "1.0.0",
                "trackId": track.track_id,
                "analyzer": {
                    "producer": ANALYZER_PRODUCER,
                    "producerVersion": ANALYZER_VERSION,
                    "createdAtUtc": created_at_utc,
                    "sourceContentHash": identity.source_content_hash or "",
                    "parametersHash": identity.parameters_hash or "",
                },
                "durationSeconds": 12.5,
                "sampleRate": 22050,
                "parameters": {"targetPointCount": 1, "mode": "peak-rms"},
                "summary": {"peak": 0.8, "rms": 0.4},
                "points": [{"timeSeconds": 0.0, "min": -0.8, "max": 0.8, "rms": 0.4}],
            },
            energy_features=EnergyFeatures(
                global_energy=0.42,
                curve=({"timeSeconds": 0.0, "value": 0.42},),
                bass_energy_curve=({"timeSeconds": 0.0, "value": 0.35},),
                onset_density_curve=({"timeSeconds": 0.0, "value": 0.25},),
                warnings=(),
                frame_length=2048,
                hop_length=512,
                curve_point_count=512,
                bass_cutoff_hz=180.0,
            ),
            tempo_features=TempoFeatures(
                bpm=140.0,
                normalized_bpm=140.0,
                confidence=0.76,
                tempo_class="straight",
                candidates=({"bpm": 140.0, "confidence": 0.76, "backend": "test"},),
                beats=({"index": 0, "timeSeconds": 0.0, "confidence": 0.72},),
                downbeats=(),
                beat_grid_confidence=0.72,
                warnings=("Downbeats were not emitted.",),
                backend="test",
                hop_length=512,
            ),
            structure_features=StructureFeatures(
                sections=(
                    {
                        "id": "section-drop-001",
                        "type": "drop",
                        "startSeconds": 0.0,
                        "endSeconds": 12.5,
                        "confidence": 0.68,
                    },
                ),
                cue_points=(
                    {
                        "id": "cue-drop-001",
                        "type": "drop",
                        "timeSeconds": 0.0,
                        "sectionId": "section-drop-001",
                        "confidence": 0.68,
                    },
                ),
                warnings=(),
                backend="test",
                high_energy_threshold=0.65,
                low_energy_threshold=0.35,
            ),
        )

    return analyze


def _write_manifest(tmp_path: Path, tracks: list[dict]) -> Path:
    music_root = tmp_path / "music"
    music_root.mkdir(exist_ok=True)
    manifest_tracks = []

    for track in tracks:
        track_id = track["track_id"]
        filename = track.get("filename", f"{track_id}.mp3")
        if track.get("create_source", True):
            (music_root / filename).write_bytes(b"fake audio bytes")
        manifest_tracks.append(
            {
                "trackId": track_id,
                "repositoryId": "local-test-repo",
                "sourceUri": filename,
                "contentHash": track.get("content_hash", f"sha256:{track_id}"),
                "title": track_id,
                "formatHint": "mp3",
            }
        )

    manifest_path = tmp_path / "repository-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "repositoryId": "local-test-repo",
                "producer": "autodj.repository.local",
                "producerVersion": "0.1.0",
                "createdAtUtc": "2026-05-16T00:00:00Z",
                "source": {
                    "repositoryType": "local",
                    "rootUri": str(music_root),
                },
                "tracks": manifest_tracks,
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _write_cli_gain_wav(path: Path, *, sample_rate: int, amplitude: float) -> None:
    frames = bytearray()
    for frame in range(sample_rate * 2):
        seconds = frame / sample_rate
        sample = amplitude * math.sin(2.0 * math.pi * 440.0 * seconds)
        frames.extend(round(sample * 32767).to_bytes(2, byteorder="little", signed=True))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def _write_cli_gain_plan(tmp_path: Path) -> Path:
    plan = {
        "schemaVersion": "1.0.0",
        "planId": "cli-gain-plan",
        "assets": [
            {"trackId": "outgoing", "sourceUri": "outgoing.wav"},
            {"trackId": "incoming", "sourceUri": "incoming.wav"},
        ],
        "tracks": [
            {
                "placementId": "place-outgoing",
                "trackId": "outgoing",
                "deck": 1,
                "sourceStartSeconds": 0.0,
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 1.0,
            },
            {
                "placementId": "place-incoming",
                "trackId": "incoming",
                "deck": 2,
                "sourceStartSeconds": 0.0,
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 2.0,
            },
        ],
        "transitions": [
            {
                "transitionId": "transition-cli-gain",
                "fromPlacementId": "place-outgoing",
                "toPlacementId": "place-incoming",
                "technique": "build_to_drop_swap",
                "templateId": "second_build_drop_switch_v1",
                "timelineStartSeconds": 0.0,
                "timelineEndSeconds": 1.0,
                "measureCountToTarget": 1.0,
                "score": 1.0,
                "sourceAnchors": {
                    "fromBuildStart": {"trackId": "outgoing", "sourceSeconds": 0.0},
                    "fromDropStart": {"trackId": "outgoing", "sourceSeconds": 1.0},
                    "toBuildStart": {"trackId": "incoming", "sourceSeconds": 0.0},
                    "toDropStart": {"trackId": "incoming", "sourceSeconds": 1.0},
                },
            }
        ],
        "commands": [
            {
                "type": "automate",
                "at": 0.0,
                "deck": 2,
                "control": "volume",
                "keyframes": [
                    {"at": 0.0, "value": 0.0, "interpolation": "hold"},
                    {"at": 0.5, "value": 1.0, "interpolation": "smoothstep"},
                ],
            },
            {
                "type": "automate",
                "at": 0.0,
                "deck": 1,
                "control": "volume",
                "keyframes": [
                    {"at": 0.0, "value": 1.0, "interpolation": "hold"},
                    {"at": 0.875, "value": 0.0, "interpolation": "hold"},
                ],
            },
        ],
        "annotations": [],
    }
    path = tmp_path / "mix-plan.json"
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return path


def test_cli_analyze_batch_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["analyze-batch", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "repository_manifest" in captured.out
    assert "--ffprobe" in captured.out
    assert "--force" in captured.out
    assert "--parameters-hash" in captured.out
    assert "--section-backend" in captured.out
    assert "--canonical-audio-root" in captured.out
    assert "--json" in captured.out


def test_cli_canonicalize_audio_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["canonicalize-audio", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "repository_manifest" in captured.out
    assert "--out" in captured.out
    assert "--ffmpeg" in captured.out
    assert "--ffprobe" in captured.out
    assert "--force" in captured.out
    assert "--sample-rate" in captured.out
    assert "--fallback-sample-rate" in captured.out
    assert "--json" in captured.out


def test_cli_debug_waveform_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["debug-waveform", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "audio_path" in captured.out
    assert "--points" in captured.out
    assert "--sample-rate" in captured.out
    assert "--low-cutoff-hz" in captured.out
    assert "--high-cutoff-hz" in captured.out


def test_cli_benchmark_timing_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["benchmark-timing", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "cases" in captured.out
    assert "--candidates" in captured.out
    assert "--sample-rate" in captured.out
    assert "--debug-waveform-points" in captured.out


def test_cli_benchmark_sections_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["benchmark-sections", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "rekordbox_xml" in captured.out
    assert "--candidates" in captured.out
    assert "--sample-rate" in captured.out
    assert "--debug-waveform-points" in captured.out


def test_cli_benchmark_keys_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["benchmark-keys", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "rekordbox_xml" in captured.out
    assert "--candidates" in captured.out
    assert "--sample-rate" in captured.out
    assert "--json" in captured.out


def test_cli_tempo_stretch_smoke_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["tempo-stretch-smoke", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "--audio" in captured.out
    assert "--source-bpm" in captured.out
    assert "--target-bpm" in captured.out
    assert "--backends" in captured.out
    assert "--sample-rate" in captured.out
    assert "--quality" in captured.out
    assert "--target-bpm-bias" in captured.out
    assert "--json" in captured.out


def test_cli_stretch_audio_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["stretch-audio", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "audio_path" in captured.out
    assert "--source-bpm" in captured.out
    assert "--target-bpm" in captured.out
    assert "--backend" in captured.out
    assert "--out" in captured.out
    assert "--report" in captured.out
    assert "--sample-rate" in captured.out
    assert "--quality" in captured.out
    assert "--target-bpm-bias" in captured.out
    assert "--json" in captured.out


def test_cli_render_mixplan_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["render-mixplan", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "mix_plan" in captured.out
    assert "--asset-root" in captured.out
    assert "--sample-rate" in captured.out
    assert "--tempo-backend" in captured.out
    assert "--tempo-quality" in captured.out
    assert "--json" in captured.out


def test_cli_rank_drop_anchors_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["rank-drop-anchors", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "analyzed_track" in captured.out
    assert "--out" in captured.out
    assert "--max-candidates" in captured.out
    assert "--json" in captured.out


def test_cli_drop_wall_debug_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["drop-wall-debug", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "audio_path" in captured.out
    assert "--time" in captured.out
    assert "--out" in captured.out
    assert "--svg" in captured.out
    assert "--track-id" in captured.out
    assert "--sample-rate" in captured.out
    assert "--search-window-ms" in captured.out
    assert "--preferred-window-ms" in captured.out
    assert "--preferred-score-ratio" in captured.out
    assert "--json" in captured.out


def test_cli_benchmark_drop_anchors_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["benchmark-drop-anchors", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "rekordbox_xml" in captured.out
    assert "--analysis-root" in captured.out
    assert "--top-k" in captured.out
    assert "--match-tolerance-ms" in captured.out
    assert "--max-candidates" in captured.out
    assert "--json" in captured.out


def test_cli_cue_detr_predict_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["cue-detr-predict", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "audio_path" in captured.out
    assert "--out" in captured.out
    assert "--checkpoint" in captured.out
    assert "--sensitivity" in captured.out
    assert "--min-distance-seconds" in captured.out
    assert "--device" in captured.out
    assert "--json" in captured.out


def test_cli_benchmark_cue_detr_drops_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["benchmark-cue-detr-drops", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "rekordbox_xml" in captured.out
    assert "--analysis-root" in captured.out
    assert "--top-k" in captured.out
    assert "--match-tolerance-ms" in captured.out
    assert "--snap-window-ms" in captured.out
    assert "--limit" in captured.out
    assert "--json" in captured.out


def test_cli_edm98_predict_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["edm98-predict", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "audio_path" in captured.out
    assert "--out" in captured.out
    assert "--checkpoint" in captured.out
    assert "--musicfm-model" in captured.out
    assert "--device" in captured.out
    assert "--json" in captured.out


def test_cli_benchmark_edm98_drops_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["benchmark-edm98-drops", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "rekordbox_xml" in captured.out
    assert "--analysis-root" in captured.out
    assert "--top-k" in captured.out
    assert "--match-tolerance-ms" in captured.out
    assert "--snap-window-ms" in captured.out
    assert "--limit" in captured.out
    assert "--json" in captured.out


def test_cli_nudge_mixplan_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["nudge-mixplan", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "mix_plan" in captured.out
    assert "--asset-root" in captured.out
    assert "--window-ms" in captured.out
    assert "--max-nudge-ms" in captured.out
    assert "--refined-anchor-report" not in captured.out
    assert "--use-refined-anchors" not in captured.out
    assert "--json" in captured.out


def test_cli_gain_plan_drop_switch_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["gain-plan-drop-switch", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "mix_plan" in captured.out
    assert "--out" in captured.out
    assert "--report" in captured.out
    assert "--asset-root" in captured.out
    assert "--target-headroom-db" in captured.out
    assert "--max-overlap-gain-reduction-db" in captured.out
    assert "--drop-energy-floor-db" in captured.out
    assert "--sample-rate" in captured.out
    assert "--json" in captured.out


def test_cli_export_rekordbox_xml_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["export-rekordbox-xml", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "analyzed_track" in captured.out
    assert "--out" in captured.out
    assert "--source-uri" in captured.out
    assert "--track-name" in captured.out
    assert "--include-cue-points" in captured.out
    assert "--cue-policy" in captured.out
    assert "--max-hot-cues" in captured.out
    assert "--time-precision" in captured.out


def test_cli_apply_rekordbox_semantics_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["apply-rekordbox-semantics", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "analyzed_track" in captured.out
    assert "rekordbox_xml" in captured.out
    assert "--out" in captured.out
    assert "--track-name" in captured.out
    assert "--json" in captured.out


def test_cli_parse_transition_template_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["parse-transition-template", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "template" in captured.out
    assert "bar/beat" in captured.out
    assert "--out" in captured.out
    assert "--json" in captured.out


def test_cli_export_rekordbox_xml_writes_xml(tmp_path, capsys) -> None:
    analyzed_path = tmp_path / "analyzed-track.json"
    analyzed_path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "trackId": "track-a",
                "title": "Track A",
                "durationSeconds": 64.0,
                "tempo": {"bpm": 140.0, "normalizedBpm": 140.0},
                "beatGrid": {"beats": [{"index": 0, "timeSeconds": 0.05, "confidence": 1.0}]},
                "sections": [{"id": "section-drop-001", "type": "drop", "startSeconds": 32.0, "endSeconds": 48.0}],
                "cuePoints": [],
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "rekordbox.xml"

    exit_code = main(
        [
            "export-rekordbox-xml",
            str(analyzed_path),
            "--out",
            str(output_path),
            "--source-uri",
            "C:/Music/track-a.mp3",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    xml_text = output_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert captured.err == ""
    assert payload["artifact"] == "rekordbox-xml"
    assert 'AverageBpm="140.00"' in xml_text
    assert 'Name="drop_1_start"' in xml_text


def test_cli_apply_rekordbox_semantics_preserves_tempo_grid(tmp_path, capsys) -> None:
    analyzed_path = tmp_path / "analyzed-track.json"
    analyzed_path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "trackId": "track-a",
                "durationSeconds": 64.0,
                "source": {"providerMetadata": {}},
                "analyzer": {},
                "tempo": {
                    "bpm": 150.0,
                    "normalizedBpm": 150.0,
                    "confidence": 0.9,
                    "candidates": [{"backend": "autodj-test", "bpm": 150.0}],
                },
                "beatGrid": {
                    "beats": [{"index": 88, "timeSeconds": 32.05, "confidence": 0.9}],
                    "downbeats": [],
                    "confidence": 0.8,
                },
                "sections": [],
                "cuePoints": [],
                "quality": {"overallConfidence": 0.8, "warnings": []},
            }
        ),
        encoding="utf-8",
    )
    xml_path = tmp_path / "rekordbox.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="1">
    <TRACK Name="Track A" AverageBpm="140.00" Location="file://localhost/C:/Music/track-a.mp3">
      <TEMPO Inizio="0.000" Bpm="140.00" Metro="4/4" Battito="1"/>
      <POSITION_MARK Name="drop_1_start" Type="0" Start="32.000" Num="0"/>
    </TRACK>
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "semantic.json"

    exit_code = main(
        [
            "apply-rekordbox-semantics",
            str(analyzed_path),
            str(xml_path),
            "--out",
            str(output_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert captured.err == ""
    assert payload["mode"] == "semantic_only"
    assert artifact["tempo"]["candidates"][0]["backend"] == "autodj-test"
    assert artifact["beatGrid"]["beats"][0]["index"] == 88
    assert artifact["cuePoints"][0]["beatIndex"] == 88


def test_cli_parse_transition_template_writes_json(tmp_path, capsys) -> None:
    template_path = tmp_path / "recipe.txt"
    template_path.write_text(
        """
kind: generic_transition
type: reverb_exit
recipe_id: manual-recipe
notes: Reverb tail transition
anchor: a_reverb_start = song_a.drop_end - 1 bar
anchor: a_drop_end = song_a.drop_end
anchor: b_first = song_b.first_beat
action: a.reverbWet at a_reverb_start = 1 straight
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "recipe.json"

    exit_code = main(["parse-transition-template", str(template_path), "--out", str(output_path), "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    recipe = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert captured.err == ""
    assert payload["artifact"] == "transition-recipe"
    assert recipe["recipeId"] == "manual-recipe"


def test_cli_gain_plan_drop_switch_writes_report_and_adjusted_plan(tmp_path, capsys) -> None:
    sample_rate = 8_000
    _write_cli_gain_wav(tmp_path / "outgoing.wav", sample_rate=sample_rate, amplitude=0.35)
    _write_cli_gain_wav(tmp_path / "incoming.wav", sample_rate=sample_rate, amplitude=0.45)
    plan_path = _write_cli_gain_plan(tmp_path)
    original = json.loads(plan_path.read_text(encoding="utf-8"))
    out_path = tmp_path / "mix-plan-gain-planned.json"
    report_path = tmp_path / "energy-report.json"

    exit_code = main(
        [
            "gain-plan-drop-switch",
            str(plan_path),
            "--out",
            str(out_path),
            "--report",
            str(report_path),
            "--asset-root",
            str(tmp_path),
            "--sample-rate",
            str(sample_rate),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    planned = json.loads(out_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert captured.err == ""
    assert payload["ok"] is True
    assert payload["artifact"] == "mixplan-drop-switch-gain-plan"
    assert report["artifact"] == "mixplan-drop-switch-energy-report"
    assert planned["transitions"][0]["sourceAnchors"] == original["transitions"][0]["sourceAnchors"]


@pytest.mark.analysis
def test_cli_debug_waveform_writes_rgb_artifact(tmp_path, capsys) -> None:
    _skip_without_debug_dependencies()
    fixture = create_energy_ramp_fixture(tmp_path, duration_seconds=1.0)
    output_path = tmp_path / "debug-waveform.json"

    exit_code = main(
        [
            "debug-waveform",
            str(fixture.path),
            "--out",
            str(output_path),
            "--points",
            "32",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    artifact = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert captured.err == ""
    assert payload["ok"] is True
    assert payload["artifact"] == "debug-waveform"
    assert payload["points"] == 32
    assert payload["sourceTimelinePolicy"] == "direct-audio-path"
    assert artifact["artifactType"] == "debug-waveform"
    assert artifact["source"]["audioPath"] == str(fixture.path)
    assert artifact["source"]["timelinePolicy"] == "direct-audio-path"
    assert artifact["points"][0]["low"] >= 0.0


@pytest.mark.analysis
def test_cli_debug_waveform_reports_canonical_timeline_policy(tmp_path, capsys) -> None:
    _skip_without_debug_dependencies()
    canonical_dir = tmp_path / "tracks" / "track-a"
    canonical_dir.mkdir(parents=True)
    canonical_wav = canonical_dir / "canonical.wav"
    _write_cli_gain_wav(canonical_wav, sample_rate=8_000, amplitude=0.25)
    (canonical_dir / "canonical-audio.json").write_text("{}", encoding="utf-8")
    output_path = tmp_path / "debug-waveform.json"

    exit_code = main(
        [
            "debug-waveform",
            str(canonical_wav),
            "--out",
            str(output_path),
            "--points",
            "32",
            "--sample-rate",
            "8000",
            "--track-id",
            "track-a",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    artifact = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert captured.err == ""
    assert payload["sourceTimelinePolicy"] == "shared-canonical-pcm"
    assert artifact["source"]["timelinePolicy"] == "shared-canonical-pcm"


def test_cli_analyze_batch_json_summary_output(tmp_path, capsys) -> None:
    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a", "content_hash": "sha256:a"}])
    cache_root = tmp_path / ".autodj-cache"
    seen_commands: list[list[str]] = []

    exit_code = main(
        [
            "analyze-batch",
            str(manifest_path),
            "--out",
            str(cache_root),
            "--ffprobe",
            "fake-ffprobe",
            "--parameters-hash",
            "sha256:cli-params",
            "--json",
        ],
        probe_runner=_runner(_ffprobe_payload(), seen_commands),
        signal_analyzer=_signal_analyzer(),
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    artifact = json.loads(analyzed_track_path(cache_root, "track-a").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert captured.err == ""
    assert payload["ok"] is True
    assert payload["totalTracks"] == 1
    assert payload["analyzed"] == 1
    assert payload["tracks"][0]["status"] == "analyzed"
    assert payload["tracks"][0]["artifactPath"] == str(analyzed_track_path(cache_root, "track-a"))
    assert payload["tracks"][0]["waveformPath"] == str(waveform_path(cache_root, "track-a"))
    assert seen_commands[0][0] == "fake-ffprobe"
    assert artifact["analyzer"]["parametersHash"] == "sha256:cli-params"
    assert waveform_path(cache_root, "track-a").exists()


def test_cli_analyze_batch_can_use_canonical_audio_root(tmp_path, capsys) -> None:
    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a", "content_hash": "sha256:a"}])
    cache_root = tmp_path / ".autodj-cache"
    canonical_root = tmp_path / "canonical-cache"
    canonical_track_dir = canonical_root / "tracks" / "track-a"
    canonical_track_dir.mkdir(parents=True)
    canonical_wav = canonical_track_dir / "canonical.wav"
    canonical_wav.write_bytes(b"fake canonical wav")
    seen = {}
    base_analyzer = _signal_analyzer()

    def analyzer(track, identity, created_at_utc):
        seen["source_path"] = track.source_path
        seen["source_uri"] = track.source_uri
        return base_analyzer(track, identity, created_at_utc)

    exit_code = main(
        [
            "analyze-batch",
            str(manifest_path),
            "--out",
            str(cache_root),
            "--canonical-audio-root",
            str(canonical_root),
            "--json",
        ],
        probe_runner=_runner(_ffprobe_payload()),
        signal_analyzer=analyzer,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    artifact = json.loads(analyzed_track_path(cache_root, "track-a").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert captured.err == ""
    assert payload["ok"] is True
    assert seen["source_path"] == canonical_wav
    assert seen["source_uri"] == "track-a.mp3"
    assert artifact["analyzer"]["parametersHash"].endswith("+canonical-pcm-v1")
    assert artifact["source"]["sourceUri"] == "track-a.mp3"
    assert artifact["source"]["providerMetadata"]["autodjAnalysisAudio"] == {
        "timelinePolicy": "shared-canonical-pcm",
        "canonicalPath": str(canonical_wav),
        "canonicalMetadataPath": str(canonical_track_dir / "canonical-audio.json"),
    }


def test_cli_canonicalize_audio_json_summary_output(tmp_path, capsys) -> None:
    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a", "content_hash": "sha256:a"}])
    cache_root = tmp_path / ".autodj-cache"
    seen = {}

    def runner(repository_manifest, output_root, **kwargs):
        seen["repository_manifest"] = repository_manifest
        seen["output_root"] = output_root
        seen["options"] = kwargs["options"]
        return {
            "ok": True,
            "artifact": "canonical-audio-batch",
            "manifestPath": str(repository_manifest),
            "outputRoot": str(output_root),
            "total": 1,
            "canonicalized": 1,
            "skipped": 0,
            "failed": 0,
            "tracks": [
                {
                    "trackId": "track-a",
                    "sourcePath": str(tmp_path / "music" / "track-a.mp3"),
                    "canonicalPath": str(cache_root / "tracks" / "track-a" / "canonical.wav"),
                    "metadataPath": str(cache_root / "tracks" / "track-a" / "canonical-audio.json"),
                    "status": "canonicalized",
                    "sourceContentHash": "sha256:a",
                    "sampleRate": 48000,
                    "channels": 1,
                    "durationSeconds": 12.5,
                    "warnings": [],
                }
            ],
        }

    exit_code = main(
        [
            "canonicalize-audio",
            str(manifest_path),
            "--out",
            str(cache_root),
            "--ffmpeg",
            "fake-ffmpeg",
            "--ffprobe",
            "fake-ffprobe",
            "--sample-rate",
            "48000",
            "--force",
            "--json",
        ],
        canonical_audio_runner=runner,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert captured.err == ""
    assert payload["ok"] is True
    assert payload["artifact"] == "canonical-audio-batch"
    assert payload["canonicalized"] == 1
    assert seen["repository_manifest"] == manifest_path
    assert seen["output_root"] == cache_root
    assert seen["options"].ffmpeg_path == "fake-ffmpeg"
    assert seen["options"].ffprobe_path == "fake-ffprobe"
    assert seen["options"].target_sample_rate == 48000
    assert seen["options"].force is True


def test_cli_benchmark_timing_json_summary_output(tmp_path, capsys) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "trackId": "track-a",
                        "audioPath": str(tmp_path / "track-a.mp3"),
                        "rekordboxXmlPath": str(tmp_path / "track-a.xml"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    seen = {}

    def runner(cases, output_root, **kwargs):
        seen["cases"] = cases
        seen["output_root"] = output_root
        seen["kwargs"] = kwargs
        return {
            "ok": True,
            "reportType": "timing-candidate-benchmark",
            "outputRoot": str(output_root),
            "cases": [],
            "candidateSummary": [],
        }

    exit_code = main(
        [
            "benchmark-timing",
            str(cases_path),
            "--out",
            str(tmp_path / "benchmark"),
            "--candidates",
            "current-autodj-signal,beat-this",
            "--sample-rate",
            "44100",
            "--debug-waveform-points",
            "1024",
            "--json",
        ],
        timing_benchmark_runner=runner,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert captured.err == ""
    assert payload["reportType"] == "timing-candidate-benchmark"
    assert seen["cases"][0].track_id == "track-a"
    assert seen["kwargs"]["candidates"] == ("current-autodj-signal", "beat-this")
    assert seen["kwargs"]["analysis_sample_rate"] == 44100
    assert seen["kwargs"]["debug_waveform_points"] == 1024


def test_cli_benchmark_sections_json_summary_output(tmp_path, capsys) -> None:
    audio_path = tmp_path / "track-a.mp3"
    audio_path.write_bytes(b"audio")
    xml_path = tmp_path / "rekordbox.xml"
    xml_path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="1">
    <TRACK Name="Track A" AverageBpm="150.00" Location="{audio_path.as_uri()}">
      <TEMPO Inizio="0.000" Bpm="150.00" Metro="4/4" Battito="1"/>
      <POSITION_MARK Name="drop_1_start" Type="0" Start="16.000" Num="0"/>
      <POSITION_MARK Name="drop_1_end" Type="0" Start="32.000" Num="1"/>
    </TRACK>
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )
    seen = {}

    def runner(cases, output_root, **kwargs):
        seen["cases"] = cases
        seen["output_root"] = output_root
        seen["kwargs"] = kwargs
        return {
            "ok": True,
            "reportType": "semantic-section-candidate-benchmark",
            "outputRoot": str(output_root),
            "cases": [],
            "candidateSummary": [],
        }

    exit_code = main(
        [
            "benchmark-sections",
            str(xml_path),
            "--out",
            str(tmp_path / "section-benchmark"),
            "--candidates",
            "current-autodj-signal,songformer",
            "--sample-rate",
            "44100",
            "--debug-waveform-points",
            "2048",
            "--json",
        ],
        semantic_benchmark_runner=runner,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert captured.err == ""
    assert payload["reportType"] == "semantic-section-candidate-benchmark"
    assert seen["cases"][0].track_name == "Track A"
    assert seen["kwargs"]["candidates"] == ("current-autodj-signal", "songformer")
    assert seen["kwargs"]["analysis_sample_rate"] == 44100
    assert seen["kwargs"]["debug_waveform_points"] == 2048


def test_cli_benchmark_keys_json_summary_output(tmp_path, capsys) -> None:
    audio_path = tmp_path / "track-a.mp3"
    audio_path.write_bytes(b"audio")
    xml_path = tmp_path / "rekordbox.xml"
    xml_path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="1">
    <TRACK Name="Track A" AverageBpm="150.00" Tonality="9A" Location="{audio_path.as_uri()}">
      <TEMPO Inizio="0.000" Bpm="150.00" Metro="4/4" Battito="1"/>
    </TRACK>
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )
    seen = {}

    def runner(cases, output_root, **kwargs):
        seen["cases"] = cases
        seen["output_root"] = output_root
        seen["kwargs"] = kwargs
        return {
            "ok": True,
            "reportType": "key-candidate-benchmark",
            "outputRoot": str(output_root),
            "cases": [],
            "candidateSummary": [],
        }

    exit_code = main(
        [
            "benchmark-keys",
            str(xml_path),
            "--out",
            str(tmp_path / "key-benchmark"),
            "--candidates",
            "essentia-key,keyfinder",
            "--sample-rate",
            "44100",
            "--json",
        ],
        key_benchmark_runner=runner,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert captured.err == ""
    assert payload["reportType"] == "key-candidate-benchmark"
    assert seen["cases"][0].track_name == "Track A"
    assert seen["cases"][0].truth.camelot.camelot == "9A"
    assert seen["kwargs"]["candidates"] == ("essentia-key", "keyfinder")
    assert seen["kwargs"]["analysis_sample_rate"] == 44100


def test_cli_tempo_stretch_smoke_json_summary_output(tmp_path, capsys) -> None:
    audio_path = tmp_path / "track.wav"
    audio_path.write_bytes(b"placeholder")
    seen = {}

    def runner(audio_path_arg, output_root, **kwargs):
        seen["audio_path"] = audio_path_arg
        seen["output_root"] = output_root
        seen["kwargs"] = kwargs
        return {
            "ok": True,
            "artifact": "tempo-stretch-smoke-report",
            "outputRoot": str(output_root),
            "results": [],
        }

    exit_code = main(
        [
            "tempo-stretch-smoke",
            "--audio",
            str(audio_path),
            "--source-bpm",
            "160",
            "--target-bpm",
            "150",
            "--out",
            str(tmp_path / "stretch-smoke"),
            "--backends",
            "rubberband,soundstretch",
            "--sample-rate",
            "48000",
            "--quality",
            "fast",
            "--target-bpm-bias",
            "0.02",
            "--json",
        ],
        tempo_stretch_smoke_runner=runner,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload["artifact"] == "tempo-stretch-smoke-report"
    assert seen["audio_path"] == audio_path
    assert seen["kwargs"]["backends"] == ("rubberband", "soundstretch")
    assert seen["kwargs"]["source_bpm"] == 160.0
    assert seen["kwargs"]["target_bpm"] == 150.0
    assert seen["kwargs"]["sample_rate"] == 48000
    assert seen["kwargs"]["quality"] == "fast"
    assert seen["kwargs"]["target_bpm_bias"] == 0.02


def test_cli_stretch_audio_json_summary_output(tmp_path, capsys) -> None:
    audio_path = tmp_path / "track.wav"
    audio_path.write_bytes(b"placeholder")
    seen = {}

    def runner(audio_path_arg, output_path, **kwargs):
        seen["audio_path"] = audio_path_arg
        seen["output_path"] = output_path
        seen["kwargs"] = kwargs
        return {
            "ok": True,
            "artifact": "tempo-stretch-report",
            "outputPath": str(output_path),
            "backendName": kwargs["options"].backend,
            "sourceBpm": kwargs["options"].source_bpm,
            "targetBpm": kwargs["options"].target_bpm,
        }

    exit_code = main(
        [
            "stretch-audio",
            str(audio_path),
            "--source-bpm",
            "160",
            "--target-bpm",
            "150",
            "--backend",
            "rubberband",
            "--out",
            str(tmp_path / "stretched.wav"),
            "--report",
            str(tmp_path / "stretch-report.json"),
            "--sample-rate",
            "48000",
            "--quality",
            "fine",
            "--target-bpm-bias",
            "0.02",
            "--json",
        ],
        tempo_stretch_runner=runner,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload["artifact"] == "tempo-stretch-report"
    assert payload["backendName"] == "rubberband"
    assert payload["sourceBpm"] == 160.0
    assert payload["targetBpm"] == 150.0
    assert seen["audio_path"] == audio_path
    assert seen["kwargs"]["report_path"] == tmp_path / "stretch-report.json"
    assert seen["kwargs"]["options"].sample_rate == 48000
    assert seen["kwargs"]["options"].target_bpm_bias == 0.02


def test_cli_analyze_batch_successful_human_output(tmp_path, capsys) -> None:
    manifest_path = _write_manifest(tmp_path, [{"track_id": "track-a"}])
    cache_root = tmp_path / ".autodj-cache"

    exit_code = main(
        ["analyze-batch", str(manifest_path), "--out", str(cache_root)],
        probe_runner=_runner(_ffprobe_payload()),
        signal_analyzer=_signal_analyzer(),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Batch analysis ok" in captured.out
    assert "Tracks: total=1, analyzed=1, skipped=0, failed=0" in captured.out
    assert "- track-a: analyzed" in captured.out
    assert captured.err == ""
    assert analyzed_track_path(cache_root, "track-a").exists()
    assert waveform_path(cache_root, "track-a").exists()


def test_cli_analyze_batch_manifest_failure_is_actionable(tmp_path, capsys) -> None:
    missing_manifest = tmp_path / "missing" / "repository-manifest.json"

    exit_code = main(["analyze-batch", str(missing_manifest), "--out", str(tmp_path / "cache")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Could not read repository manifest" in captured.err
    assert "Traceback" not in captured.err


def test_cli_analyze_batch_partial_failure_returns_nonzero_after_summary(tmp_path, capsys) -> None:
    manifest_path = _write_manifest(
        tmp_path,
        [
            {"track_id": "track-good", "content_hash": "sha256:good"},
            {"track_id": "track-missing", "content_hash": "sha256:missing", "create_source": False},
        ],
    )
    cache_root = tmp_path / ".autodj-cache"

    exit_code = main(
        ["analyze-batch", str(manifest_path), "--out", str(cache_root), "--json"],
        probe_runner=_runner(_ffprobe_payload()),
        signal_analyzer=_signal_analyzer(),
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert captured.err == ""
    assert payload["ok"] is False
    assert payload["totalTracks"] == 2
    assert payload["analyzed"] == 1
    assert payload["failed"] == 1
    assert payload["errors"][0]["code"] == "source_missing"
    assert payload["errors"][0]["trackId"] == "track-missing"
