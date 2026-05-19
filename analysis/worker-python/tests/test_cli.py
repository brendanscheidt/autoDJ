import json
import importlib.util
from pathlib import Path
import subprocess

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
    assert artifact["artifactType"] == "debug-waveform"
    assert artifact["points"][0]["low"] >= 0.0


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
