"""Generate a continuous AutoDJ POC set from analyzed tracks.

This module intentionally reuses the proven pairwise planner path:

1. choose a diversified track order;
2. generate each pair transition with the C++ planner;
3. run the Python nudge pass on every transition;
4. run the drop-switch energy/gain post-pass for drop switches;
5. merge the pair MixPlans onto one continuous timeline;
6. render one WAV.

It is a POC set builder, not the final set-planning engine. The legacy
``tools/scripts/generate_full_set_poc.py`` entry point imports this module.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import random
import shutil
import shlex
import subprocess
from typing import Any, Sequence
from urllib.parse import unquote, urlparse


def host_path(value: str | Path) -> Path:
    """Normalize a Windows path when this module is running inside WSL."""
    raw = str(value)
    normalized = raw.replace("\\", "/")
    if len(normalized) >= 3 and normalized[0] == "/" and normalized[2] == ":" and normalized[1].isalpha():
        wsl_candidate = Path(f"/mnt/{normalized[1].lower()}{normalized[3:]}")
        if wsl_candidate.exists() or Path("/mnt").exists():
            return wsl_candidate
    if len(raw) >= 3 and raw[1] == ":" and raw[2] in ("\\", "/"):
        drive = raw[0].lower()
        rest = raw[3:].replace("\\", "/")
        wsl_candidate = Path(f"/mnt/{drive}/{rest}")
        if wsl_candidate.exists() or Path("/mnt").exists():
            return wsl_candidate
    return Path(raw)


PROJECT_ROOT = host_path(r"C:\Users\Brendan\Dev\AudioProj")
DEFAULT_AUDIO_FOLDER = host_path(r"C:\Users\Brendan\Desktop\AutoDJTestDubstep")
DEFAULT_ANALYSIS_ROOT = (
    PROJECT_ROOT
    / ".autodj-cache"
    / "transition-auditions"
    / "keyed-rekordbox-semantic-truth-20260524-095821"
    / "analysis"
)
DEFAULT_WASHOUT_SWEEP_URI = "C:/Users/Brendan/Desktop/sweep.wav"


@dataclass(frozen=True)
class TrackRow:
    track_id: str
    artifact_path: Path
    source_uri: str
    normalized_bpm: float
    camelot_key: str
    key_confidence: float
    duration_seconds: float
    build_count: int
    drop_count: int

    @property
    def can_outgoing_drop_switch(self) -> bool:
        return self.build_count >= 2 and self.drop_count >= 2

    @property
    def can_incoming_drop_switch(self) -> bool:
        return self.drop_count >= 1

    @property
    def can_wash_out(self) -> bool:
        return self.drop_count >= 1


@dataclass
class CurrentPlacement:
    track_id: str
    placement_id: str
    deck: int
    source_start: float
    timeline_start: float
    tempo_ratio: float


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a continuous AutoDJ full-set POC WAV.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--audio-folder", type=Path, default=DEFAULT_AUDIO_FOLDER)
    parser.add_argument("--analysis-root", type=Path, default=DEFAULT_ANALYSIS_ROOT)
    parser.add_argument("--run-name", default=f"full-set-poc-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--track-count", type=int, default=48)
    parser.add_argument("--seed", default="full-set-poc-v1")
    parser.add_argument("--max-tempo-adjustment-bpm", type=float, default=10.0)
    parser.add_argument(
        "--allow-drop-switch-tempo-stretch",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="allow drop switches between different BPM tracks; off by default until stretched alignment is separately proven",
    )
    parser.add_argument(
        "--drop-switch-key-policy",
        choices=("compatible", "allow-unknown"),
        default="allow-unknown",
        help=(
            "Camelot key gate for drop switches. 'compatible' rejects clashes and unknown/low-confidence keys; "
            "'allow-unknown' rejects only confident clashes and lets low-confidence keys audition."
        ),
    )
    parser.add_argument(
        "--max-total-stretch-bpm",
        type=float,
        default=999.0,
        help="maximum cumulative absolute BPM adjustment allowed across selected drop switches",
    )
    parser.add_argument(
        "--candidate-search-width",
        type=int,
        default=0,
        help="maximum candidates to attempt per transition family per step; 0 means unlimited",
    )
    parser.add_argument(
        "--max-consecutive-wash-outs",
        type=int,
        default=2,
        help="maximum wash-outs allowed in a row before drop switches must be attempted first",
    )
    parser.add_argument(
        "--avoid-repeated-artist",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="avoid immediate same-artist/slug transitions when a rough artist token is available",
    )
    parser.add_argument(
        "--emergency-fallback",
        choices=["stop", "allow-repeated-artist"],
        default="stop",
        help="fallback behavior when normal policy cannot find a transition",
    )
    parser.add_argument("--min-nudge-confidence", type=float, default=0.58)
    parser.add_argument(
        "--min-stretched-drop-switch-nudge-confidence",
        type=float,
        default=0.85,
        help="minimum nudge confidence for tempo-stretched drop switches",
    )
    parser.add_argument(
        "--max-drop-switch-nudge-ms",
        type=float,
        default=18.0,
        help="maximum absolute nudge allowed for full-set drop switches",
    )
    parser.add_argument("--max-nudge-anchor-disagreement-ms", type=float, default=30.0)
    parser.add_argument(
        "--max-rendered-alignment-correction-ms",
        type=float,
        default=30.0,
        help="maximum final rendered-domain source correction allowed for drop switches",
    )
    parser.add_argument(
        "--max-rendered-probe-residual-ms",
        type=float,
        default=999_000.0,
        help="maximum residual allowed across rendered-domain beat probes for drop switches; high default records diagnostics without gating",
    )
    parser.add_argument(
        "--prove-rendered-drop-switch-alignment",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "run the expensive rendered-domain nudge proof for each selected drop switch; "
            "off by default because the accepted audition path uses raw transient nudge"
        ),
    )
    parser.add_argument("--sample-rate", type=int, default=44_100)
    parser.add_argument(
        "--washout-sweep-uri",
        default=DEFAULT_WASHOUT_SWEEP_URI,
        help="source URI/path for the user-rendered wash-out sweep asset",
    )
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--render-previews", action="store_true", help="render one preview WAV per transition after planning")
    parser.add_argument("--preview-pre-seconds", type=float, default=32.0)
    parser.add_argument("--preview-post-seconds", type=float, default=24.0)
    parser.add_argument("--preview-fx-preroll-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)

    project_root = host_path(args.project_root).resolve()
    output_root = project_root / ".autodj-cache" / "full-set-poc" / args.run_name
    pairs_root = output_root / "pairs"
    output_root.mkdir(parents=True, exist_ok=True)
    pairs_root.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    audio_folder = host_path(args.audio_folder).resolve()
    analysis_root = host_path(args.analysis_root).resolve()
    tracks = load_tracks(analysis_root)
    if len(tracks) < 2:
        raise SystemExit("Need at least two analyzed tracks.")

    mixplan_tool = project_root / "build" / "debug" / "core" / "dj" / "Debug" / "autodj_mixplan_poc.exe"
    if not mixplan_tool.exists():
        raise SystemExit(f"Missing planner tool: {mixplan_tool}")

    print(f"Loaded tracks: {len(tracks)}")
    print(f"Run root: {output_root}")
    print(f"Seed: {args.seed}")

    candidate_events: list[dict[str, Any]] = []
    selected = build_set_sequence(
        tracks=tracks,
        rng=rng,
        track_count=min(args.track_count, len(tracks)),
        pairs_root=pairs_root,
        mixplan_tool=mixplan_tool,
        project_root=project_root,
        audio_folder=audio_folder,
        max_tempo_adjustment_bpm=args.max_tempo_adjustment_bpm,
        allow_drop_switch_tempo_stretch=args.allow_drop_switch_tempo_stretch,
        drop_switch_key_policy=args.drop_switch_key_policy,
        max_total_stretch_bpm=args.max_total_stretch_bpm,
        candidate_search_width=args.candidate_search_width,
        max_consecutive_wash_outs=args.max_consecutive_wash_outs,
        avoid_repeated_artist=args.avoid_repeated_artist,
        emergency_fallback=args.emergency_fallback,
        min_nudge_confidence=args.min_nudge_confidence,
        min_stretched_drop_switch_nudge_confidence=args.min_stretched_drop_switch_nudge_confidence,
        max_drop_switch_nudge_ms=args.max_drop_switch_nudge_ms,
        max_nudge_anchor_disagreement_ms=args.max_nudge_anchor_disagreement_ms,
        prove_rendered_drop_switch_alignment=args.prove_rendered_drop_switch_alignment,
        max_rendered_alignment_correction_ms=args.max_rendered_alignment_correction_ms,
        max_rendered_probe_residual_ms=args.max_rendered_probe_residual_ms,
        candidate_events=candidate_events,
    )
    if not selected:
        raise SystemExit("Could not generate any transitions.")

    full_plan = merge_pair_plans(selected, args.run_name, washout_sweep_uri=args.washout_sweep_uri)
    full_plan_path = output_root / "mix-plan-full-set.json"
    write_json(full_plan_path, full_plan)
    validation = validate_full_set_plan(full_plan, asset_root=audio_folder)
    validation_report_path = output_root / "validation-report.json"
    write_json(validation_report_path, validation)
    if not validation["ok"]:
        raise SystemExit("Generated invalid full-set MixPlan: " + json.dumps(validation, indent=2))
    candidate_report = build_candidate_report(
        events=candidate_events,
        run_name=args.run_name,
        seed=args.seed,
        selected=selected,
        policy={
            "maxTempoAdjustmentBpm": args.max_tempo_adjustment_bpm,
            "allowDropSwitchTempoStretch": args.allow_drop_switch_tempo_stretch,
            "dropSwitchKeyPolicy": args.drop_switch_key_policy,
            "maxTotalStretchBpm": args.max_total_stretch_bpm,
            "candidateSearchWidth": args.candidate_search_width,
            "maxConsecutiveWashOuts": args.max_consecutive_wash_outs,
            "avoidRepeatedArtist": args.avoid_repeated_artist,
            "emergencyFallback": args.emergency_fallback,
            "minNudgeConfidence": args.min_nudge_confidence,
            "minStretchedDropSwitchNudgeConfidence": args.min_stretched_drop_switch_nudge_confidence,
            "maxDropSwitchNudgeMs": args.max_drop_switch_nudge_ms,
            "maxNudgeAnchorDisagreementMs": args.max_nudge_anchor_disagreement_ms,
            "proveRenderedDropSwitchAlignment": args.prove_rendered_drop_switch_alignment,
            "maxRenderedAlignmentCorrectionMs": args.max_rendered_alignment_correction_ms,
            "maxRenderedProbeResidualMs": args.max_rendered_probe_residual_ms,
            "washoutSweepUri": args.washout_sweep_uri,
        },
    )
    candidate_report_path = output_root / "candidate-report.json"
    write_json(candidate_report_path, candidate_report)

    summary = {
        "ok": True,
        "runName": args.run_name,
        "seed": args.seed,
        "trackCountRequested": args.track_count,
        "trackCountInSet": len({step["outgoing"].track_id for step in selected} | {selected[-1]["incoming"].track_id}),
        "transitionCount": len(selected),
        "dropSwitchCount": sum(1 for step in selected if step["kind"] == "drop-switch"),
        "washOutCount": sum(1 for step in selected if step["kind"] == "wash-out"),
        "outputRoot": str(output_root),
        "mixPlanPath": str(full_plan_path),
        "candidateReportPath": str(candidate_report_path),
        "validationReportPath": str(validation_report_path),
        "renderPath": str(output_root / "render" / "audition.wav"),
        "validation": validation,
        "statistics": build_full_set_statistics(selected, validation),
        "manualVerdicts": [],
        "artifactLinks": {
            "mixPlan": str(full_plan_path),
            "candidateReport": str(candidate_report_path),
            "validationReport": str(validation_report_path),
            "renderWav": str(output_root / "render" / "audition.wav"),
        },
        "sequence": [
            {
                "index": index + 1,
                "kind": step["kind"],
                "outgoingTrackId": step["outgoing"].track_id,
                "incomingTrackId": step["incoming"].track_id,
                "outgoingCamelotKey": step["outgoing"].camelot_key,
                "incomingCamelotKey": step["incoming"].camelot_key,
                "keyCompatibility": key_compatibility(step["outgoing"], step["incoming"]),
                "outgoingEffectiveBpm": round_float(float(step.get("outgoing_effective_bpm", step["outgoing"].normalized_bpm))),
                "nativeTempoDeltaBpm": round_float(abs(step["outgoing"].normalized_bpm - step["incoming"].normalized_bpm)),
                "tempoDeltaBpm": round_float(float(step.get("tempo_delta_bpm", abs(step["outgoing"].normalized_bpm - step["incoming"].normalized_bpm)))),
                "requiresTempoStretch": step["kind"] == "drop-switch"
                and float(step.get("tempo_delta_bpm", abs(step["outgoing"].normalized_bpm - step["incoming"].normalized_bpm))) > 0.0001,
                "pairPlanPath": str(step["final_plan_path"]),
                "nudgeConfidence": step.get("nudge", {}).get("confidence"),
                "nudgeMilliseconds": step.get("nudge", {}).get("nudgeMilliseconds"),
                "gainVerdict": (step.get("gain") or {}).get("verdict"),
            }
            for index, step in enumerate(selected)
        ],
    }
    write_json(output_root / "full-set-summary.json", summary)

    print(
        "Selected transitions: "
        f"{summary['transitionCount']} total, {summary['dropSwitchCount']} drop-switch, {summary['washOutCount']} wash-out"
    )
    print(f"MixPlan: {full_plan_path}")

    if args.render_previews:
        from .transition_preview import (
            TransitionPreviewOptions,
            TransitionPreviewPackOptions,
            write_transition_preview_pack,
        )

        previews_root = output_root / "previews"
        preview_summary = write_transition_preview_pack(
            full_plan_path,
            previews_root,
            options=TransitionPreviewPackOptions(
                preview=TransitionPreviewOptions(
                    pre_seconds=args.preview_pre_seconds,
                    post_seconds=args.preview_post_seconds,
                    fx_preroll_seconds=args.preview_fx_preroll_seconds,
                ),
                render=True,
                asset_root=audio_folder,
                sample_rate=args.sample_rate,
            ),
        )
        summary["previewResult"] = preview_summary
        summary["artifactLinks"]["previewIndex"] = str(previews_root / "index.json")
        write_json(output_root / "full-set-summary.json", summary)
        print(f"Preview index: {previews_root / 'index.json'}")

    if not args.skip_render:
        render_dir = output_root / "render"
        render_dir.mkdir(parents=True, exist_ok=True)
        render_result = run_wsl_json(
            project_root,
            "autodj-analysis render-mixplan "
            f"{quote_wsl(full_plan_path)} "
            f"--out {quote_wsl(render_dir)} "
            f"--asset-root {quote_wsl(audio_folder)} "
            f"--sample-rate {args.sample_rate} "
            "--json",
        )
        write_json(render_dir / "render-stdout.json", render_result)
        summary["renderResult"] = render_result
        write_json(output_root / "full-set-summary.json", summary)
        print(f"Rendered WAV: {render_result.get('outputWav')}")

    return 0


def load_tracks(analysis_root: Path) -> list[TrackRow]:
    rows: list[TrackRow] = []
    for artifact_path in sorted(analysis_root.glob("tracks/*/analyzed-track.json")):
        artifact = read_json(artifact_path)
        sections = artifact.get("sections") or []
        source = artifact.get("source") or {}
        tempo = artifact.get("tempo") or {}
        key = artifact.get("key") or {}
        rows.append(
            TrackRow(
                track_id=str(artifact.get("trackId") or artifact_path.parent.name),
                artifact_path=artifact_path,
                source_uri=str(source.get("sourceUri") or ""),
                normalized_bpm=float(tempo.get("normalizedBpm") or tempo.get("bpm") or 0.0),
                camelot_key=str(key.get("camelot") or ""),
                key_confidence=float(key.get("confidence") or 0.0),
                duration_seconds=float(source.get("durationSeconds") or 0.0),
                build_count=sum(1 for section in sections if str(section.get("type", "")).lower() == "build"),
                drop_count=sum(1 for section in sections if str(section.get("type", "")).lower() == "drop"),
            )
        )
    return rows


def build_set_sequence(
    *,
    tracks: list[TrackRow],
    rng: random.Random,
    track_count: int,
    pairs_root: Path,
    mixplan_tool: Path,
    project_root: Path,
    audio_folder: Path,
    max_tempo_adjustment_bpm: float,
    allow_drop_switch_tempo_stretch: bool,
    drop_switch_key_policy: str,
    max_total_stretch_bpm: float,
    candidate_search_width: int,
    max_consecutive_wash_outs: int,
    avoid_repeated_artist: bool,
    emergency_fallback: str,
    min_nudge_confidence: float,
    min_stretched_drop_switch_nudge_confidence: float,
    max_drop_switch_nudge_ms: float,
    max_nudge_anchor_disagreement_ms: float,
    prove_rendered_drop_switch_alignment: bool,
    max_rendered_alignment_correction_ms: float,
    max_rendered_probe_residual_ms: float,
    candidate_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    unused = tracks[:]
    rng.shuffle(unused)
    starts = [track for track in unused if track.can_outgoing_drop_switch]
    current = rng.choice(starts or unused)
    unused.remove(current)
    selected: list[dict[str, Any]] = []
    used_stretch_bpm = 0.0
    current_effective_bpm = current.normalized_bpm
    print(f"Start track: {current.track_id}")

    step_index = 1
    while unused and len(selected) + 1 < track_count:
        print(f"\nPlanning step {step_index}: outgoing={current.track_id}, remaining={len(unused)}")
        accepted = None
        recent_kinds = [str(step["kind"]) for step in selected[-3:]]
        step_records = build_candidate_step_records(
            step_index=step_index,
            outgoing=current,
            outgoing_effective_bpm=current_effective_bpm,
            candidates=unused,
            max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
            allow_drop_switch_tempo_stretch=allow_drop_switch_tempo_stretch,
            drop_switch_key_policy=drop_switch_key_policy,
            max_total_stretch_bpm=max_total_stretch_bpm,
            used_stretch_bpm=used_stretch_bpm,
            max_consecutive_wash_outs=max_consecutive_wash_outs,
            avoid_repeated_artist=avoid_repeated_artist,
            recent_kinds=recent_kinds,
        )
        if candidate_events is not None:
            candidate_events.extend(step_records)
        records_by_key = {
            (str(record["kind"]), str(record["incomingTrackId"])): record
            for record in step_records
        }
        attempt_order = 1

        drop_candidates = drop_switch_candidates(
            current,
            unused,
            rng,
            outgoing_effective_bpm=current_effective_bpm,
            max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
            allow_tempo_stretch=allow_drop_switch_tempo_stretch,
            drop_switch_key_policy=drop_switch_key_policy,
            max_total_stretch_bpm=max_total_stretch_bpm,
            used_stretch_bpm=used_stretch_bpm,
            candidate_search_width=candidate_search_width,
            avoid_repeated_artist=avoid_repeated_artist,
        )
        if not drop_candidates and emergency_fallback == "allow-repeated-artist" and avoid_repeated_artist:
            drop_candidates = drop_switch_candidates(
                current,
                unused,
                rng,
                outgoing_effective_bpm=current_effective_bpm,
                max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
                allow_tempo_stretch=allow_drop_switch_tempo_stretch,
                drop_switch_key_policy=drop_switch_key_policy,
                max_total_stretch_bpm=max_total_stretch_bpm,
                used_stretch_bpm=used_stretch_bpm,
                candidate_search_width=candidate_search_width,
                avoid_repeated_artist=False,
            )

        for candidate in drop_candidates:
            record = records_by_key.get(("drop-switch", candidate.track_id))
            if record is not None:
                record["status"] = "attempted"
                record["attemptOrder"] = attempt_order
            attempt_order += 1
            accepted = try_create_pair(
                kind="drop-switch",
                index=step_index,
                outgoing=current,
                incoming=candidate,
                outgoing_effective_bpm=current_effective_bpm,
                pairs_root=pairs_root,
                mixplan_tool=mixplan_tool,
                project_root=project_root,
                audio_folder=audio_folder,
                max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
                min_nudge_confidence=min_nudge_confidence,
                min_stretched_drop_switch_nudge_confidence=min_stretched_drop_switch_nudge_confidence,
                max_drop_switch_nudge_ms=max_drop_switch_nudge_ms,
                max_nudge_anchor_disagreement_ms=max_nudge_anchor_disagreement_ms,
                prove_rendered_drop_switch_alignment=prove_rendered_drop_switch_alignment,
                max_rendered_alignment_correction_ms=max_rendered_alignment_correction_ms,
                max_rendered_probe_residual_ms=max_rendered_probe_residual_ms,
            )
            if accepted is not None:
                if record is not None:
                    mark_candidate_selected(record, accepted)
                break
            if record is not None:
                mark_candidate_rejected_after_attempt(record)

        if accepted is None:
            wash_candidates = wash_out_candidates(
                current,
                unused,
                rng,
                candidate_search_width=candidate_search_width,
                avoid_repeated_artist=avoid_repeated_artist,
                max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
                allow_drop_switch_tempo_stretch=allow_drop_switch_tempo_stretch,
                drop_switch_key_policy=drop_switch_key_policy,
                max_total_stretch_bpm=max_total_stretch_bpm,
                used_stretch_bpm=used_stretch_bpm,
            )
            if not wash_candidates and emergency_fallback == "allow-repeated-artist" and avoid_repeated_artist:
                wash_candidates = wash_out_candidates(
                    current,
                    unused,
                    rng,
                    candidate_search_width=candidate_search_width,
                    avoid_repeated_artist=False,
                    max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
                    allow_drop_switch_tempo_stretch=allow_drop_switch_tempo_stretch,
                    drop_switch_key_policy=drop_switch_key_policy,
                    max_total_stretch_bpm=max_total_stretch_bpm,
                    used_stretch_bpm=used_stretch_bpm,
                )
            if max_consecutive_wash_outs >= 0 and consecutive_transition_count(recent_kinds, "wash-out") >= max_consecutive_wash_outs:
                if drop_candidates:
                    wash_candidates = []

            for candidate in wash_candidates:
                record = records_by_key.get(("wash-out", candidate.track_id))
                if record is not None:
                    record["status"] = "attempted"
                    record["attemptOrder"] = attempt_order
                attempt_order += 1
                accepted = try_create_pair(
                    kind="wash-out",
                    index=step_index,
                    outgoing=current,
                    incoming=candidate,
                    pairs_root=pairs_root,
                    mixplan_tool=mixplan_tool,
                    project_root=project_root,
                    audio_folder=audio_folder,
                    max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
                    min_nudge_confidence=min_nudge_confidence,
                    min_stretched_drop_switch_nudge_confidence=min_stretched_drop_switch_nudge_confidence,
                    max_drop_switch_nudge_ms=max_drop_switch_nudge_ms,
                    max_nudge_anchor_disagreement_ms=max_nudge_anchor_disagreement_ms,
                    prove_rendered_drop_switch_alignment=prove_rendered_drop_switch_alignment,
                    max_rendered_alignment_correction_ms=max_rendered_alignment_correction_ms,
                    max_rendered_probe_residual_ms=max_rendered_probe_residual_ms,
                )
                if accepted is not None:
                    if record is not None:
                        mark_candidate_selected(record, accepted)
                    break
                if record is not None:
                    mark_candidate_rejected_after_attempt(record)

        if accepted is None:
            print(f"Could not find a valid transition out of {current.track_id}; stopping early.")
            if not selected and unused:
                print("Retrying with a different start track.")
                starts = [track for track in unused if track.can_outgoing_drop_switch or track.can_wash_out]
                if not starts:
                    break
                current = rng.choice(starts)
                unused.remove(current)
                print(f"Start track: {current.track_id}")
                continue
            break

        for record in step_records:
            if record["status"] == "eligible":
                record["status"] = "not_attempted_after_selection"
            elif record["status"] == "rejected_pre_filter":
                record["attemptOrder"] = None
        selected.append(accepted)
        next_effective_bpm = accepted["incoming"].normalized_bpm
        if accepted["kind"] == "drop-switch":
            tempo_delta = abs(current_effective_bpm - accepted["incoming"].normalized_bpm)
            used_stretch_bpm += tempo_delta
            # A drop-switch keeps the incoming song at the outgoing song's
            # current effective tempo. The next step can now plan from that
            # carried tempo instead of forcing a wash-out back to native BPM.
            next_effective_bpm = current_effective_bpm
        current = accepted["incoming"]
        current_effective_bpm = next_effective_bpm
        unused.remove(current)
        step_index += 1

    return selected


def drop_switch_candidates(
    outgoing: TrackRow,
    candidates: list[TrackRow],
    rng: random.Random,
    *,
    outgoing_effective_bpm: float | None = None,
    max_tempo_adjustment_bpm: float,
    allow_tempo_stretch: bool = False,
    drop_switch_key_policy: str = "compatible",
    max_total_stretch_bpm: float = 999.0,
    used_stretch_bpm: float = 0.0,
    candidate_search_width: int = 0,
    avoid_repeated_artist: bool = True,
) -> list[TrackRow]:
    if not outgoing.can_outgoing_drop_switch:
        return []
    effective_bpm = outgoing.normalized_bpm if outgoing_effective_bpm is None else outgoing_effective_bpm
    rows: list[tuple[int, int, float, float, float, float, TrackRow]] = []
    for incoming in candidates:
        if not incoming.can_incoming_drop_switch:
            continue
        key = key_compatibility(outgoing, incoming)
        if drop_switch_key_rejected(key, drop_switch_key_policy):
            continue
        tempo_delta = abs(effective_bpm - incoming.normalized_bpm)
        if not allow_tempo_stretch and tempo_delta > 0.0001:
            continue
        if tempo_delta > max_tempo_adjustment_bpm:
            continue
        if used_stretch_bpm + tempo_delta > max_total_stretch_bpm:
            continue
        if avoid_repeated_artist and same_artist_token(outgoing, incoming):
            continue
        future = drop_switch_followup_potential(
            incoming,
            [candidate for candidate in candidates if candidate.track_id != incoming.track_id],
            outgoing_effective_bpm=effective_bpm,
            max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
            allow_tempo_stretch=allow_tempo_stretch,
            drop_switch_key_policy=drop_switch_key_policy,
            max_total_stretch_bpm=max_total_stretch_bpm,
            used_stretch_bpm=used_stretch_bpm + tempo_delta,
            avoid_repeated_artist=avoid_repeated_artist,
        )
        tempo_priority = 0 if tempo_delta <= 0.0001 else 1
        rows.append((tempo_priority, -int(future["count"]), -float(future["bestScore"]), -key["score"], tempo_delta, rng.random(), incoming))
    rows.sort(key=lambda item: item[:6])
    selected = [item[6] for item in rows]
    return limit_candidates(selected, candidate_search_width)


def drop_switch_followup_potential(
    incoming: TrackRow,
    future_candidates: list[TrackRow],
    *,
    outgoing_effective_bpm: float,
    max_tempo_adjustment_bpm: float,
    allow_tempo_stretch: bool,
    drop_switch_key_policy: str,
    max_total_stretch_bpm: float,
    used_stretch_bpm: float,
    avoid_repeated_artist: bool,
) -> dict[str, float | int]:
    if not incoming.can_outgoing_drop_switch:
        return {"count": 0, "bestScore": 0.0}

    count = 0
    best_score = 0.0
    for candidate in future_candidates:
        if not candidate.can_incoming_drop_switch:
            continue
        if avoid_repeated_artist and same_artist_token(incoming, candidate):
            continue
        key = key_compatibility(incoming, candidate)
        if drop_switch_key_rejected(key, drop_switch_key_policy):
            continue
        tempo_delta = abs(outgoing_effective_bpm - candidate.normalized_bpm)
        if not allow_tempo_stretch and tempo_delta > 0.0001:
            continue
        if tempo_delta > max_tempo_adjustment_bpm:
            continue
        if used_stretch_bpm + tempo_delta > max_total_stretch_bpm:
            continue
        count += 1
        score = candidate_score(
            "drop-switch",
            incoming,
            candidate,
            max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
            outgoing_effective_bpm=outgoing_effective_bpm,
            recent_kinds=[],
        )["score"]
        best_score = max(best_score, float(score))
    return {"count": count, "bestScore": round_float(best_score)}


def wash_out_candidates(
    outgoing: TrackRow,
    candidates: list[TrackRow],
    rng: random.Random,
    *,
    candidate_search_width: int = 0,
    avoid_repeated_artist: bool = True,
    max_tempo_adjustment_bpm: float = 10.0,
    allow_drop_switch_tempo_stretch: bool = False,
    drop_switch_key_policy: str = "compatible",
    max_total_stretch_bpm: float = 999.0,
    used_stretch_bpm: float = 0.0,
) -> list[TrackRow]:
    if not outgoing.can_wash_out:
        return []
    rows: list[tuple[int, int, int, float, float, float, float, TrackRow]] = []
    for incoming in candidates:
        if avoid_repeated_artist and same_artist_token(outgoing, incoming):
            continue
        key = key_compatibility(outgoing, incoming)
        future = wash_out_setup_potential(
            incoming,
            [candidate for candidate in candidates if candidate.track_id != incoming.track_id],
            max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
            allow_drop_switch_tempo_stretch=allow_drop_switch_tempo_stretch,
            drop_switch_key_policy=drop_switch_key_policy,
            max_total_stretch_bpm=max_total_stretch_bpm,
            used_stretch_bpm=used_stretch_bpm,
            avoid_repeated_artist=avoid_repeated_artist,
        )
        setup_priority = 0 if incoming.can_outgoing_drop_switch else 1
        rows.append(
            (
                setup_priority,
                -future["exactCount"],
                -future["stretchedCount"],
                -future["bestScore"],
                future["bestTempoDelta"],
                -key["score"],
                rng.random(),
                incoming,
            )
        )
    rows.sort(key=lambda item: item[:7])
    selected = [item[7] for item in rows]
    return limit_candidates(selected, candidate_search_width)


def wash_out_setup_potential(
    incoming: TrackRow,
    future_candidates: list[TrackRow],
    *,
    max_tempo_adjustment_bpm: float,
    allow_drop_switch_tempo_stretch: bool,
    drop_switch_key_policy: str = "compatible",
    max_total_stretch_bpm: float = 999.0,
    used_stretch_bpm: float = 0.0,
    avoid_repeated_artist: bool = True,
) -> dict[str, float | int]:
    """Score how well a wash-out target sets up the next drop switch."""

    exact_count = 0
    stretched_count = 0
    best_score = 0.0
    best_tempo_delta = 999.0
    if not incoming.can_outgoing_drop_switch:
        return {
            "exactCount": exact_count,
            "stretchedCount": stretched_count,
            "bestScore": best_score,
            "bestTempoDelta": best_tempo_delta,
        }

    for candidate in future_candidates:
        if not candidate.can_incoming_drop_switch:
            continue
        if avoid_repeated_artist and same_artist_token(incoming, candidate):
            continue
        key = key_compatibility(incoming, candidate)
        if drop_switch_key_rejected(key, drop_switch_key_policy):
            continue
        tempo_delta = abs(incoming.normalized_bpm - candidate.normalized_bpm)
        if tempo_delta > max_tempo_adjustment_bpm:
            continue
        if tempo_delta > 0.0001:
            if not allow_drop_switch_tempo_stretch:
                continue
            if used_stretch_bpm + tempo_delta > max_total_stretch_bpm:
                continue
            stretched_count += 1
        else:
            exact_count += 1
        score = float(
            candidate_score(
                "drop-switch",
                incoming,
                candidate,
                max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
                recent_kinds=[],
            )["score"]
        )
        best_score = max(best_score, score)
        best_tempo_delta = min(best_tempo_delta, tempo_delta)

    return {
        "exactCount": exact_count,
        "stretchedCount": stretched_count,
        "bestScore": round_float(best_score),
        "bestTempoDelta": round_float(best_tempo_delta if best_tempo_delta < 999.0 else 999.0),
    }


def build_candidate_step_records(
    *,
    step_index: int,
    outgoing: TrackRow,
    candidates: list[TrackRow],
    max_tempo_adjustment_bpm: float,
    outgoing_effective_bpm: float | None = None,
    allow_drop_switch_tempo_stretch: bool = False,
    drop_switch_key_policy: str = "compatible",
    max_total_stretch_bpm: float = 999.0,
    used_stretch_bpm: float = 0.0,
    max_consecutive_wash_outs: int = 2,
    avoid_repeated_artist: bool = True,
    recent_kinds: list[str] | None = None,
) -> list[dict[str, Any]]:
    recent_kinds = recent_kinds or []
    records: list[dict[str, Any]] = []
    for incoming in sorted(candidates, key=lambda item: item.track_id):
        for kind in ("drop-switch", "wash-out"):
            records.append(
                build_candidate_record(
                    step_index=step_index,
                    kind=kind,
                    outgoing=outgoing,
                    outgoing_effective_bpm=outgoing_effective_bpm,
                    incoming=incoming,
                    max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
                    allow_drop_switch_tempo_stretch=allow_drop_switch_tempo_stretch,
                    drop_switch_key_policy=drop_switch_key_policy,
                    max_total_stretch_bpm=max_total_stretch_bpm,
                    used_stretch_bpm=used_stretch_bpm,
                    max_consecutive_wash_outs=max_consecutive_wash_outs,
                    avoid_repeated_artist=avoid_repeated_artist,
                    recent_kinds=recent_kinds,
                )
            )
    return records


def build_candidate_record(
    *,
    step_index: int,
    kind: str,
    outgoing: TrackRow,
    incoming: TrackRow,
    max_tempo_adjustment_bpm: float,
    outgoing_effective_bpm: float | None = None,
    allow_drop_switch_tempo_stretch: bool = False,
    drop_switch_key_policy: str = "compatible",
    max_total_stretch_bpm: float = 999.0,
    used_stretch_bpm: float = 0.0,
    max_consecutive_wash_outs: int = 2,
    avoid_repeated_artist: bool = True,
    recent_kinds: list[str] | None = None,
) -> dict[str, Any]:
    recent_kinds = recent_kinds or []
    reasons = candidate_precheck_reasons(
        kind,
        outgoing,
        incoming,
        max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
        outgoing_effective_bpm=outgoing_effective_bpm,
        allow_drop_switch_tempo_stretch=allow_drop_switch_tempo_stretch,
        drop_switch_key_policy=drop_switch_key_policy,
        max_total_stretch_bpm=max_total_stretch_bpm,
        used_stretch_bpm=used_stretch_bpm,
        max_consecutive_wash_outs=max_consecutive_wash_outs,
        avoid_repeated_artist=avoid_repeated_artist,
        recent_kinds=recent_kinds,
    )
    score = candidate_score(
        kind,
        outgoing,
        incoming,
        max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
        outgoing_effective_bpm=outgoing_effective_bpm,
        recent_kinds=recent_kinds,
    )
    effective_bpm = outgoing.normalized_bpm if outgoing_effective_bpm is None else outgoing_effective_bpm
    tempo_delta = abs(effective_bpm - incoming.normalized_bpm)
    native_tempo_delta = abs(outgoing.normalized_bpm - incoming.normalized_bpm)
    return {
        "stepIndex": step_index,
        "kind": kind,
        "status": "rejected_pre_filter" if reasons else "eligible",
        "attemptOrder": None,
        "outgoingTrackId": outgoing.track_id,
        "incomingTrackId": incoming.track_id,
        "score": score["score"],
        "scoreComponents": score["components"],
        "policy": {
            "maxTempoAdjustmentBpm": max_tempo_adjustment_bpm,
            "allowDropSwitchTempoStretch": allow_drop_switch_tempo_stretch,
            "dropSwitchKeyPolicy": drop_switch_key_policy,
            "maxTotalStretchBpm": max_total_stretch_bpm,
            "usedStretchBpm": round_float(used_stretch_bpm),
            "maxConsecutiveWashOuts": max_consecutive_wash_outs,
            "avoidRepeatedArtist": avoid_repeated_artist,
            "recentKinds": recent_kinds,
        },
        "trackFacts": {
            "outgoing": track_facts(outgoing),
            "incoming": track_facts(incoming),
            "outgoingEffectiveBpm": round_float(effective_bpm),
            "nativeTempoDeltaBpm": round_float(native_tempo_delta),
            "tempoDeltaBpm": round_float(tempo_delta),
            "requiresTempoStretch": kind == "drop-switch" and tempo_delta > 0.0001,
        },
        "precheckReasons": reasons,
        "postPass": {},
    }


def track_facts(track: TrackRow) -> dict[str, Any]:
    return {
        "trackId": track.track_id,
        "normalizedBpm": round_float(track.normalized_bpm),
        "camelotKey": track.camelot_key,
        "keyConfidence": round_float(track.key_confidence),
        "buildCount": track.build_count,
        "dropCount": track.drop_count,
        "durationSeconds": round_float(track.duration_seconds),
    }


def candidate_precheck_reasons(
    kind: str,
    outgoing: TrackRow,
    incoming: TrackRow,
    *,
    max_tempo_adjustment_bpm: float,
    outgoing_effective_bpm: float | None = None,
    allow_drop_switch_tempo_stretch: bool = False,
    drop_switch_key_policy: str = "compatible",
    max_total_stretch_bpm: float = 999.0,
    used_stretch_bpm: float = 0.0,
    max_consecutive_wash_outs: int = 2,
    avoid_repeated_artist: bool = True,
    recent_kinds: list[str] | None = None,
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    key = key_compatibility(outgoing, incoming)
    effective_bpm = outgoing.normalized_bpm if outgoing_effective_bpm is None else outgoing_effective_bpm
    tempo_delta = abs(effective_bpm - incoming.normalized_bpm)
    recent_kinds = recent_kinds or []

    if kind == "drop-switch":
        if not outgoing.can_outgoing_drop_switch:
            reasons.append(
                {
                    "code": "missing_outgoing_second_build_drop",
                    "message": "Drop switch needs at least two ordered build/drop sections on the outgoing track.",
                }
            )
        if not incoming.can_incoming_drop_switch:
            reasons.append(
                {
                    "code": "missing_incoming_drop",
                    "message": "Drop switch needs at least one drop section on the incoming track.",
                }
            )
        if drop_switch_key_rejected(key, drop_switch_key_policy):
            reasons.append(
                {
                    "code": "key_incompatible",
                    "message": "Drop switch requires Camelot-compatible keys.",
                    "classification": key["classification"],
                    "score": key["score"],
                    "dropSwitchKeyPolicy": drop_switch_key_policy,
                }
            )
        if tempo_delta > max_tempo_adjustment_bpm:
            reasons.append(
                {
                    "code": "tempo_delta_exceeds_limit",
                    "message": "Drop switch requires BPMs to be alignable within the configured stretch budget.",
                    "tempoDeltaBpm": round_float(tempo_delta),
                    "outgoingEffectiveBpm": round_float(effective_bpm),
                    "outgoingNativeBpm": round_float(outgoing.normalized_bpm),
                    "maxTempoAdjustmentBpm": max_tempo_adjustment_bpm,
                }
            )
        if not allow_drop_switch_tempo_stretch and tempo_delta > 0.0001:
            reasons.append(
                {
                    "code": "drop_switch_tempo_stretch_disabled",
                    "message": "Safe-mode full-set drop switches require exact BPM until stretched alignment has a separate proof step.",
                    "tempoDeltaBpm": round_float(tempo_delta),
                    "outgoingEffectiveBpm": round_float(effective_bpm),
                }
            )
        if used_stretch_bpm + tempo_delta > max_total_stretch_bpm:
            reasons.append(
                {
                    "code": "stretch_budget_exceeded",
                    "message": "Candidate would exceed the configured set-level stretch budget.",
                    "usedStretchBpm": round_float(used_stretch_bpm),
                    "candidateTempoDeltaBpm": round_float(tempo_delta),
                    "outgoingEffectiveBpm": round_float(effective_bpm),
                    "maxTotalStretchBpm": max_total_stretch_bpm,
                }
            )
        if avoid_repeated_artist and same_artist_token(outgoing, incoming):
            reasons.append(
                {
                    "code": "immediate_artist_repeat",
                    "message": "Candidate appears to repeat the same artist token immediately.",
                    "artistToken": artist_token(outgoing),
                }
            )
    elif kind == "wash-out":
        if not outgoing.can_wash_out:
            reasons.append(
                {
                    "code": "missing_outgoing_drop",
                    "message": "Wash-out needs at least one outgoing drop end anchor.",
                }
            )
        if avoid_repeated_artist and same_artist_token(outgoing, incoming):
            reasons.append(
                {
                    "code": "immediate_artist_repeat",
                    "message": "Candidate appears to repeat the same artist token immediately.",
                    "artistToken": artist_token(outgoing),
                }
            )
    else:
        reasons.append(
            {
                "code": "unsupported_transition_kind",
                "message": f"Unsupported transition kind: {kind}",
            }
        )

    return reasons


def candidate_score(
    kind: str,
    outgoing: TrackRow,
    incoming: TrackRow,
    *,
    max_tempo_adjustment_bpm: float,
    outgoing_effective_bpm: float | None = None,
    recent_kinds: list[str] | None = None,
) -> dict[str, Any]:
    recent_kinds = recent_kinds or []
    key = key_compatibility(outgoing, incoming)
    effective_bpm = outgoing.normalized_bpm if outgoing_effective_bpm is None else outgoing_effective_bpm
    tempo_delta = abs(effective_bpm - incoming.normalized_bpm)
    if max_tempo_adjustment_bpm <= 0:
        tempo_component = 1.0 if tempo_delta <= 0.0001 else 0.0
    else:
        tempo_component = max(0.0, 1.0 - (tempo_delta / max_tempo_adjustment_bpm))
    recent_component = recent_transition_component(kind, recent_kinds)

    if kind == "drop-switch":
        semantic_component = min(
            outgoing.build_count / 2.0,
            outgoing.drop_count / 2.0,
            incoming.drop_count / 1.0,
            1.0,
        )
        transition_type_component = 1.0
        weighted_score = (
            0.30 * semantic_component
            + 0.25 * float(key["score"])
            + 0.20 * tempo_component
            + 0.15 * recent_component
            + 0.10 * transition_type_component
        )
    elif kind == "wash-out":
        outgoing_anchor_component = min(outgoing.drop_count / 1.0, 1.0)
        incoming_setup_component = 1.0 if incoming.can_outgoing_drop_switch else 0.65
        transition_type_component = 0.72
        semantic_component = 0.65 * outgoing_anchor_component + 0.35 * incoming_setup_component
        weighted_score = (
            0.35 * semantic_component
            + 0.20 * float(key["score"])
            + 0.20 * recent_component
            + 0.15 * incoming_setup_component
            + 0.10 * transition_type_component
        )
    else:
        semantic_component = 0.0
        transition_type_component = 0.0
        incoming_setup_component = 0.0
        weighted_score = 0.0

    components: dict[str, Any] = {
        "transitionType": round_float(transition_type_component),
        "key": {
            "score": round_float(float(key["score"])),
            "classification": key["classification"],
            "compatible": key["compatible"],
        },
        "tempo": {
            "score": round_float(tempo_component),
            "deltaBpm": round_float(tempo_delta),
            "outgoingEffectiveBpm": round_float(effective_bpm),
            "outgoingNativeBpm": round_float(outgoing.normalized_bpm),
            "requiresStretch": kind == "drop-switch" and tempo_delta > 0.0001,
        },
        "semantic": {
            "score": round_float(semantic_component),
            "confidenceSource": "section-count-proxy",
        },
        "recentHistory": {
            "score": round_float(recent_component),
            "recentKinds": recent_kinds,
        },
    }
    if kind == "wash-out":
        components["incomingSetup"] = round_float(incoming_setup_component)

    return {
        "score": round_float(max(0.0, min(1.0, weighted_score))),
        "components": components,
    }


def recent_transition_component(kind: str, recent_kinds: list[str]) -> float:
    if len(recent_kinds) >= 2 and recent_kinds[-1] == kind and recent_kinds[-2] == kind:
        return 0.35
    if recent_kinds and recent_kinds[-1] == kind:
        return 0.75
    return 1.0


def consecutive_transition_count(recent_kinds: list[str], kind: str) -> int:
    count = 0
    for recent in reversed(recent_kinds):
        if recent != kind:
            break
        count += 1
    return count


def limit_candidates(candidates: list[TrackRow], candidate_search_width: int) -> list[TrackRow]:
    if candidate_search_width <= 0:
        return candidates
    return candidates[:candidate_search_width]


def same_artist_token(outgoing: TrackRow, incoming: TrackRow) -> bool:
    first = artist_token(outgoing)
    second = artist_token(incoming)
    return bool(first and second and first == second)


def artist_token(track: TrackRow) -> str:
    value = track.source_uri or track.track_id
    stem = Path(value).stem.lower()
    for separator in (" - ", "_-_"):
        if separator in stem:
            stem = stem.split(separator, 1)[0]
            break
    token = stem.split("-", 1)[0].strip()
    return "".join(ch for ch in token if ch.isalnum())


def mark_candidate_selected(record: dict[str, Any], accepted: dict[str, Any]) -> None:
    record["status"] = "selected"
    record["finalPlanPath"] = str(accepted["final_plan_path"])
    record["postPass"] = post_pass_summary(accepted)


def mark_candidate_rejected_after_attempt(record: dict[str, Any]) -> None:
    record["status"] = "rejected_after_attempt"
    record.setdefault("postPass", {})
    record.setdefault("precheckReasons", [])
    record["postcheckReasons"] = [
        {
            "code": "pair_generation_or_post_pass_rejected",
            "message": (
                "The candidate passed cheap policy checks, but the pair planner, "
                "nudge gate, template match, or gain post-pass rejected it."
            ),
        }
    ]


def post_pass_summary(accepted: dict[str, Any]) -> dict[str, Any]:
    nudge = accepted.get("nudge") or {}
    gain = accepted.get("gain") or {}
    summary = {
        "nudge": {
            "ok": bool(nudge.get("ok")),
            "confidence": round_float(float(nudge.get("confidence") or 0.0)),
            "nudgeMilliseconds": round_float(float(nudge.get("nudgeMilliseconds") or 0.0)),
            "anchorDisagreementMilliseconds": round_float(nudge_anchor_disagreement_ms(nudge)),
        },
        "gain": None,
    }
    if gain:
        summary["gain"] = {
            "ok": bool(gain.get("ok", True)),
            "verdict": gain.get("verdict"),
            "outgoingOverlapGain": round_float(gain.get("outgoingOverlapGain")),
            "recommendedOutgoingTrimDb": round_float(gain.get("recommendedOutgoingTrimDb")),
            "bDropVsPostGainLayeredDb": round_float(gain.get("bDropVsPostGainLayeredDb")),
            "reportPath": gain.get("reportPath"),
        }
    return summary


def nudge_anchor_disagreement_ms(summary: dict[str, Any]) -> float:
    nudges = [float(item.get("nudgeSeconds") or 0.0) for item in summary.get("anchorNudges") or []]
    if len(nudges) < 2:
        return 0.0
    return (max(nudges) - min(nudges)) * 1000.0


def build_candidate_report(
    *,
    events: list[dict[str, Any]],
    run_name: str,
    seed: str,
    selected: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    rejection_summary: dict[str, int] = {}
    status_summary: dict[str, int] = {}
    for event in events:
        status = str(event.get("status") or "unknown")
        status_summary[status] = status_summary.get(status, 0) + 1
        reasons = list(event.get("precheckReasons") or []) + list(event.get("postcheckReasons") or [])
        for reason in reasons:
            code = str(reason.get("code") or "unknown")
            rejection_summary[code] = rejection_summary.get(code, 0) + 1

    return {
        "ok": True,
        "artifact": "full-set-candidate-report",
        "runName": run_name,
        "seed": seed,
        "createdAtUtc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "policy": policy,
        "totalCandidates": len(events),
        "selectedCount": len(selected),
        "statusSummary": dict(sorted(status_summary.items())),
        "rejectionSummary": dict(sorted(rejection_summary.items())),
        "selectedTransitions": [
            {
                "index": index + 1,
                "kind": step["kind"],
                "outgoingTrackId": step["outgoing"].track_id,
                "incomingTrackId": step["incoming"].track_id,
                "finalPlanPath": str(step["final_plan_path"]),
            }
            for index, step in enumerate(selected)
        ],
        "candidates": events,
    }


def build_full_set_statistics(selected: list[dict[str, Any]], validation: dict[str, Any]) -> dict[str, Any]:
    transition_counts: dict[str, int] = {}
    key_classes: dict[str, int] = {}
    gain_verdicts: dict[str, int] = {}
    nudge_confidences: list[float] = []
    nudge_milliseconds: list[float] = []
    stretch_deltas: list[float] = []
    current_wash_run = 0
    max_wash_run = 0

    for step in selected:
        kind = str(step["kind"])
        transition_counts[kind] = transition_counts.get(kind, 0) + 1
        if kind == "wash-out":
            current_wash_run += 1
            max_wash_run = max(max_wash_run, current_wash_run)
        else:
            current_wash_run = 0

        key_class = str(key_compatibility(step["outgoing"], step["incoming"])["classification"])
        key_classes[key_class] = key_classes.get(key_class, 0) + 1

        nudge = step.get("nudge") or {}
        if nudge.get("confidence") is not None:
            nudge_confidences.append(float(nudge.get("confidence") or 0.0))
        if nudge.get("nudgeMilliseconds") is not None:
            nudge_milliseconds.append(float(nudge.get("nudgeMilliseconds") or 0.0))

        if kind == "drop-switch":
            tempo_delta = float(step.get("tempo_delta_bpm", abs(step["outgoing"].normalized_bpm - step["incoming"].normalized_bpm)))
            if tempo_delta > 0.0001:
                stretch_deltas.append(tempo_delta)

        gain_verdict = (step.get("gain") or {}).get("verdict")
        if gain_verdict:
            gain_verdicts[str(gain_verdict)] = gain_verdicts.get(str(gain_verdict), 0) + 1

    return {
        "transitionCounts": dict(sorted(transition_counts.items())),
        "maxConsecutiveWashOuts": max_wash_run,
        "stretchedDropSwitchCount": len(stretch_deltas),
        "totalStretchDeltaBpm": round_float(sum(stretch_deltas)),
        "stretchDeltaBpmRange": range_summary(stretch_deltas),
        "keyCompatibilityClasses": dict(sorted(key_classes.items())),
        "nudgeConfidenceRange": range_summary(nudge_confidences),
        "nudgeMillisecondsRange": range_summary(nudge_milliseconds),
        "gainVerdicts": dict(sorted(gain_verdicts.items())),
        "validationOk": bool(validation.get("ok")),
        "validationErrorCount": int(validation.get("errorCount") or 0),
    }


def range_summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "max": None}
    return {"min": round_float(min(values)), "max": round_float(max(values))}


def write_effective_bpm_artifact(track: TrackRow, target_bpm: float, pair_dir: Path) -> Path:
    """Write a planner-only artifact that treats outgoing BPM as the current deck tempo.

    The C++ pair planner aligns incoming tempo to the outgoing artifact BPM.
    In the full-set planner an outgoing deck can already be playing at a
    prior drop-switch target tempo, so this source-time artifact lets the pair
    planner calculate the next incoming target without changing source audio
    paths, beat times, or semantic cue timestamps.
    """

    artifact = read_json(track.artifact_path)
    if not isinstance(artifact, dict):
        raise RuntimeError(f"Invalid analyzed-track artifact: {track.artifact_path}")
    tempo = artifact.setdefault("tempo", {})
    if not isinstance(tempo, dict):
        raise RuntimeError(f"Invalid tempo object in analyzed-track artifact: {track.artifact_path}")
    tempo["bpm"] = round_float(target_bpm)
    tempo["normalizedBpm"] = round_float(target_bpm)
    quality = artifact.setdefault("quality", {})
    if isinstance(quality, dict):
        warnings = quality.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append(
                "Full-set planner used this artifact as an effective-BPM outgoing view for chained drop-switch planning."
            )
    output = pair_dir / "outgoing-effective-bpm.analyzed-track.json"
    write_json(output, artifact)
    return output


def write_effective_nudge_plan(
    raw_plan_path: Path,
    output_plan_path: Path,
    *,
    outgoing_native_bpm: float,
    outgoing_effective_bpm: float,
) -> None:
    """Write a temporary pair plan whose outgoing timeline reflects effective BPM.

    The mergeable pair plan remains in outgoing source-second time so the full
    set can map it onto the reused deck placement. The nudge proof, however,
    needs rendered-domain placement timing when the outgoing deck is already
    tempo-stretched from a prior drop switch.
    """

    plan = read_json(raw_plan_path)
    transition = first_transition(plan)
    placements = placements_by_id(plan)
    outgoing = placements[str(transition["fromPlacementId"])]
    incoming = placements[str(transition["toPlacementId"])]
    outgoing_ratio = outgoing_effective_bpm / outgoing_native_bpm
    incoming_ratio = tempo_ratio(incoming)
    outgoing["tempoPlan"] = tempo_plan_payload(outgoing_native_bpm, outgoing_effective_bpm)

    anchors = transition.get("sourceAnchors")
    if not isinstance(anchors, dict):
        raise RuntimeError("Drop-switch plan is missing sourceAnchors")
    from_build = anchor_source_seconds(anchors, "fromBuildStart")
    from_drop = anchor_source_seconds(anchors, "fromDropStart")
    to_drop = anchor_source_seconds(anchors, "toDropStart")
    outgoing_source_start = float(outgoing.get("sourceStartSeconds") or 0.0)
    outgoing_timeline_start = float(outgoing.get("timelineStartSeconds") or 0.0)
    incoming_source_start = float(incoming.get("sourceStartSeconds") or 0.0)

    aligned_drop_timeline = outgoing_timeline_start + (from_drop - outgoing_source_start) / outgoing_ratio
    incoming_timeline_start = aligned_drop_timeline - (to_drop - incoming_source_start) / incoming_ratio
    incoming["timelineStartSeconds"] = round_float(incoming_timeline_start)
    if incoming.get("sourceEndSeconds") is not None:
        incoming["timelineEndSeconds"] = round_float(
            incoming_timeline_start + (float(incoming["sourceEndSeconds"]) - incoming_source_start) / incoming_ratio
        )
    if outgoing.get("sourceEndSeconds") is not None:
        outgoing["timelineEndSeconds"] = round_float(
            outgoing_timeline_start + (float(outgoing["sourceEndSeconds"]) - outgoing_source_start) / outgoing_ratio
        )

    transition["timelineStartSeconds"] = round_float(outgoing_timeline_start + (from_build - outgoing_source_start) / outgoing_ratio)
    transition["timelineEndSeconds"] = round_float(aligned_drop_timeline)
    transition["alignedDropTimelineSeconds"] = round_float(aligned_drop_timeline)
    if transition.get("handoffTimelineSeconds") is not None and outgoing.get("sourceEndSeconds") is not None:
        transition["handoffTimelineSeconds"] = round_float(
            outgoing_timeline_start + (float(outgoing["sourceEndSeconds"]) - outgoing_source_start) / outgoing_ratio
        )

    output_plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")


def transfer_effective_nudge_to_source_plan(raw_plan_path: Path, proof_nudged_path: Path, output_plan_path: Path) -> None:
    raw = read_json(raw_plan_path)
    proof = read_json(proof_nudged_path)
    raw_transition = first_transition(raw)
    proof_transition = first_transition(proof)
    raw_placements = placements_by_id(raw)
    proof_placements = placements_by_id(proof)
    incoming_id = str(raw_transition["toPlacementId"])
    raw_incoming = raw_placements[incoming_id]
    proof_incoming = proof_placements[str(proof_transition["toPlacementId"])]
    incoming_track_id = str(raw_incoming["trackId"])
    raw_incoming["sourceStartSeconds"] = proof_incoming["sourceStartSeconds"]

    proof_load = load_command_for_track(proof, incoming_track_id)
    raw_load = load_command_for_track(raw, incoming_track_id)
    if proof_load is not None and raw_load is not None and proof_load.get("cueSeconds") is not None:
        raw_load["cueSeconds"] = proof_load["cueSeconds"]

    raw_annotations = raw.setdefault("annotations", [])
    if isinstance(raw_annotations, list):
        for annotation in proof.get("annotations", []):
            if not isinstance(annotation, dict):
                continue
            message = str(annotation.get("message") or "")
            if "Incoming source transient nudge applied" not in message:
                continue
            copied = json.loads(json.dumps(annotation))
            copied["at"] = raw_transition.get("timelineStartSeconds", copied.get("at", 0.0))
            raw_annotations.append(copied)

    output_plan_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


def tempo_plan_payload(source_bpm: float, target_bpm: float) -> dict[str, Any]:
    return {
        "sourceBpm": round_float(source_bpm),
        "targetBpm": round_float(target_bpm),
        "tempoRatio": round_float(target_bpm / source_bpm),
        "preservePitch": True,
        "backend": "soundstretch",
        "backendVersion": "2.3.2",
        "quality": "standard",
        "targetBpmBias": 0.0,
        "validationStatus": "pending",
        "requiresRenderedBpmValidation": True,
        "warnings": [
            "Outgoing deck is already playing at this effective BPM from a prior stretched drop switch.",
        ],
    }


def first_transition(plan: dict[str, Any]) -> dict[str, Any]:
    transitions = plan.get("transitions")
    if not isinstance(transitions, list) or not transitions or not isinstance(transitions[0], dict):
        raise RuntimeError("MixPlan is missing its transition")
    return transitions[0]


def placements_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    placements = plan.get("tracks")
    if not isinstance(placements, list):
        raise RuntimeError("MixPlan is missing tracks")
    return {str(placement["placementId"]): placement for placement in placements if isinstance(placement, dict)}


def anchor_source_seconds(anchors: dict[str, Any], name: str) -> float:
    anchor = anchors.get(name)
    if not isinstance(anchor, dict) or anchor.get("sourceSeconds") is None:
        raise RuntimeError(f"Drop-switch plan is missing source anchor: {name}")
    return float(anchor["sourceSeconds"])


def load_command_for_track(plan: dict[str, Any], track_id: str) -> dict[str, Any] | None:
    commands = plan.get("commands")
    if not isinstance(commands, list):
        return None
    for command in commands:
        if isinstance(command, dict) and command.get("type") == "load" and command.get("trackId") == track_id:
            return command
    return None


def try_create_pair(
    *,
    kind: str,
    index: int,
    outgoing: TrackRow,
    incoming: TrackRow,
    outgoing_effective_bpm: float | None = None,
    pairs_root: Path,
    mixplan_tool: Path,
    project_root: Path,
    audio_folder: Path,
    max_tempo_adjustment_bpm: float,
    min_nudge_confidence: float,
    min_stretched_drop_switch_nudge_confidence: float,
    max_drop_switch_nudge_ms: float,
    max_nudge_anchor_disagreement_ms: float,
    prove_rendered_drop_switch_alignment: bool,
    max_rendered_alignment_correction_ms: float,
    max_rendered_probe_residual_ms: float,
) -> dict[str, Any] | None:
    safe_name = safe_transition_name(kind, index, outgoing.track_id, incoming.track_id)
    pair_dir = pairs_root / safe_name
    if pair_dir.exists():
        shutil.rmtree(pair_dir)
    pair_dir.mkdir(parents=True, exist_ok=True)

    expected_template = "second_build_drop_switch_v1" if kind == "drop-switch" else "drop_end_wash_out_v1"
    target_bpm = outgoing.normalized_bpm if kind != "drop-switch" else float(outgoing_effective_bpm or outgoing.normalized_bpm)
    outgoing_artifact_path = outgoing.artifact_path
    outgoing_is_effective = (
        kind == "drop-switch"
        and not math.isclose(target_bpm, outgoing.normalized_bpm, rel_tol=0.0, abs_tol=0.0001)
    )
    if outgoing_is_effective:
        outgoing_artifact_path = write_effective_bpm_artifact(outgoing, target_bpm, pair_dir)
    args = [
        str(mixplan_tool),
        "--out",
        planner_arg_path(pair_dir, project_root),
        "--plan-id",
        safe_name,
        "--max-tempo-adjustment-bpm",
        invariant(max_tempo_adjustment_bpm),
        "--tempo-backend",
        "soundstretch",
        "--tempo-quality",
        "standard",
        "--json",
    ]
    if kind == "drop-switch":
        args.insert(-1, "--allow-tempo-stretch")
    else:
        args.insert(-1, "--disable-tempo-stretch")
    args.extend([planner_arg_path(outgoing_artifact_path, project_root), planner_arg_path(incoming.artifact_path, project_root)])

    proc = subprocess.run(args, cwd=project_root, text=True, capture_output=True)
    (pair_dir / "planner-stdout.json").write_text(proc.stdout, encoding="utf-8")
    if proc.returncode != 0:
        print(
            f"  rejected {kind}: planner failed {outgoing.track_id} -> {incoming.track_id}: "
            f"{(proc.stderr or proc.stdout or '').strip()[:300]}"
        )
        shutil.rmtree(pair_dir, ignore_errors=True)
        return None
    summary = read_json(pair_dir / "planner-summary.json")
    if summary.get("selectedTemplateId") != expected_template:
        print(
            f"  rejected {kind}: template mismatch {outgoing.track_id} -> {incoming.track_id}: "
            f"selected={summary.get('selectedTemplateId')} expected={expected_template}"
        )
        shutil.rmtree(pair_dir, ignore_errors=True)
        return None

    raw_plan = pair_dir / "mix-plan.json"
    nudged_plan = pair_dir / "mix-plan-nudged.json"
    nudge_summary: dict[str, Any]
    try:
        nudge_input_plan = raw_plan
        nudge_output_plan = nudged_plan
        proof_plan = pair_dir / "mix-plan-effective-nudge-input.json"
        proof_nudged_plan = pair_dir / "mix-plan-effective-nudged.json"
        if outgoing_is_effective:
            write_effective_nudge_plan(
                raw_plan,
                proof_plan,
                outgoing_native_bpm=outgoing.normalized_bpm,
                outgoing_effective_bpm=target_bpm,
            )
            nudge_input_plan = proof_plan
            nudge_output_plan = proof_nudged_plan
        nudge_summary = run_wsl_json(
            project_root,
            "autodj-analysis nudge-mixplan "
            f"{quote_wsl(nudge_input_plan)} "
            f"--out {quote_wsl(nudge_output_plan)} "
            f"--asset-root {quote_wsl(audio_folder)} "
            "--window-ms 80 --max-nudge-ms 80 "
            + (
                f"--prove-rendered-alignment --max-rendered-correction-ms {invariant(max_rendered_alignment_correction_ms)} "
                if kind == "drop-switch" and prove_rendered_drop_switch_alignment
                else ""
            )
            + (
                f"--max-rendered-probe-residual-ms {invariant(max_rendered_probe_residual_ms)} "
                if kind == "drop-switch" and prove_rendered_drop_switch_alignment
                else ""
            )
            + "--json",
        )
        if outgoing_is_effective:
            transfer_effective_nudge_to_source_plan(raw_plan, proof_nudged_plan, nudged_plan)
    except RuntimeError as exc:
        if kind != "wash-out":
            print(f"  rejected {kind}: nudge failed {outgoing.track_id} -> {incoming.track_id}: {exc}")
            shutil.rmtree(pair_dir, ignore_errors=True)
            return None
        print(
            "  warning: keeping raw wash-out without nudge "
            f"{outgoing.track_id} -> {incoming.track_id}: {exc}"
        )
        nudge_summary = {
            "ok": False,
            "warning": "wash_out_nudge_failed_raw_plan_used",
            "message": str(exc),
            "confidence": 0.0,
            "nudgeMilliseconds": 0.0,
            "anchorNudges": [],
        }
        shutil.copyfile(raw_plan, nudged_plan)
    write_json(pair_dir / "nudge-summary.json", nudge_summary)
    requires_tempo_stretch = kind == "drop-switch" and (
        abs(target_bpm - incoming.normalized_bpm) > 0.0001
        or abs(target_bpm - outgoing.normalized_bpm) > 0.0001
    )
    required_nudge_confidence = (
        max(min_nudge_confidence, min_stretched_drop_switch_nudge_confidence)
        if requires_tempo_stretch
        else min_nudge_confidence
    )
    if kind == "drop-switch" and not nudge_quality_ok(
        nudge_summary,
        required_nudge_confidence,
        max_drop_switch_nudge_ms,
        max_nudge_anchor_disagreement_ms,
    ):
        print(
            "  rejected drop-switch nudge "
            f"{outgoing.track_id} -> {incoming.track_id}: "
            f"confidence={nudge_summary.get('confidence')} requiredConfidence={required_nudge_confidence} "
            f"nudgeMs={nudge_summary.get('nudgeMilliseconds')} "
            f"maxAbsNudgeMs={max_drop_switch_nudge_ms}"
        )
        shutil.rmtree(pair_dir, ignore_errors=True)
        return None

    final_plan = nudged_plan
    gain_summary: dict[str, Any] | None = None
    if kind == "drop-switch":
        gain_plan = pair_dir / "mix-plan-gain-planned.json"
        gain_report = pair_dir / "energy-report.json"
        try:
            gain_summary = run_wsl_json(
                project_root,
                "autodj-analysis gain-plan-drop-switch "
                f"{quote_wsl(nudged_plan)} "
                f"--out {quote_wsl(gain_plan)} "
                f"--report {quote_wsl(gain_report)} "
                f"--asset-root {quote_wsl(audio_folder)} "
                "--json",
            )
            write_json(pair_dir / "gain-plan-summary.json", gain_summary)
            final_plan = gain_plan
        except RuntimeError as exc:
            print(f"  warning: gain planning failed; using nudged plan: {exc}")

    final_copy = pair_dir / "mix-plan-final.json"
    shutil.copyfile(final_plan, final_copy)
    print(
        f"  accepted {kind}: {outgoing.track_id} -> {incoming.track_id} "
        f"nudgeMs={nudge_summary.get('nudgeMilliseconds')} confidence={nudge_summary.get('confidence')}"
    )
    return {
        "kind": kind,
        "outgoing": outgoing,
        "incoming": incoming,
        "pair_dir": pair_dir,
        "final_plan_path": final_copy,
        "planner": summary,
        "nudge": nudge_summary,
        "gain": gain_summary,
        "outgoing_effective_bpm": target_bpm,
        "tempo_delta_bpm": abs(target_bpm - incoming.normalized_bpm) if kind == "drop-switch" else 0.0,
    }


def merge_pair_plans(
    steps: list[dict[str, Any]],
    run_name: str,
    *,
    washout_sweep_uri: str = DEFAULT_WASHOUT_SWEEP_URI,
) -> dict[str, Any]:
    global_plan: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "planId": run_name,
        "createdAtUtc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "strategy": {
            "strategyId": "dubstep-full-set-poc",
            "strategyVersion": "0.1.0",
            "randomSeed": run_name,
        },
        "assets": [],
        "tracks": [],
        "transitions": [],
        "commands": [],
        "annotations": [],
    }
    assets_by_id: dict[str, dict[str, Any]] = {}
    current: CurrentPlacement | None = None

    for index, step in enumerate(steps, start=1):
        pair = read_json(step["final_plan_path"])
        transition = pair["transitions"][0]
        placements_by_id = {placement["placementId"]: placement for placement in pair.get("tracks", [])}
        pair_outgoing = placements_by_id[transition["fromPlacementId"]]
        pair_incoming = placements_by_id[transition["toPlacementId"]]
        old_out_deck = int(pair_outgoing["deck"])
        old_in_deck = int(pair_incoming["deck"])

        if current is None:
            current = CurrentPlacement(
                track_id=str(pair_outgoing["trackId"]),
                placement_id=f"set-{index:03d}-{pair_outgoing['placementId']}",
                deck=old_out_deck,
                source_start=float(pair_outgoing["sourceStartSeconds"]),
                timeline_start=float(pair_outgoing["timelineStartSeconds"]),
                tempo_ratio=tempo_ratio(pair_outgoing),
            )
        incoming_deck = 1 if current.deck == 2 else 2
        deck_map = {old_out_deck: current.deck, old_in_deck: incoming_deck, 3: 3}

        def map_time(value: float | int | None) -> float | None:
            if value is None:
                return None
            return current.timeline_start + (float(value) - current.source_start) / current.tempo_ratio

        id_map: dict[str, str] = {pair_outgoing["placementId"]: current.placement_id}

        for asset in pair.get("assets", []):
            track_id = str(asset.get("trackId"))
            normalized_asset = json.loads(json.dumps(asset))
            if track_id == "washout-sweep-fx":
                normalized_asset["sourceUri"] = washout_sweep_uri
            assets_by_id.setdefault(track_id, normalized_asset)

        for placement in pair.get("tracks", []):
            is_pair_outgoing = placement["placementId"] == pair_outgoing["placementId"]
            if is_pair_outgoing and index > 1:
                continue
            new_placement = json.loads(json.dumps(placement))
            original_id = str(new_placement["placementId"])
            new_placement["placementId"] = f"set-{index:03d}-{original_id}"
            if str(new_placement["trackId"]) == "washout-sweep-fx":
                new_placement["placementId"] = f"set-{index:03d}-place-washout-sweep-fx"
            new_placement["deck"] = deck_map.get(int(new_placement["deck"]), int(new_placement["deck"]))
            new_placement["timelineStartSeconds"] = round_float(map_time(new_placement["timelineStartSeconds"]))
            if new_placement.get("timelineEndSeconds") is not None:
                new_placement["timelineEndSeconds"] = round_float(map_time(new_placement["timelineEndSeconds"]))
            global_plan["tracks"].append(new_placement)
            id_map[original_id] = new_placement["placementId"]

        incoming_global = next(
            placement for placement in global_plan["tracks"] if placement["placementId"] == id_map[pair_incoming["placementId"]]
        )

        new_transition = json.loads(json.dumps(transition))
        new_transition["transitionId"] = f"set-{index:03d}-{new_transition['transitionId']}"
        new_transition["fromPlacementId"] = current.placement_id
        new_transition["toPlacementId"] = incoming_global["placementId"]
        for field in ("timelineStartSeconds", "timelineEndSeconds", "handoffTimelineSeconds", "alignedDropTimelineSeconds"):
            if new_transition.get(field) is not None:
                new_transition[field] = round_float(map_time(new_transition[field]))
        global_plan["transitions"].append(new_transition)

        outgoing_stop_times: list[float] = []
        for command in pair.get("commands", []):
            old_deck = command.get("deck")
            if command.get("type") == "automate" and command.get("control") == "tempo":
                # Full-set rendering relies on per-placement tempoPlan values.
                # Carrying pair-level tempo automation onto reused decks looks
                # like a dynamic deck tempo ramp to the offline renderer.
                continue
            if index > 1 and old_deck == old_out_deck and command.get("type") in ("load", "play") and float(command.get("at", 0.0)) <= 0.001:
                continue
            new_command = json.loads(json.dumps(command))
            if old_deck is not None:
                new_command["deck"] = deck_map.get(int(old_deck), int(old_deck))
            new_command["at"] = round_float(map_time(new_command.get("at", 0.0)))
            if isinstance(new_command.get("keyframes"), list):
                for keyframe in new_command["keyframes"]:
                    keyframe["at"] = round_float(map_time(keyframe.get("at", 0.0)))
            global_plan["commands"].append(new_command)
            if command.get("type") == "stop" and old_deck == old_out_deck:
                outgoing_stop_times.append(float(new_command["at"]))

        outgoing_end = outgoing_stop_times[0] if outgoing_stop_times else transition_completion_time(new_transition)
        truncate_placement(global_plan["tracks"], current.placement_id, outgoing_end)

        inject_incoming_resets(global_plan["commands"], incoming_deck, float(incoming_global["timelineStartSeconds"]), step["kind"])

        for annotation in pair.get("annotations", []):
            new_annotation = json.loads(json.dumps(annotation))
            new_annotation["at"] = round_float(map_time(new_annotation.get("at", 0.0)))
            if new_annotation.get("placementId") in id_map:
                new_annotation["placementId"] = id_map[new_annotation["placementId"]]
            new_annotation["transitionId"] = new_transition["transitionId"]
            global_plan["annotations"].append(new_annotation)

        current = CurrentPlacement(
            track_id=str(incoming_global["trackId"]),
            placement_id=str(incoming_global["placementId"]),
            deck=int(incoming_global["deck"]),
            source_start=float(incoming_global["sourceStartSeconds"]),
            timeline_start=float(incoming_global["timelineStartSeconds"]),
            tempo_ratio=tempo_ratio(incoming_global),
        )

    global_plan["assets"] = list(assets_by_id.values())
    sort_commands(global_plan["commands"])
    global_plan["tracks"].sort(key=lambda item: (float(item.get("timelineStartSeconds", 0.0)), int(item.get("deck", 0))))
    global_plan["transitions"].sort(key=lambda item: float(item.get("timelineStartSeconds", 0.0)))
    global_plan["annotations"].sort(key=lambda item: float(item.get("at", 0.0)))
    return global_plan


def validate_full_set_plan(plan: dict[str, Any], *, asset_root: Path | None = None) -> dict[str, Any]:
    placement_rows = [placement for placement in plan.get("tracks", []) if isinstance(placement, dict)]
    transition_rows = [item for item in plan.get("transitions", []) if isinstance(item, dict)]
    asset_rows = [asset for asset in plan.get("assets", []) if isinstance(asset, dict)]
    placements = {str(placement.get("placementId")): placement for placement in placement_rows}
    assets = {str(asset.get("trackId")): asset for asset in asset_rows}
    commands = [command for command in plan.get("commands", []) if isinstance(command, dict)]
    errors: list[dict[str, Any]] = []

    add_duplicate_id_errors(errors, asset_rows, "trackId", "duplicate_asset_track_id")
    add_duplicate_id_errors(errors, placement_rows, "placementId", "duplicate_placement_id")
    add_duplicate_id_errors(errors, transition_rows, "transitionId", "duplicate_transition_id")

    for placement in placement_rows:
        track_id = str(placement.get("trackId", ""))
        if track_id not in assets:
            errors.append(
                {
                    "code": "placement_missing_asset",
                    "placementId": placement.get("placementId"),
                    "trackId": track_id,
                }
            )
        else:
            source_uri = str(assets[track_id].get("sourceUri") or "")
            if asset_root is not None and source_uri and not source_uri_resolvable(source_uri, asset_root=asset_root):
                errors.append(
                    {
                        "code": "asset_source_unresolved",
                        "trackId": track_id,
                        "sourceUri": source_uri,
                        "assetRoot": str(asset_root),
                    }
                )
        validate_tempo_plan(errors, placement)

    validate_tempo_automation(errors, commands)

    for transition in transition_rows:
        from_id = str(transition.get("fromPlacementId", ""))
        from_placement = placements.get(from_id)
        if not from_placement:
            errors.append({"code": "missing_from_placement", "transitionId": transition.get("transitionId"), "placementId": from_id})
            continue
        to_id = str(transition.get("toPlacementId", ""))
        to_placement = placements.get(to_id)
        if not to_placement:
            errors.append({"code": "missing_to_placement", "transitionId": transition.get("transitionId"), "placementId": to_id})
            continue
        placement_end = float(from_placement.get("timelineEndSeconds", from_placement.get("timelineStartSeconds", 0.0)))
        transition_start = float(transition.get("timelineStartSeconds", 0.0))
        stop_times = [
            float(command.get("at", 0.0))
            for command in commands
            if command.get("type") == "stop"
            and int(command.get("deck", -1)) == int(from_placement.get("deck", -2))
            and float(command.get("at", 0.0)) >= transition_start - 0.001
        ]
        if stop_times:
            expected_stop = min(stop_times)
            if placement_end > expected_stop + 0.001:
                errors.append(
                    {
                        "code": "outgoing_placement_overruns_stop",
                        "transitionId": transition.get("transitionId"),
                        "trackId": from_placement.get("trackId"),
                        "placementEndSeconds": placement_end,
                        "stopSeconds": expected_stop,
                    }
                )

        validate_incoming_resets(errors, transition, to_placement, commands)

        if transition.get("templateId") != "second_build_drop_switch_v1":
            continue
        start = float(transition.get("timelineStartSeconds", 0.0))
        end = float(transition.get("timelineEndSeconds", start))
        decks = {int(from_placement.get("deck", -2)), int(to_placement.get("deck", -3))}
        for command in commands:
            if command.get("type") != "automate":
                continue
            if command.get("control") not in {"reverbWet", "reverbTailGain", "echoWet"}:
                continue
            if int(command.get("deck", -1)) not in decks:
                continue
            at = float(command.get("at", 0.0))
            if not start < at < end:
                continue
            if any(float(keyframe.get("value", 0.0)) > 0.0 for keyframe in command.get("keyframes", []) if isinstance(keyframe, dict)):
                errors.append(
                    {
                        "code": "drop_switch_wet_fx_automation",
                        "transitionId": transition.get("transitionId"),
                        "deck": command.get("deck"),
                        "control": command.get("control"),
                        "at": at,
                    }
                )

    return {
        "ok": not errors,
        "errorCount": len(errors),
        "errors": errors[:20],
        "checkedRules": [
            "asset, placement, and transition ids must be unique",
            "every placement must reference a resolvable asset",
            "tempo plans must be supported by the offline renderer",
            "tempo automation must be constant per deck",
            "outgoing placements must not outlive their transition stop command",
            "incoming deck wet FX state must be reset at placement start",
            "drop-switch transition windows must not contain positive reverb/tail/echo automation",
        ],
    }


def add_duplicate_id_errors(errors: list[dict[str, Any]], rows: list[dict[str, Any]], field: str, code: str) -> None:
    seen: dict[str, int] = {}
    for row in rows:
        value = str(row.get(field) or "")
        if not value:
            continue
        seen[value] = seen.get(value, 0) + 1
    for value, count in seen.items():
        if count > 1:
            errors.append({"code": code, field: value, "count": count})


def source_uri_resolvable(source_uri: str, *, asset_root: Path) -> bool:
    if source_uri.startswith("generated://"):
        return True
    if "://" in source_uri and not source_uri.startswith("file://"):
        return True
    if source_uri.startswith("file://"):
        parsed = urlparse(source_uri)
        if parsed.netloc and parsed.netloc not in {"localhost", ""}:
            raw = f"//{parsed.netloc}{parsed.path}"
        else:
            raw = parsed.path
        raw = unquote(raw)
    else:
        raw = source_uri
    path = host_path(raw)
    if path.is_absolute() and path.exists():
        return True
    if (asset_root / path).exists():
        return True
    return (Path.cwd() / path).exists()


def validate_tempo_plan(errors: list[dict[str, Any]], placement: dict[str, Any]) -> None:
    tempo_plan = placement.get("tempoPlan")
    if tempo_plan is None:
        return
    if not isinstance(tempo_plan, dict):
        errors.append({"code": "invalid_tempo_plan", "placementId": placement.get("placementId"), "message": "tempoPlan must be an object"})
        return
    source = optional_number(tempo_plan, "sourceBpm")
    target = optional_number(tempo_plan, "targetBpm")
    ratio = optional_number(tempo_plan, "tempoRatio")
    bias = float(tempo_plan.get("targetBpmBias", 0.0) or 0.0)
    if source is not None and target is not None:
        if source <= 0.0 or target + bias <= 0.0:
            errors.append(
                {
                    "code": "invalid_tempo_plan_bpm",
                    "placementId": placement.get("placementId"),
                    "sourceBpm": source,
                    "targetBpm": target,
                    "targetBpmBias": bias,
                }
            )
        if not bool(tempo_plan.get("preservePitch", True)):
            errors.append(
                {
                    "code": "preserve_pitch_required",
                    "placementId": placement.get("placementId"),
                    "message": "Tempo-stretched placements must preserve pitch for the current renderer.",
                }
            )
    elif ratio is not None and ratio <= 0.0:
        errors.append({"code": "invalid_tempo_ratio", "placementId": placement.get("placementId"), "tempoRatio": ratio})


def validate_tempo_automation(errors: list[dict[str, Any]], commands: list[dict[str, Any]]) -> None:
    by_deck: dict[int | None, list[float]] = {}
    for command in commands:
        if command.get("type") != "automate" or command.get("control") != "tempo":
            continue
        deck = command.get("deck")
        deck_key = int(deck) if deck is not None else None
        values = by_deck.setdefault(deck_key, [])
        for keyframe in command.get("keyframes") or []:
            if isinstance(keyframe, dict):
                values.append(float(keyframe.get("value", 1.0)))
    for deck, values in by_deck.items():
        if len(values) <= 1:
            continue
        first = values[0]
        if any(not math.isclose(value, first, rel_tol=0.0, abs_tol=0.000001) for value in values[1:]):
            errors.append({"code": "tempo_ramp_unsupported", "deck": deck, "values": values[:8]})


def validate_incoming_resets(
    errors: list[dict[str, Any]],
    transition: dict[str, Any],
    to_placement: dict[str, Any],
    commands: list[dict[str, Any]],
) -> None:
    deck = int(to_placement.get("deck", -1))
    start = float(to_placement.get("timelineStartSeconds", 0.0))
    expected = {"reverbWet": 0.0, "reverbTailGain": 0.0, "echoWet": 0.0}
    if transition.get("templateId") == "drop_end_wash_out_v1":
        expected.update({"volume": 1.0, "eqLow": 1.0, "eqMid": 1.0, "eqHigh": 1.0})
    for control, value in expected.items():
        if not has_control_reset(commands, deck=deck, control=control, expected_value=value, at=start):
            errors.append(
                {
                    "code": "missing_incoming_control_reset",
                    "transitionId": transition.get("transitionId"),
                    "placementId": to_placement.get("placementId"),
                    "deck": deck,
                    "control": control,
                    "expectedValue": value,
                    "atOrBeforeSeconds": start,
                }
            )


def has_control_reset(
    commands: list[dict[str, Any]],
    *,
    deck: int,
    control: str,
    expected_value: float,
    at: float,
) -> bool:
    for command in commands:
        if command.get("type") != "automate" or command.get("control") != control:
            continue
        if int(command.get("deck", -1)) != deck:
            continue
        if float(command.get("at", 0.0)) > at + 0.001:
            continue
        for keyframe in command.get("keyframes") or []:
            if not isinstance(keyframe, dict):
                continue
            keyframe_at = float(keyframe.get("at", command.get("at", 0.0)))
            keyframe_value = float(keyframe.get("value", -999.0))
            if keyframe_at <= at + 0.001 and math.isclose(keyframe_value, expected_value, rel_tol=0.0, abs_tol=0.000001):
                return True
    return False


def optional_number(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    return float(value)


def transition_completion_time(transition: dict[str, Any]) -> float:
    for field in ("timelineEndSeconds", "handoffTimelineSeconds", "timelineStartSeconds"):
        value = transition.get(field)
        if isinstance(value, int | float):
            return float(value)
    return 0.0


def truncate_placement(placements: list[dict[str, Any]], placement_id: str, end_seconds: float) -> None:
    for placement in placements:
        if placement.get("placementId") != placement_id:
            continue
        timeline_start = float(placement.get("timelineStartSeconds", 0.0))
        current_end = placement.get("timelineEndSeconds")
        bounded_end = round_float(max(timeline_start, end_seconds))
        if current_end is None or bounded_end < float(current_end):
            placement["timelineEndSeconds"] = bounded_end
        return


def inject_incoming_resets(commands: list[dict[str, Any]], deck: int, at: float, kind: str) -> None:
    reset_controls = [("reverbWet", 0.0), ("reverbTailGain", 0.0), ("echoWet", 0.0)]
    if kind == "wash-out":
        reset_controls = [("volume", 1.0), ("eqLow", 1.0), ("eqMid", 1.0), ("eqHigh", 1.0), *reset_controls]
    for control, value in reset_controls:
        commands.append(
            {
                "type": "automate",
                "at": round_float(at),
                "deck": deck,
                "control": control,
                "keyframes": [{"at": round_float(at), "value": value, "interpolation": "hold"}],
            }
        )


def sort_commands(commands: list[dict[str, Any]]) -> None:
    priority = {"stop": 0, "load": 1, "seek": 2, "automate": 3, "setLoop": 3, "play": 4}
    commands.sort(key=lambda command: (float(command.get("at", 0.0)), priority.get(str(command.get("type")), 5)))


def key_compatibility(outgoing: TrackRow, incoming: TrackRow) -> dict[str, Any]:
    minimum_confidence = 0.65
    first = parse_camelot(outgoing.camelot_key)
    second = parse_camelot(incoming.camelot_key)
    if first is None or second is None:
        return {"compatible": False, "score": 0.4, "classification": "unknown"}
    if outgoing.key_confidence < minimum_confidence or incoming.key_confidence < minimum_confidence:
        return {"compatible": False, "score": 0.45, "classification": "unknown"}
    if first == second:
        return {"compatible": True, "score": 1.0, "classification": "perfect"}
    if first[0] == second[0] and first[1] != second[1]:
        return {"compatible": True, "score": 0.9, "classification": "relative"}
    if first[1] == second[1] and (((first[0] % 12) + 1 == second[0]) or ((second[0] % 12) + 1 == first[0])):
        return {"compatible": True, "score": 0.8, "classification": "adjacent"}
    return {"compatible": False, "score": 0.0, "classification": "clash"}


def drop_switch_key_rejected(key: dict[str, Any], policy: str) -> bool:
    if policy == "allow-unknown":
        return str(key.get("classification")) == "clash"
    return not bool(key.get("compatible"))


def parse_camelot(value: str) -> tuple[int, str] | None:
    value = value.strip().upper()
    if len(value) not in (2, 3):
        return None
    number_text = value[:-1]
    letter = value[-1]
    if letter not in ("A", "B") or not number_text.isdigit():
        return None
    number = int(number_text)
    if number < 1 or number > 12:
        return None
    return number, letter


def nudge_quality_ok(
    summary: dict[str, Any],
    min_confidence: float,
    max_abs_nudge_ms: float,
    max_disagreement_ms: float,
) -> bool:
    if not summary.get("ok"):
        return False
    if float(summary.get("confidence") or 0.0) < min_confidence:
        return False
    if abs(float(summary.get("nudgeMilliseconds") or 0.0)) > max_abs_nudge_ms:
        return False
    nudges = [float(item.get("nudgeSeconds") or 0.0) for item in summary.get("anchorNudges") or []]
    if len(nudges) >= 2 and (max(nudges) - min(nudges)) * 1000.0 > max_disagreement_ms:
        return False
    return True


def tempo_ratio(placement: dict[str, Any]) -> float:
    plan = placement.get("tempoPlan") or {}
    if not isinstance(plan, dict):
        return 1.0
    if plan.get("tempoRatio"):
        return float(plan["tempoRatio"])
    source = plan.get("sourceBpm")
    target = plan.get("targetBpm")
    if source and target:
        return float(target) / float(source)
    return 1.0


def run_wsl_json(project_root: Path, command: str) -> dict[str, Any]:
    full_command = (
        "set -o pipefail; "
        f"cd {quote_wsl(project_root)} && "
        "source .venv-analysis/bin/activate && "
        f"{command}"
    )
    proc = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu-24.04", "--", "bash", "-lc", full_command],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip())
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Expected JSON from command but got: {proc.stdout[:500]}") from exc


def quote_wsl(path: Path) -> str:
    return shlex.quote(to_wsl_path(path))


def planner_arg_path(path: Path, project_root: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(resolved)


def to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    resolved_text = str(resolved).replace("\\", "/")
    if resolved_text.startswith("/mnt/"):
        return resolved_text
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        return resolved_text
    parts = resolved.parts[1:]
    return "/mnt/" + drive + "/" + "/".join(part.replace("\\", "/") for part in parts)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def safe_transition_name(kind: str, index: int, outgoing: str, incoming: str) -> str:
    return f"{kind}-{index:03d}-{shorten(outgoing)}-to-{shorten(incoming)}"


def shorten(value: str, limit: int = 28) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in safe:
        safe = safe.replace("--", "-")
    safe = safe.strip("-") or "track"
    return safe[:limit].strip("-")


def invariant(value: float) -> str:
    return format(float(value), ".15g")


def round_float(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(float(value)):
        return value
    return round(float(value), 12)


if __name__ == "__main__":
    raise SystemExit(main())
