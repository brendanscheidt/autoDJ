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
from .evaluation import (
    DEFAULT_SEMANTIC_ANALYSIS_SAMPLE_RATE,
    DEFAULT_SEMANTIC_CANDIDATES,
    DEFAULT_SEMANTIC_DEBUG_WAVEFORM_POINTS,
    DEFAULT_TIMING_ANALYSIS_SAMPLE_RATE,
    DEFAULT_TIMING_CANDIDATES,
    DEFAULT_TIMING_DEBUG_WAVEFORM_POINTS,
    RekordboxEvaluationOptions,
    load_semantic_benchmark_cases,
    load_timing_benchmark_cases,
    run_semantic_section_benchmark,
    run_timing_benchmark,
    write_rekordbox_evaluation_report,
)
from .genre import classify_stub
from .audio_io import load_audio
from .manifest import ManifestError
from .probe import ProbeRunner
from .rekordbox_xml import apply_rekordbox_xml_file


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
    except OSError as exc:
        print(f"autodj-analysis: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"autodj-analysis: {exc}", file=sys.stderr)
        return 2

    parser.error(f"unsupported command: {args.command}")
    return 2
