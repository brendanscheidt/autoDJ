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
from .canonical_audio import (
    CANONICAL_AUDIO_FILENAME,
    CANONICAL_AUDIO_METADATA_FILENAME,
    CANONICAL_FALLBACK_SAMPLE_RATE,
    CANONICAL_TIMELINE_POLICY,
    CanonicalAudioError,
    CanonicalAudioOptions,
    canonicalize_repository_manifest,
)
from .debug_waveform import build_debug_waveform_artifact, write_debug_waveform_artifact
from .beatgrid_phase import (
    BeatgridPhaseOptions,
    parse_phase_anchor,
    refine_beatgrid_phase_file,
)
from .drop_wall import DropWallOptions, detect_drop_wall_file
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
from .key_benchmark import (
    DEFAULT_KEY_ANALYSIS_SAMPLE_RATE,
    DEFAULT_KEY_CANDIDATES,
    load_key_benchmark_cases,
    run_key_benchmark,
)
from .manifest import ManifestError
from .mixplan_energy import GainPlanOptions, gain_plan_drop_switch_file
from .mixplan_nudge import NudgeOptions, nudge_mix_plan_file
from .mixplan_renderer import RenderOptions, render_mix_plan_file
from .probe import ProbeRunner
from .rekordbox_xml import apply_rekordbox_semantic_xml_file, apply_rekordbox_xml_file
from .rekordbox_xml import export_analyzed_track_to_rekordbox_xml_file
from .tempo_stretch import (
    DEFAULT_TEMPO_STRETCH_BACKENDS,
    TempoStretchOptions,
    run_tempo_stretch_smoke,
    stretch_audio_file,
)
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
        "--canonical-audio-root",
        type=Path,
        help=(
            "optional canonical PCM cache root from canonicalize-audio; when set, "
            "signal analysis uses tracks/<track-id>/canonical.wav"
        ),
    )
    analyze_batch.add_argument(
        "--json",
        action="store_true",
        help="print the batch summary as JSON",
    )

    canonicalize_audio = subparsers.add_parser(
        "canonicalize-audio",
        help="decode repository tracks into shared canonical PCM artifacts",
    )
    canonicalize_audio.add_argument(
        "repository_manifest",
        type=Path,
        help="repository-manifest.json file produced by the repository scanner",
    )
    canonicalize_audio.add_argument(
        "--out",
        required=True,
        type=Path,
        help="metadata cache root where canonical.wav and canonical-audio.json will be written",
    )
    canonicalize_audio.add_argument(
        "--ffmpeg",
        default="ffmpeg",
        help="ffmpeg executable path or name",
    )
    canonicalize_audio.add_argument(
        "--ffprobe",
        default="ffprobe",
        help="ffprobe executable path or name",
    )
    canonicalize_audio.add_argument(
        "--force",
        action="store_true",
        help="rewrite canonical artifacts even when cache freshness checks pass",
    )
    canonicalize_audio.add_argument(
        "--sample-rate",
        type=int,
        help=(
            "optional target sample rate for canonical WAVs; omit to preserve "
            "44.1/48 kHz sources and use the fallback for other rates"
        ),
    )
    canonicalize_audio.add_argument(
        "--fallback-sample-rate",
        type=int,
        default=CANONICAL_FALLBACK_SAMPLE_RATE,
        help="sample rate used when source sample rate is unsupported or unavailable",
    )
    canonicalize_audio.add_argument(
        "--json",
        action="store_true",
        help="print the canonicalization summary as JSON",
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

    apply_rekordbox_semantics = subparsers.add_parser(
        "apply-rekordbox-semantics",
        help="apply only Rekordbox XML semantic cue labels while preserving AutoDJ tempo/grid/key",
    )
    apply_rekordbox_semantics.add_argument("analyzed_track", type=Path, help="input analyzed-track.json path")
    apply_rekordbox_semantics.add_argument("rekordbox_xml", type=Path, help="Rekordbox XML export path")
    apply_rekordbox_semantics.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output analyzed-track JSON path with Rekordbox semantic labels",
    )
    apply_rekordbox_semantics.add_argument(
        "--track-name",
        help="optional Rekordbox TRACK Name to import when the XML has multiple tracks",
    )
    apply_rekordbox_semantics.add_argument(
        "--json",
        action="store_true",
        help="print the semantic override summary as JSON",
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

    benchmark_keys = subparsers.add_parser(
        "benchmark-keys",
        help="run key detector candidates against Rekordbox Tonality truth",
    )
    benchmark_keys.add_argument(
        "rekordbox_xml",
        type=Path,
        help="Rekordbox XML export containing one or more TRACK Tonality values",
    )
    benchmark_keys.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output directory for candidate key artifacts and benchmark reports",
    )
    benchmark_keys.add_argument(
        "--candidates",
        default=",".join(DEFAULT_KEY_CANDIDATES),
        help="comma-separated key detector candidate names to run",
    )
    benchmark_keys.add_argument(
        "--sample-rate",
        type=int,
        default=DEFAULT_KEY_ANALYSIS_SAMPLE_RATE,
        help="shared decoded audio sample rate for in-process key candidates",
    )
    benchmark_keys.add_argument(
        "--json",
        action="store_true",
        help="print the benchmark summary as JSON",
    )

    tempo_stretch_smoke = subparsers.add_parser(
        "tempo-stretch-smoke",
        help="smoke-test pitch-preserving tempo-stretch backends on one audio file",
    )
    tempo_stretch_smoke.add_argument(
        "--audio",
        required=True,
        type=Path,
        help="local MP3/WAV path to stretch",
    )
    tempo_stretch_smoke.add_argument(
        "--source-bpm",
        required=True,
        type=float,
        help="source/native BPM for the input audio",
    )
    tempo_stretch_smoke.add_argument(
        "--target-bpm",
        required=True,
        type=float,
        help="target effective BPM for the stretched output",
    )
    tempo_stretch_smoke.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output directory for per-backend WAVs and stretch reports",
    )
    tempo_stretch_smoke.add_argument(
        "--backends",
        default=",".join(DEFAULT_TEMPO_STRETCH_BACKENDS),
        help="comma-separated tempo-stretch backends to smoke-test",
    )
    tempo_stretch_smoke.add_argument(
        "--sample-rate",
        type=int,
        default=44_100,
        help="WAV sample rate used for backend inputs and outputs",
    )
    tempo_stretch_smoke.add_argument(
        "--quality",
        default="fine",
        choices=("fine", "fine-centre", "fast"),
        help="backend quality mode where supported",
    )
    tempo_stretch_smoke.add_argument(
        "--target-bpm-bias",
        type=float,
        default=0.0,
        help="optional tiny BPM bias added to the requested target before rendering; 0 disables calibration",
    )
    tempo_stretch_smoke.add_argument(
        "--json",
        action="store_true",
        help="print the smoke summary as JSON",
    )

    stretch_audio = subparsers.add_parser(
        "stretch-audio",
        help="render one pitch-preserving tempo-stretched WAV",
    )
    stretch_audio.add_argument("audio_path", type=Path, help="local MP3/WAV path to stretch")
    stretch_audio.add_argument(
        "--source-bpm",
        required=True,
        type=float,
        help="source/native BPM for the input audio",
    )
    stretch_audio.add_argument(
        "--target-bpm",
        required=True,
        type=float,
        help="target effective BPM for the stretched output",
    )
    stretch_audio.add_argument(
        "--backend",
        default="rubberband",
        help="tempo-stretch backend name, e.g. rubberband or soundstretch",
    )
    stretch_audio.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output WAV path",
    )
    stretch_audio.add_argument(
        "--report",
        required=True,
        type=Path,
        help="output JSON report path",
    )
    stretch_audio.add_argument(
        "--sample-rate",
        type=int,
        default=44_100,
        help="WAV sample rate used for backend input and output",
    )
    stretch_audio.add_argument(
        "--quality",
        default="fine",
        choices=("fine", "fine-centre", "fast"),
        help="backend quality mode where supported",
    )
    stretch_audio.add_argument(
        "--target-bpm-bias",
        type=float,
        default=0.0,
        help="optional tiny BPM bias added to the requested target before rendering; 0 disables calibration",
    )
    stretch_audio.add_argument(
        "--json",
        action="store_true",
        help="print the stretch report as JSON",
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
        "--tempo-backend",
        default="soundstretch",
        choices=("soundstretch", "rubberband"),
        help="default backend for tempoPlan preserve-pitch renders without an explicit backend",
    )
    render_mixplan.add_argument(
        "--tempo-quality",
        default="standard",
        help="default quality mode for tempoPlan preserve-pitch renders",
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

    drop_wall_debug = subparsers.add_parser(
        "drop-wall-debug",
        help="detect and visualize the sharp drop-wall transient around an approximate drop time",
    )
    drop_wall_debug.add_argument("audio_path", type=Path, help="local audio path to inspect")
    drop_wall_debug.add_argument(
        "--time",
        required=True,
        type=float,
        help="approximate drop time in source seconds, usually a nearby beatgrid/cue time",
    )
    drop_wall_debug.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output drop-wall-debug JSON path",
    )
    drop_wall_debug.add_argument(
        "--svg",
        type=Path,
        help="optional output SVG path for visual inspection",
    )
    drop_wall_debug.add_argument(
        "--track-id",
        help="optional track id to store in the artifact; defaults to the audio filename stem",
    )
    drop_wall_debug.add_argument(
        "--sample-rate",
        type=int,
        default=44_100,
        help="analysis sample rate",
    )
    drop_wall_debug.add_argument(
        "--search-window-ms",
        type=float,
        default=450.0,
        help="search window on each side of --time in milliseconds",
    )
    drop_wall_debug.add_argument(
        "--preferred-window-ms",
        type=float,
        default=120.0,
        help="preferred candidate window around --time in milliseconds",
    )
    drop_wall_debug.add_argument(
        "--preferred-score-ratio",
        type=float,
        default=0.60,
        help="minimum score ratio for a near candidate to beat a farther wall",
    )
    drop_wall_debug.add_argument(
        "--json",
        action="store_true",
        help="print the selected wall summary as JSON",
    )

    refine_beatgrid_phase = subparsers.add_parser(
        "refine-beatgrid-phase",
        help="shift a whole beatgrid by consensus drop-wall phase correction",
    )
    refine_beatgrid_phase.add_argument("analyzed_track", type=Path, help="input analyzed-track.json path")
    refine_beatgrid_phase.add_argument("audio_path", type=Path, help="local audio path matching the analyzed track")
    refine_beatgrid_phase.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output refined analyzed-track.json path",
    )
    refine_beatgrid_phase.add_argument(
        "--report",
        required=True,
        type=Path,
        help="output beatgrid-phase-refinement-report.json path",
    )
    refine_beatgrid_phase.add_argument(
        "--smoke-dir",
        type=Path,
        help="optional directory for short metronome WAVs around accepted drop anchors",
    )
    refine_beatgrid_phase.add_argument(
        "--anchor-time",
        action="append",
        default=[],
        help="optional drop anchor in seconds or label=seconds form; repeatable. Defaults to drop cuePoints.",
    )
    refine_beatgrid_phase.add_argument(
        "--sample-rate",
        type=int,
        default=44_100,
        help="analysis sample rate",
    )
    refine_beatgrid_phase.add_argument(
        "--search-window-ms",
        type=float,
        default=450.0,
        help="drop-wall search window on each side of each anchor in milliseconds",
    )
    refine_beatgrid_phase.add_argument(
        "--preferred-window-ms",
        type=float,
        default=120.0,
        help="preferred drop-wall candidate window around each anchor in milliseconds",
    )
    refine_beatgrid_phase.add_argument(
        "--min-wall-score",
        type=float,
        default=0.45,
        help="minimum selected drop-wall score for an anchor to vote on phase",
    )
    refine_beatgrid_phase.add_argument(
        "--max-wall-offset-ms",
        type=float,
        default=120.0,
        help="maximum selected wall distance from the semantic anchor in milliseconds",
    )
    refine_beatgrid_phase.add_argument(
        "--consensus-tolerance-ms",
        type=float,
        default=15.0,
        help="maximum disagreement between accepted anchor phase corrections in milliseconds",
    )
    refine_beatgrid_phase.add_argument(
        "--min-consensus-anchors",
        type=int,
        default=1,
        help="minimum accepted inlier anchors required to apply the shift",
    )
    refine_beatgrid_phase.add_argument(
        "--json",
        action="store_true",
        help="print the refinement summary as JSON",
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
        "--micro-align-ms",
        type=float,
        default=0.0,
        help="maximum post-transient micro-alignment adjustment in milliseconds",
    )
    nudge_mixplan.add_argument(
        "--micro-window-ms",
        type=float,
        default=30.0,
        help="milliseconds on either side of the selected transient used for micro-alignment correlation",
    )
    nudge_mixplan.add_argument(
        "--min-micro-improvement",
        type=float,
        default=0.03,
        help="minimum correlation improvement required before applying micro-alignment",
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


def _print_canonical_audio_human(summary: dict[str, object]) -> None:
    status = "ok" if summary.get("ok") else "failed"
    print(f"Canonical audio {status}")
    print(f"Manifest: {summary.get('manifestPath')}")
    print(f"Output root: {summary.get('outputRoot')}")
    print(
        "Tracks: "
        f"total={summary.get('total', 0)}, "
        f"canonicalized={summary.get('canonicalized', 0)}, "
        f"skipped={summary.get('skipped', 0)}, "
        f"failed={summary.get('failed', 0)}"
    )
    for track in summary.get("tracks", []):
        if not isinstance(track, dict):
            continue
        line = f"- {track.get('trackId', '<unknown>')}: {track.get('status', '<unknown>')}"
        if track.get("canonicalPath"):
            line += f" -> {track['canonicalPath']}"
        error = track.get("error")
        if isinstance(error, dict):
            line += f" ({error.get('code', 'error')}: {error.get('message', '')})"
        print(line)


def _timeline_policy_for_audio_path(path: Path) -> str:
    if path.name == CANONICAL_AUDIO_FILENAME and (path.parent / CANONICAL_AUDIO_METADATA_FILENAME).exists():
        return CANONICAL_TIMELINE_POLICY
    return "direct-audio-path"


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
    key_benchmark_runner=None,
    tempo_stretch_runner=None,
    tempo_stretch_smoke_runner=None,
    canonical_audio_runner=None,
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
                    canonical_audio_root=args.canonical_audio_root,
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

        if args.command == "canonicalize-audio":
            runner = canonical_audio_runner or canonicalize_repository_manifest
            try:
                summary = runner(
                    args.repository_manifest,
                    args.out,
                    options=CanonicalAudioOptions(
                        ffmpeg_path=args.ffmpeg,
                        ffprobe_path=args.ffprobe,
                        force=args.force,
                        target_sample_rate=args.sample_rate,
                        fallback_sample_rate=args.fallback_sample_rate,
                    ),
                )
            except ManifestError as exc:
                summary = _manifest_error_payload(exc, args.repository_manifest, args.out)
                summary["artifact"] = "canonical-audio-batch"
                if not args.json:
                    print(f"autodj-analysis: {exc.message}", file=sys.stderr)
                    return 1
            except CanonicalAudioError as exc:
                summary = {
                    "ok": False,
                    "artifact": "canonical-audio-batch",
                    "manifestPath": str(args.repository_manifest),
                    "outputRoot": str(args.out),
                    "total": 0,
                    "canonicalized": 0,
                    "skipped": 0,
                    "failed": 1,
                    "tracks": [],
                    "errors": [exc.to_dict()],
                }
                if not args.json:
                    print(f"autodj-analysis: {exc.message}", file=sys.stderr)
                    return 1

            if args.json:
                _print_json(summary)
            else:
                _print_canonical_audio_human(summary)
            return 0 if summary.get("ok") else 1

        if args.command == "debug-waveform":
            decoded_audio = load_audio(args.audio_path, target_sample_rate=args.sample_rate)
            artifact = build_debug_waveform_artifact(
                args.track_id or args.audio_path.stem,
                decoded_audio,
                analyzer_version=__version__,
                source_path=decoded_audio.source_path,
                timeline_policy=_timeline_policy_for_audio_path(decoded_audio.source_path),
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
                "sourceTimelinePolicy": artifact["source"]["timelinePolicy"],
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

        if args.command == "apply-rekordbox-semantics":
            output_path = apply_rekordbox_semantic_xml_file(
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
                "mode": "semantic_only",
            }
            if args.json:
                _print_json(payload)
            else:
                print(f"Rekordbox semantic labels written: {output_path}")
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

        if args.command == "benchmark-keys":
            candidates = tuple(candidate.strip() for candidate in args.candidates.split(",") if candidate.strip())
            runner = key_benchmark_runner or run_key_benchmark
            summary = runner(
                load_key_benchmark_cases(args.rekordbox_xml),
                args.out,
                candidates=candidates,
                analysis_sample_rate=args.sample_rate,
            )
            if args.json:
                _print_json(summary)
            else:
                print(f"Key benchmark written: {args.out / 'key-benchmark-summary.json'}")
            return 0

        if args.command == "tempo-stretch-smoke":
            backends = tuple(candidate.strip() for candidate in args.backends.split(",") if candidate.strip())
            runner = tempo_stretch_smoke_runner or run_tempo_stretch_smoke
            summary = runner(
                args.audio,
                args.out,
                source_bpm=args.source_bpm,
                target_bpm=args.target_bpm,
                backends=backends,
                sample_rate=args.sample_rate,
                quality=args.quality,
                target_bpm_bias=args.target_bpm_bias,
            )
            if args.json:
                _print_json(summary)
            else:
                print(f"Tempo-stretch smoke outputs written: {args.out}")
            return 0 if summary.get("ok") else 1

        if args.command == "stretch-audio":
            runner = tempo_stretch_runner or stretch_audio_file
            result = runner(
                args.audio_path,
                args.out,
                report_path=args.report,
                options=TempoStretchOptions(
                    source_bpm=args.source_bpm,
                    target_bpm=args.target_bpm,
                    backend=args.backend,
                    sample_rate=args.sample_rate,
                    quality=args.quality,
                    target_bpm_bias=args.target_bpm_bias,
                ),
            )
            payload = result.to_dict() if hasattr(result, "to_dict") else result
            if args.json:
                _print_json(payload)
            else:
                print(f"Tempo-stretched WAV written: {args.out}")
                print(f"Tempo-stretch report written: {args.report}")
            return 0 if payload.get("ok", True) else 1

        if args.command == "render-mixplan":
            result = render_mix_plan_file(
                args.mix_plan,
                args.out,
                RenderOptions(
                    sample_rate=args.sample_rate,
                    asset_root=args.asset_root,
                    tempo_backend=args.tempo_backend,
                    tempo_quality=args.tempo_quality,
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

        if args.command == "drop-wall-debug":
            output_path = detect_drop_wall_file(
                args.audio_path,
                args.out,
                approximate_time_seconds=args.time,
                svg_path=args.svg,
                track_id=args.track_id,
                options=DropWallOptions(
                    sample_rate=args.sample_rate,
                    search_window_seconds=args.search_window_ms / 1000.0,
                    preferred_window_seconds=args.preferred_window_ms / 1000.0,
                    preferred_score_ratio=args.preferred_score_ratio,
                ),
            )
            artifact = json.loads(output_path.read_text(encoding="utf-8"))
            payload = {
                "ok": True,
                "artifact": "drop-wall-debug",
                "outputPath": str(output_path),
                "svgPath": str(args.svg) if args.svg is not None else None,
                "selectedWall": artifact["selectedWall"],
            }
            if args.json:
                _print_json(payload)
            else:
                selected = artifact["selectedWall"]
                print(f"Drop-wall debug written: {output_path}")
                if args.svg is not None:
                    print(f"Drop-wall SVG written: {args.svg}")
                print(
                    "Selected wall: "
                    f"{selected['timeSeconds']:.3f}s "
                    f"({selected['offsetMilliseconds']:+.1f} ms, score {selected['score']:.3f})"
                )
            return 0

        if args.command == "refine-beatgrid-phase":
            output_path = refine_beatgrid_phase_file(
                args.analyzed_track,
                args.audio_path,
                args.out,
                report_path=args.report,
                smoke_dir=args.smoke_dir,
                anchors=tuple(parse_phase_anchor(value) for value in args.anchor_time),
                options=BeatgridPhaseOptions(
                    sample_rate=args.sample_rate,
                    search_window_seconds=args.search_window_ms / 1000.0,
                    preferred_window_seconds=args.preferred_window_ms / 1000.0,
                    min_wall_score=args.min_wall_score,
                    max_wall_offset_seconds=args.max_wall_offset_ms / 1000.0,
                    consensus_tolerance_seconds=args.consensus_tolerance_ms / 1000.0,
                    min_consensus_anchors=args.min_consensus_anchors,
                ),
            )
            report = json.loads(args.report.read_text(encoding="utf-8"))
            payload = {
                "ok": True,
                "artifact": "beatgrid-phase-refinement",
                "outputPath": str(output_path),
                "reportPath": str(args.report),
                "smokeDir": str(args.smoke_dir) if args.smoke_dir is not None else None,
                "applied": report["applied"],
                "phaseShiftMilliseconds": report["phaseShiftMilliseconds"],
                "acceptedAnchorCount": report["acceptedAnchorCount"],
                "consensusAnchorCount": report["consensusAnchorCount"],
                "warnings": report["warnings"],
            }
            if args.json:
                _print_json(payload)
            else:
                print(f"Refined analyzed track written: {output_path}")
                print(f"Phase report written: {args.report}")
                if args.smoke_dir is not None:
                    print(f"Metronome smoke WAVs written under: {args.smoke_dir}")
                print(
                    "Beatgrid phase shift: "
                    f"{report['phaseShiftMilliseconds']:+.3f} ms "
                    f"({'applied' if report['applied'] else 'not applied'})"
                )
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
                    micro_alignment_seconds=args.micro_align_ms / 1000.0,
                    micro_alignment_window_seconds=args.micro_window_ms / 1000.0,
                    min_micro_alignment_improvement=args.min_micro_improvement,
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
