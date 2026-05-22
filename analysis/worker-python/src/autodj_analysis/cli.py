"""Command-line entrypoint for the AutoDJ analysis worker stub."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .analyze import analyze_stub
from .batch import (
    DEFAULT_PARAMETERS_HASH,
    SELECTED_SECTION_BACKEND,
    BatchAnalysisResult,
    SignalAnalyzer,
    analyze_repository_manifest,
)
from .debug_waveform import build_debug_waveform_artifact, write_debug_waveform_artifact
from .cue_detr import CueDetrOptions, predict_cue_detr_file
from .drop_anchor_ranker import DropAnchorRankerOptions, rank_drop_anchors_file
from .edm98 import Edm98Options, predict_edm98_file
from .evaluation import (
    DEFAULT_CUE_DETR_DROP_MATCH_TOLERANCE_SECONDS,
    DEFAULT_CUE_DETR_DROP_TOP_K,
    DEFAULT_CUE_DETR_SNAP_WINDOW_SECONDS,
    DEFAULT_EDM98_DROP_MATCH_TOLERANCE_SECONDS,
    DEFAULT_EDM98_DROP_TOP_K,
    DEFAULT_EDM98_SNAP_WINDOW_SECONDS,
    DEFAULT_DROP_ANCHOR_MATCH_TOLERANCE_SECONDS,
    DEFAULT_DROP_ANCHOR_TOP_K,
    DEFAULT_SEMANTIC_ANALYSIS_SAMPLE_RATE,
    DEFAULT_SEMANTIC_CANDIDATES,
    DEFAULT_SEMANTIC_DEBUG_WAVEFORM_POINTS,
    DEFAULT_TIMING_ANALYSIS_SAMPLE_RATE,
    DEFAULT_TIMING_CANDIDATES,
    DEFAULT_TIMING_DEBUG_WAVEFORM_POINTS,
    RekordboxEvaluationOptions,
    load_semantic_benchmark_cases,
    load_timing_benchmark_cases,
    run_cue_detr_drop_benchmark,
    run_drop_anchor_benchmark,
    run_edm98_drop_benchmark,
    run_semantic_section_benchmark,
    run_timing_benchmark,
    write_rekordbox_evaluation_report,
)
from .genre import classify_stub
from .audio_io import load_audio
from .manifest import ManifestError
from .mixplan_energy import GainPlanOptions, gain_plan_drop_switch_file
from .mixplan_nudge import NudgeOptions, nudge_mix_plan_file
from .mixplan_renderer import RenderOptions, render_mix_plan_file
from .probe import ProbeRunner
from .rekordbox_xml import apply_rekordbox_xml_file
from .rekordbox_xml import export_analyzed_track_to_rekordbox_xml_file
from .transition_template import parse_transition_template_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autodj-analysis",
        description="Offline AutoDJ analysis worker stub",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    classify = subparsers.add_parser(
        "classify",
        help="emit a stub GenreVerdict for an audio path",
    )
    classify.add_argument("audio_path", help="local WAV/MP3 path to classify")

    analyze = subparsers.add_parser(
        "analyze",
        help="write a stub analyzed-track.json artifact",
    )
    analyze.add_argument("audio_path", help="local WAV/MP3 path to analyze")
    analyze.add_argument(
        "--out",
        required=True,
        type=Path,
        help="directory where analyzed-track.json will be written",
    )

    analyze_batch = subparsers.add_parser(
        "analyze-batch",
        help="analyze tracks from a repository manifest into the metadata cache",
    )
    analyze_batch.add_argument(
        "repository_manifest",
        type=Path,
        help="repository-manifest.json file produced by the repository scanner",
    )
    analyze_batch.add_argument(
        "--out",
        required=True,
        type=Path,
        help="metadata cache root where per-track artifacts will be written",
    )
    analyze_batch.add_argument(
        "--ffprobe",
        default="ffprobe",
        help="ffprobe executable path or name",
    )
    analyze_batch.add_argument(
        "--force",
        action="store_true",
        help="rewrite artifacts even when cache freshness checks pass",
    )
    analyze_batch.add_argument(
        "--parameters-hash",
        default=DEFAULT_PARAMETERS_HASH,
        help="analysis parameter hash used for cache freshness",
    )
    analyze_batch.add_argument(
        "--section-backend",
        default=SELECTED_SECTION_BACKEND,
        help=(
            "semantic section backend for artifact generation "
            f"(default: {SELECTED_SECTION_BACKEND}; use current-autodj-signal for rough fallback only)"
        ),
    )
    analyze_batch.add_argument(
        "--json",
        action="store_true",
        help="print the batch summary as JSON",
    )

    debug_waveform = subparsers.add_parser(
        "debug-waveform",
        help="write a high-resolution RGB waveform JSON artifact for visual debugging",
    )
    debug_waveform.add_argument("audio_path", type=Path, help="local WAV/MP3 path to inspect")
    debug_waveform.add_argument(
        "--out",
        required=True,
        type=Path,
        help="JSON file path where the debug waveform artifact will be written",
    )
    debug_waveform.add_argument(
        "--points",
        type=int,
        default=32_768,
        help="target number of waveform points to write",
    )
    debug_waveform.add_argument(
        "--sample-rate",
        type=int,
        default=22_050,
        help="analysis sample rate used for the debug waveform",
    )
    debug_waveform.add_argument(
        "--low-cutoff-hz",
        type=float,
        default=180.0,
        help="low/mid band crossover frequency in Hz",
    )
    debug_waveform.add_argument(
        "--high-cutoff-hz",
        type=float,
        default=2_000.0,
        help="mid/high band crossover frequency in Hz",
    )
    debug_waveform.add_argument(
        "--track-id",
        help="optional track id to store in the debug artifact; defaults to the audio filename stem",
    )
    debug_waveform.add_argument(
        "--json",
        action="store_true",
        help="print the debug waveform summary as JSON",
    )

    apply_rekordbox = subparsers.add_parser(
        "apply-rekordbox-xml",
        help="apply Rekordbox XML tempo/grid/cue overrides to an analyzed-track artifact",
    )
    apply_rekordbox.add_argument("analyzed_track", type=Path, help="input analyzed-track.json path")
    apply_rekordbox.add_argument("rekordbox_xml", type=Path, help="Rekordbox XML export path")
    apply_rekordbox.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output analyzed-track JSON path with Rekordbox overrides",
    )
    apply_rekordbox.add_argument(
        "--track-name",
        help="optional Rekordbox TRACK Name to import when the XML has multiple tracks",
    )
    apply_rekordbox.add_argument(
        "--json",
        action="store_true",
        help="print the override summary as JSON",
    )

    export_rekordbox = subparsers.add_parser(
        "export-rekordbox-xml",
        help="export AutoDJ analyzed-track tempo/grid/sections as Rekordbox XML",
    )
    export_rekordbox.add_argument("analyzed_track", type=Path, help="input analyzed-track.json path")
    export_rekordbox.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output Rekordbox XML path",
    )
    export_rekordbox.add_argument(
        "--source-uri",
        help="audio file path/URI to write into the Rekordbox TRACK Location field",
    )
    export_rekordbox.add_argument(
        "--track-name",
        help="optional Rekordbox TRACK Name override",
    )
    export_rekordbox.add_argument(
        "--include-cue-points",
        action="store_true",
        help="also export analyzed cuePoints in addition to semantic section boundaries",
    )
    export_rekordbox.add_argument(
        "--cue-policy",
        choices=("transition-8", "all"),
        default="transition-8",
        help="which POSITION_MARK cue set to export; transition-8 caps to important transition hot cues",
    )
    export_rekordbox.add_argument(
        "--max-hot-cues",
        type=int,
        default=8,
        help="maximum POSITION_MARK entries when --cue-policy transition-8 is used",
    )
    export_rekordbox.add_argument(
        "--time-precision",
        type=int,
        default=3,
        help="decimal places for Rekordbox TEMPO/POSITION_MARK timestamps, between 0 and 6",
    )
    export_rekordbox.add_argument(
        "--json",
        action="store_true",
        help="print the export summary as JSON",
    )

    evaluate_rekordbox = subparsers.add_parser(
        "evaluate-rekordbox",
        help="compare an analyzed-track artifact against Rekordbox XML ground truth",
    )
    evaluate_rekordbox.add_argument("analyzed_track", type=Path, help="input analyzed-track.json path")
    evaluate_rekordbox.add_argument("rekordbox_xml", type=Path, help="Rekordbox XML export path")
    evaluate_rekordbox.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output benchmark report JSON path",
    )
    evaluate_rekordbox.add_argument(
        "--track-name",
        help="optional Rekordbox TRACK Name to evaluate when the XML has multiple tracks",
    )
    evaluate_rekordbox.add_argument(
        "--candidate-name",
        help="optional candidate backend name to record in the report",
    )
    evaluate_rekordbox.add_argument(
        "--processing-seconds",
        type=float,
        help="optional candidate processing time to record in the report",
    )
    evaluate_rekordbox.add_argument(
        "--timeline-offset-seconds",
        type=float,
        default=0.0,
        help="shift candidate beat/cue/section times by this many seconds before comparison",
    )
    evaluate_rekordbox.add_argument(
        "--timeline-offset-policy",
        default="none",
        help="human-readable name for the timeline offset policy used",
    )
    evaluate_rekordbox.add_argument(
        "--json",
        action="store_true",
        help="print the evaluation summary as JSON",
    )

    benchmark_timing = subparsers.add_parser(
        "benchmark-timing",
        help="run first-wave timing candidates against Rekordbox XML cases",
    )
    benchmark_timing.add_argument(
        "cases",
        type=Path,
        help="JSON file containing benchmark cases",
    )
    benchmark_timing.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output directory for candidate artifacts and benchmark reports",
    )
    benchmark_timing.add_argument(
        "--candidates",
        default=",".join(DEFAULT_TIMING_CANDIDATES),
        help="comma-separated candidate backend names to run",
    )
    benchmark_timing.add_argument(
        "--sample-rate",
        type=int,
        default=DEFAULT_TIMING_ANALYSIS_SAMPLE_RATE,
        help="shared decoded WAV sample rate for timing candidates",
    )
    benchmark_timing.add_argument(
        "--debug-waveform-points",
        type=int,
        default=DEFAULT_TIMING_DEBUG_WAVEFORM_POINTS,
        help="target point count for generated debug-waveform artifacts",
    )
    benchmark_timing.add_argument(
        "--json",
        action="store_true",
        help="print the benchmark summary as JSON",
    )

    benchmark_sections = subparsers.add_parser(
        "benchmark-sections",
        help="run semantic section candidates against labeled Rekordbox XML cues",
    )
    benchmark_sections.add_argument(
        "rekordbox_xml",
        type=Path,
        help="Rekordbox XML export containing one or more TRACK entries",
    )
    benchmark_sections.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output directory for candidate artifacts and section benchmark reports",
    )
    benchmark_sections.add_argument(
        "--candidates",
        default=",".join(DEFAULT_SEMANTIC_CANDIDATES),
        help="comma-separated semantic section candidate names to run",
    )
    benchmark_sections.add_argument(
        "--sample-rate",
        type=int,
        default=DEFAULT_SEMANTIC_ANALYSIS_SAMPLE_RATE,
        help="shared decoded WAV sample rate for section candidates",
    )
    benchmark_sections.add_argument(
        "--debug-waveform-points",
        type=int,
        default=DEFAULT_SEMANTIC_DEBUG_WAVEFORM_POINTS,
        help="target point count for generated debug-waveform artifacts",
    )
    benchmark_sections.add_argument(
        "--json",
        action="store_true",
        help="print the benchmark summary as JSON",
    )

    render_mixplan = subparsers.add_parser(
        "render-mixplan",
        help="render a MixPlan JSON file to a local WAV audition artifact",
    )
    render_mixplan.add_argument("mix_plan", type=Path, help="MixPlan JSON path to render")
    render_mixplan.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output directory for audition.wav, render-summary.json, and state-trace.json",
    )
    render_mixplan.add_argument(
        "--asset-root",
        type=Path,
        help="optional directory used to resolve relative MixPlan asset sourceUri paths",
    )
    render_mixplan.add_argument(
        "--sample-rate",
        type=int,
        default=44_100,
        help="rendered WAV sample rate",
    )
    render_mixplan.add_argument(
        "--json",
        action="store_true",
        help="print the render summary as JSON",
    )

    rank_drop_anchors = subparsers.add_parser(
        "rank-drop-anchors",
        help="rank likely drop-start anchors from an analyzed-track JSON artifact",
    )
    rank_drop_anchors.add_argument("analyzed_track", type=Path, help="input analyzed-track.json path")
    rank_drop_anchors.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output drop-anchor-ranking.json path",
    )
    rank_drop_anchors.add_argument(
        "--max-candidates",
        type=int,
        default=16,
        help="maximum ranked drop candidates to emit",
    )
    rank_drop_anchors.add_argument(
        "--json",
        action="store_true",
        help="print the ranking artifact as JSON",
    )

    benchmark_drop_anchors = subparsers.add_parser(
        "benchmark-drop-anchors",
        help="benchmark ranked drop anchors against Rekordbox drop_start cues",
    )
    benchmark_drop_anchors.add_argument("rekordbox_xml", type=Path, help="Rekordbox XML export path")
    benchmark_drop_anchors.add_argument(
        "--analysis-root",
        required=True,
        type=Path,
        help="analysis root containing tracks/*/analyzed-track.json artifacts",
    )
    benchmark_drop_anchors.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output folder for drop-anchor benchmark reports",
    )
    benchmark_drop_anchors.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_DROP_ANCHOR_TOP_K,
        help="candidate rank depth to count as a hit",
    )
    benchmark_drop_anchors.add_argument(
        "--match-tolerance-ms",
        type=float,
        default=DEFAULT_DROP_ANCHOR_MATCH_TOLERANCE_SECONDS * 1000.0,
        help="maximum absolute cue error, in milliseconds, counted as a match",
    )
    benchmark_drop_anchors.add_argument(
        "--max-candidates",
        type=int,
        default=16,
        help="maximum ranked drop candidates to emit per track",
    )
    benchmark_drop_anchors.add_argument(
        "--json",
        action="store_true",
        help="print the benchmark summary as JSON",
    )

    cue_detr_predict = subparsers.add_parser(
        "cue-detr-predict",
        help="predict cue-point candidates for one audio file using CUE-DETR",
    )
    cue_detr_predict.add_argument("audio_path", type=Path, help="local MP3/WAV path to analyze")
    cue_detr_predict.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output cue-detr-candidates.json path",
    )
    cue_detr_predict.add_argument(
        "--checkpoint",
        default=CueDetrOptions.checkpoint,
        help="Hugging Face model id or local checkpoint path",
    )
    cue_detr_predict.add_argument(
        "--sensitivity",
        type=float,
        default=CueDetrOptions.sensitivity,
        help="minimum normalized CUE-DETR score to keep before non-max suppression",
    )
    cue_detr_predict.add_argument(
        "--min-distance-seconds",
        type=float,
        default=CueDetrOptions.min_distance_seconds,
        help="minimum time between emitted cue candidates after non-max suppression",
    )
    cue_detr_predict.add_argument(
        "--max-candidates",
        type=int,
        default=CueDetrOptions.max_candidates,
        help="maximum cue candidates to emit",
    )
    cue_detr_predict.add_argument(
        "--batch-size",
        type=int,
        default=CueDetrOptions.batch_size,
        help="spectrogram window batch size for model inference",
    )
    cue_detr_predict.add_argument(
        "--sample-rate",
        type=int,
        default=CueDetrOptions.sample_rate,
        help="audio sample rate used to generate the CUE-DETR spectrogram",
    )
    cue_detr_predict.add_argument(
        "--device",
        help="torch device override such as cuda or cpu; defaults to cuda when available",
    )
    cue_detr_predict.add_argument(
        "--json",
        action="store_true",
        help="print the prediction artifact as JSON",
    )

    benchmark_cue_detr_drops = subparsers.add_parser(
        "benchmark-cue-detr-drops",
        help="benchmark CUE-DETR cue candidates against Rekordbox drop_start cues",
    )
    benchmark_cue_detr_drops.add_argument("rekordbox_xml", type=Path, help="Rekordbox XML export path")
    benchmark_cue_detr_drops.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output folder for CUE-DETR drop benchmark reports",
    )
    benchmark_cue_detr_drops.add_argument(
        "--analysis-root",
        type=Path,
        help="optional analysis root containing tracks/*/analyzed-track.json for beatgrid snapping",
    )
    benchmark_cue_detr_drops.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_CUE_DETR_DROP_TOP_K,
        help="candidate rank depth to count as a hit",
    )
    benchmark_cue_detr_drops.add_argument(
        "--match-tolerance-ms",
        type=float,
        default=DEFAULT_CUE_DETR_DROP_MATCH_TOLERANCE_SECONDS * 1000.0,
        help="maximum absolute cue error, in milliseconds, counted as a match",
    )
    benchmark_cue_detr_drops.add_argument(
        "--snap-window-ms",
        type=float,
        default=DEFAULT_CUE_DETR_SNAP_WINDOW_SECONDS * 1000.0,
        help="maximum cue-to-beat distance, in milliseconds, for snapping candidates to the analyzed beatgrid",
    )
    benchmark_cue_detr_drops.add_argument(
        "--checkpoint",
        default=CueDetrOptions.checkpoint,
        help="Hugging Face model id or local checkpoint path",
    )
    benchmark_cue_detr_drops.add_argument(
        "--sensitivity",
        type=float,
        default=CueDetrOptions.sensitivity,
        help="minimum normalized CUE-DETR score to keep before non-max suppression",
    )
    benchmark_cue_detr_drops.add_argument(
        "--min-distance-seconds",
        type=float,
        default=CueDetrOptions.min_distance_seconds,
        help="minimum time between emitted cue candidates after non-max suppression",
    )
    benchmark_cue_detr_drops.add_argument(
        "--max-candidates",
        type=int,
        default=CueDetrOptions.max_candidates,
        help="maximum cue candidates to emit per track",
    )
    benchmark_cue_detr_drops.add_argument(
        "--batch-size",
        type=int,
        default=CueDetrOptions.batch_size,
        help="spectrogram window batch size for model inference",
    )
    benchmark_cue_detr_drops.add_argument(
        "--sample-rate",
        type=int,
        default=CueDetrOptions.sample_rate,
        help="audio sample rate used to generate the CUE-DETR spectrogram",
    )
    benchmark_cue_detr_drops.add_argument(
        "--device",
        help="torch device override such as cuda or cpu; defaults to cuda when available",
    )
    benchmark_cue_detr_drops.add_argument(
        "--limit",
        type=int,
        help="optional first-N track limit for smoke tests",
    )
    benchmark_cue_detr_drops.add_argument(
        "--json",
        action="store_true",
        help="print the benchmark summary as JSON",
    )

    edm98_predict = subparsers.add_parser(
        "edm98-predict",
        help="predict EDM section segments for one audio file using EDM-98/EDMFormer",
    )
    edm98_predict.add_argument("audio_path", type=Path, help="local MP3/WAV path to analyze")
    edm98_predict.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output edm98-sections.json path",
    )
    _add_edm98_options(edm98_predict)
    edm98_predict.add_argument(
        "--json",
        action="store_true",
        help="print the prediction artifact as JSON",
    )

    benchmark_edm98_drops = subparsers.add_parser(
        "benchmark-edm98-drops",
        help="benchmark EDM-98/EDMFormer drop segments against Rekordbox drop_start cues",
    )
    benchmark_edm98_drops.add_argument("rekordbox_xml", type=Path, help="Rekordbox XML export path")
    benchmark_edm98_drops.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output folder for EDM-98 drop benchmark reports",
    )
    benchmark_edm98_drops.add_argument(
        "--analysis-root",
        type=Path,
        help="optional analysis root containing tracks/*/analyzed-track.json for beatgrid snapping",
    )
    benchmark_edm98_drops.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_EDM98_DROP_TOP_K,
        help="candidate rank depth to count as a hit",
    )
    benchmark_edm98_drops.add_argument(
        "--match-tolerance-ms",
        type=float,
        default=DEFAULT_EDM98_DROP_MATCH_TOLERANCE_SECONDS * 1000.0,
        help="maximum absolute cue error, in milliseconds, counted as a match",
    )
    benchmark_edm98_drops.add_argument(
        "--snap-window-ms",
        type=float,
        default=DEFAULT_EDM98_SNAP_WINDOW_SECONDS * 1000.0,
        help="maximum segment-boundary-to-beat distance, in milliseconds, for snapping to the analyzed beatgrid",
    )
    benchmark_edm98_drops.add_argument(
        "--limit",
        type=int,
        help="optional first-N track limit for smoke tests",
    )
    _add_edm98_options(benchmark_edm98_drops)
    benchmark_edm98_drops.add_argument(
        "--json",
        action="store_true",
        help="print the benchmark summary as JSON",
    )

    nudge_mixplan = subparsers.add_parser(
        "nudge-mixplan",
        help="write a MixPlan copy with a small incoming transient nudge",
    )
    nudge_mixplan.add_argument("mix_plan", type=Path, help="MixPlan JSON path to nudge")
    nudge_mixplan.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output MixPlan JSON path with incoming source-start nudge applied",
    )
    nudge_mixplan.add_argument(
        "--asset-root",
        type=Path,
        help="optional directory used to resolve relative MixPlan asset sourceUri paths",
    )
    nudge_mixplan.add_argument(
        "--sample-rate",
        type=int,
        default=44_100,
        help="sample rate used while detecting transient offsets",
    )
    nudge_mixplan.add_argument(
        "--window-ms",
        type=float,
        default=80.0,
        help="milliseconds on either side of each anchor to search for the nearest transient",
    )
    nudge_mixplan.add_argument(
        "--max-nudge-ms",
        type=float,
        default=50.0,
        help="maximum absolute incoming-source nudge in milliseconds",
    )
    nudge_mixplan.add_argument(
        "--json",
        action="store_true",
        help="print the nudge summary as JSON",
    )

    gain_plan_drop_switch = subparsers.add_parser(
        "gain-plan-drop-switch",
        help="write a drop-switch MixPlan copy with energy-aware overlap gain planning",
    )
    gain_plan_drop_switch.add_argument("mix_plan", type=Path, help="MixPlan JSON path to gain-plan")
    gain_plan_drop_switch.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output MixPlan JSON path with adjusted overlap volume automation",
    )
    gain_plan_drop_switch.add_argument(
        "--report",
        required=True,
        type=Path,
        help="energy compatibility report JSON path",
    )
    gain_plan_drop_switch.add_argument(
        "--asset-root",
        type=Path,
        help="optional directory used to resolve relative MixPlan asset sourceUri paths",
    )
    gain_plan_drop_switch.add_argument(
        "--target-headroom-db",
        type=float,
        default=1.5,
        help="target dB gap between layered build RMS and incoming drop RMS",
    )
    gain_plan_drop_switch.add_argument(
        "--max-overlap-gain-reduction-db",
        type=float,
        default=4.0,
        help="maximum outgoing overlap volume reduction in dB",
    )
    gain_plan_drop_switch.add_argument(
        "--drop-energy-floor-db",
        type=float,
        default=-3.0,
        help="minimum allowed incoming-drop-vs-layered-build RMS delta before risk is reported",
    )
    gain_plan_drop_switch.add_argument(
        "--sample-rate",
        type=int,
        default=44_100,
        help="sample rate used while measuring source-window energy",
    )
    gain_plan_drop_switch.add_argument(
        "--json",
        action="store_true",
        help="print the gain-plan summary as JSON",
    )

    parse_transition_template = subparsers.add_parser(
        "parse-transition-template",
        help="parse a hand-authored bar/beat transition sheet into recipe or MixPlan JSON",
        description="Parse a hand-authored bar/beat transition sheet into recipe or MixPlan JSON",
    )
    parse_transition_template.add_argument("template", type=Path, help="transition sheet path")
    parse_transition_template.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output JSON path; concrete templates write MixPlan JSON, generic templates write recipe JSON",
    )
    parse_transition_template.add_argument(
        "--json",
        action="store_true",
        help="print the parse summary as JSON",
    )

    return parser


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2))


def _print_batch_human(result: BatchAnalysisResult) -> None:
    status = "ok" if result.ok else "failed"
    print(f"Batch analysis {status}")
    print(f"Manifest: {result.manifest_path}")
    print(f"Cache root: {result.cache_root}")
    print(
        f"Tracks: total={result.total_tracks}, analyzed={result.analyzed}, "
        f"skipped={result.skipped}, failed={result.failed}"
    )
    for track in result.tracks:
        line = f"- {track.track_id}: {track.status}"
        if track.reason:
            line += f" ({track.reason})"
        if track.artifact_path is not None:
            line += f" -> {track.artifact_path}"
        print(line)
    for error in result.errors:
        print(
            "error: "
            f"{error.get('trackId', '<manifest>')}: "
            f"{error.get('code', 'error')}: "
            f"{error.get('message', '')}",
            file=sys.stderr,
        )


def _manifest_error_payload(error: ManifestError, manifest_path: Path, cache_root: Path) -> dict[str, object]:
    return {
        "ok": False,
        "manifestPath": str(manifest_path),
        "cacheRoot": str(cache_root),
        "total": 0,
        "totalTracks": 0,
        "analyzed": 0,
        "skipped": 0,
        "failed": 0,
        "tracks": [],
        "errors": [error.to_dict()],
    }


def _cue_detr_options_from_args(args: argparse.Namespace) -> CueDetrOptions:
    return CueDetrOptions(
        checkpoint=args.checkpoint,
        sensitivity=args.sensitivity,
        min_distance_seconds=args.min_distance_seconds,
        max_candidates=args.max_candidates,
        batch_size=args.batch_size,
        sample_rate=args.sample_rate,
        device=args.device,
    )


def _add_edm98_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--checkpoint", help="local EDMFormer checkpoint path; defaults to EDM-98 package path")
    parser.add_argument("--config", help="local EDMFormer config path; defaults to EDM-98 package path")
    parser.add_argument("--musicfm-stat", help="local MusicFM stats JSON path; defaults to EDM-98 package path")
    parser.add_argument("--musicfm-model", help="local MusicFM checkpoint path; defaults to EDM-98 package path")
    parser.add_argument(
        "--device",
        default=Edm98Options.device,
        choices=["auto", "cpu", "cuda", "mps"],
        help="torch device for EDMFormer inference",
    )
    parser.add_argument(
        "--low-memory",
        action=argparse.BooleanOptionalAction,
        default=Edm98Options.low_memory,
        help="load MuQ/MusicFM feature models only while extracting each file",
    )
    parser.add_argument("--hf-cache-dir", help="Hugging Face cache directory for MuQ/MusicFM upstream assets")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="use only locally cached Hugging Face-backed assets",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="use an ephemeral Hugging Face cache for this run",
    )


def _edm98_options_from_args(args: argparse.Namespace) -> Edm98Options:
    return Edm98Options(
        checkpoint=args.checkpoint,
        config=args.config,
        musicfm_stat=args.musicfm_stat,
        musicfm_model=args.musicfm_model,
        device=args.device,
        low_memory=args.low_memory,
        hf_cache_dir=args.hf_cache_dir,
        offline=args.offline,
        no_cache=args.no_cache,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    probe_runner: ProbeRunner | None = None,
    signal_analyzer: SignalAnalyzer | None = None,
    timing_benchmark_runner=None,
    semantic_benchmark_runner=None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "classify":
            _print_json(classify_stub(args.audio_path))
            return 0

        if args.command == "analyze":
            artifact_path = analyze_stub(args.audio_path, args.out)
            _print_json(
                {
                    "ok": True,
                    "artifact": "analyzed-track",
                    "outputPath": str(artifact_path),
                }
            )
            return 0

        if args.command == "analyze-batch":
            try:
                result = analyze_repository_manifest(
                    args.repository_manifest,
                    args.out,
                    ffprobe_path=args.ffprobe,
                    force=args.force,
                    parameters_hash=args.parameters_hash,
                    probe_runner=probe_runner,
                    signal_analyzer=signal_analyzer,
                    section_backend=args.section_backend,
                )
            except ManifestError as exc:
                if args.json:
                    _print_json(_manifest_error_payload(exc, args.repository_manifest, args.out))
                else:
                    print(f"autodj-analysis: {exc.message}", file=sys.stderr)
                return 1

            if args.json:
                _print_json(result.to_dict())
            else:
                _print_batch_human(result)
            return 0 if result.ok else 1

        if args.command == "debug-waveform":
            decoded_audio = load_audio(args.audio_path, target_sample_rate=args.sample_rate)
            artifact = build_debug_waveform_artifact(
                args.track_id or args.audio_path.stem,
                decoded_audio,
                analyzer_version=__version__,
                target_point_count=args.points,
                low_cutoff_hz=args.low_cutoff_hz,
                high_cutoff_hz=args.high_cutoff_hz,
            )
            output_path = write_debug_waveform_artifact(args.out, artifact)
            payload = {
                "ok": True,
                "artifact": "debug-waveform",
                "outputPath": str(output_path),
                "points": len(artifact["points"]),
                "durationSeconds": artifact["durationSeconds"],
            }
            if args.json:
                _print_json(payload)
            else:
                print(
                    "Debug waveform written: "
                    f"{output_path} ({payload['points']} points, "
                    f"{payload['durationSeconds']} seconds)"
                )
            return 0

        if args.command == "apply-rekordbox-xml":
            output_path = apply_rekordbox_xml_file(
                args.analyzed_track,
                args.rekordbox_xml,
                args.out,
                track_name=args.track_name,
            )
            payload = {
                "ok": True,
                "artifact": "analyzed-track",
                "outputPath": str(output_path),
                "source": "rekordbox.xml",
            }
            if args.json:
                _print_json(payload)
            else:
                print(f"Rekordbox overrides written: {output_path}")
            return 0

        if args.command == "export-rekordbox-xml":
            output_path = export_analyzed_track_to_rekordbox_xml_file(
                args.analyzed_track,
                args.out,
                source_uri=args.source_uri,
                track_name=args.track_name,
                include_cue_points=args.include_cue_points,
                cue_policy=args.cue_policy,
                max_hot_cues=args.max_hot_cues,
                time_precision=args.time_precision,
            )
            payload = {
                "ok": True,
                "artifact": "rekordbox-xml",
                "outputPath": str(output_path),
                "source": "analyzed-track",
            }
            if args.json:
                _print_json(payload)
            else:
                print(f"Rekordbox XML written: {output_path}")
            return 0

        if args.command == "evaluate-rekordbox":
            output_path = write_rekordbox_evaluation_report(
                args.analyzed_track,
                args.rekordbox_xml,
                args.out,
                track_name=args.track_name,
                options=RekordboxEvaluationOptions(
                    candidate_name=args.candidate_name,
                    processing_seconds=args.processing_seconds,
                    timeline_offset_seconds=args.timeline_offset_seconds,
                    timeline_offset_policy=args.timeline_offset_policy,
                ),
            )
            payload = {
                "ok": True,
                "artifact": "rekordbox-evaluation-report",
                "outputPath": str(output_path),
                "source": "rekordbox.xml",
            }
            if args.json:
                _print_json(payload)
            else:
                print(f"Rekordbox evaluation report written: {output_path}")
            return 0

        if args.command == "benchmark-timing":
            candidates = tuple(candidate.strip() for candidate in args.candidates.split(",") if candidate.strip())
            runner = timing_benchmark_runner or run_timing_benchmark
            summary = runner(
                load_timing_benchmark_cases(args.cases),
                args.out,
                candidates=candidates,
                analysis_sample_rate=args.sample_rate,
                debug_waveform_points=args.debug_waveform_points,
            )
            if args.json:
                _print_json(summary)
            else:
                print(f"Timing benchmark written: {args.out / 'timing-benchmark-summary.json'}")
            return 0

        if args.command == "benchmark-sections":
            candidates = tuple(candidate.strip() for candidate in args.candidates.split(",") if candidate.strip())
            runner = semantic_benchmark_runner or run_semantic_section_benchmark
            summary = runner(
                load_semantic_benchmark_cases(args.rekordbox_xml),
                args.out,
                candidates=candidates,
                analysis_sample_rate=args.sample_rate,
                debug_waveform_points=args.debug_waveform_points,
            )
            if args.json:
                _print_json(summary)
            else:
                print(f"Semantic section benchmark written: {args.out / 'semantic-section-benchmark-summary.json'}")
            return 0

        if args.command == "render-mixplan":
            result = render_mix_plan_file(
                args.mix_plan,
                args.out,
                RenderOptions(
                    sample_rate=args.sample_rate,
                    asset_root=args.asset_root,
                ),
            )
            if args.json:
                _print_json(result.to_dict())
            else:
                print(f"MixPlan audition WAV written: {result.output_wav}")
                print(f"Render summary written: {result.summary_path}")
                print(f"State trace written: {result.trace_path}")
            return 0

        if args.command == "rank-drop-anchors":
            output_path = rank_drop_anchors_file(
                args.analyzed_track,
                args.out,
                options=DropAnchorRankerOptions(max_candidates=args.max_candidates),
            )
            if args.json:
                _print_json(json.loads(output_path.read_text(encoding="utf-8")))
            else:
                print(f"Drop-anchor ranking written: {output_path}")
            return 0

        if args.command == "benchmark-drop-anchors":
            summary = run_drop_anchor_benchmark(
                args.rekordbox_xml,
                args.analysis_root,
                args.out,
                top_k=args.top_k,
                match_tolerance_seconds=args.match_tolerance_ms / 1000.0,
                ranker_options=DropAnchorRankerOptions(max_candidates=args.max_candidates),
            )
            if args.json:
                _print_json(summary)
            else:
                print(f"Drop-anchor benchmark written: {args.out / 'drop-anchor-benchmark-summary.json'}")
            return 0

        if args.command == "cue-detr-predict":
            output_path = predict_cue_detr_file(
                args.audio_path,
                args.out,
                options=_cue_detr_options_from_args(args),
            )
            if args.json:
                _print_json(json.loads(output_path.read_text(encoding="utf-8")))
            else:
                print(f"CUE-DETR cue candidates written: {output_path}")
            return 0

        if args.command == "benchmark-cue-detr-drops":
            summary = run_cue_detr_drop_benchmark(
                args.rekordbox_xml,
                args.out,
                analysis_root=args.analysis_root,
                top_k=args.top_k,
                match_tolerance_seconds=args.match_tolerance_ms / 1000.0,
                snap_window_seconds=args.snap_window_ms / 1000.0,
                cue_detr_options=_cue_detr_options_from_args(args),
                limit=args.limit,
            )
            if args.json:
                _print_json(summary)
            else:
                print(f"CUE-DETR drop benchmark written: {args.out / 'cue-detr-drop-benchmark-summary.json'}")
            return 0

        if args.command == "edm98-predict":
            output_path = predict_edm98_file(
                args.audio_path,
                args.out,
                options=_edm98_options_from_args(args),
            )
            if args.json:
                _print_json(json.loads(output_path.read_text(encoding="utf-8")))
            else:
                print(f"EDM-98 section prediction written: {output_path}")
            return 0

        if args.command == "benchmark-edm98-drops":
            summary = run_edm98_drop_benchmark(
                args.rekordbox_xml,
                args.out,
                analysis_root=args.analysis_root,
                top_k=args.top_k,
                match_tolerance_seconds=args.match_tolerance_ms / 1000.0,
                snap_window_seconds=args.snap_window_ms / 1000.0,
                edm98_options=_edm98_options_from_args(args),
                limit=args.limit,
            )
            if args.json:
                _print_json(summary)
            else:
                print(f"EDM-98 drop benchmark written: {args.out / 'edm98-drop-benchmark-summary.json'}")
            return 0

        if args.command == "nudge-mixplan":
            result = nudge_mix_plan_file(
                args.mix_plan,
                args.out,
                NudgeOptions(
                    sample_rate=args.sample_rate,
                    asset_root=args.asset_root,
                    window_seconds=args.window_ms / 1000.0,
                    max_nudge_seconds=args.max_nudge_ms / 1000.0,
                ),
            )
            if args.json:
                _print_json(result.to_dict())
            else:
                print(f"Nudged MixPlan written: {result.output_mix_plan}")
                print(f"Incoming nudge: {result.nudge_seconds * 1000.0:.1f} ms")
            return 0

        if args.command == "gain-plan-drop-switch":
            result = gain_plan_drop_switch_file(
                args.mix_plan,
                args.out,
                args.report,
                GainPlanOptions(
                    sample_rate=args.sample_rate,
                    asset_root=args.asset_root,
                    target_headroom_db=args.target_headroom_db,
                    max_overlap_gain_reduction_db=args.max_overlap_gain_reduction_db,
                    drop_energy_floor_db=args.drop_energy_floor_db,
                ),
            )
            if args.json:
                _print_json(result.to_dict())
            else:
                print(f"Gain-planned MixPlan written: {result.output_mix_plan}")
                print(f"Energy report written: {result.report_path}")
                print(f"Verdict: {result.verdict}")
                print(f"Outgoing overlap trim: {result.outgoing_overlap_trim_db:.2f} dB")
            return 0

        if args.command == "parse-transition-template":
            result = parse_transition_template_file(args.template, args.out)
            if args.json:
                _print_json(result.to_dict())
            else:
                print(f"Transition template parsed: {result.output_path}")
            return 0
    except OSError as exc:
        print(f"autodj-analysis: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"autodj-analysis: {exc}", file=sys.stderr)
        return 2

    parser.error(f"unsupported command: {args.command}")
    return 2
