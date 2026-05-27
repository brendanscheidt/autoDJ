"""Generate a continuous AutoDJ POC set from analyzed tracks.

This script intentionally reuses the proven pairwise planner path:

1. choose a diversified track order;
2. generate each pair transition with the C++ planner;
3. run the Python nudge pass on every transition;
4. run the drop-switch energy/gain post-pass for drop switches;
5. merge the pair MixPlans onto one continuous timeline;
6. render one WAV.

It is a POC set builder, not the final set-planning engine.
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
from typing import Any


PROJECT_ROOT = Path(r"C:\Users\Brendan\Dev\AudioProj")
DEFAULT_AUDIO_FOLDER = Path(r"C:\Users\Brendan\Desktop\AutoDJTestDubstep")
DEFAULT_ANALYSIS_ROOT = (
    PROJECT_ROOT
    / ".autodj-cache"
    / "transition-auditions"
    / "keyed-rekordbox-semantic-truth-20260524-095821"
    / "analysis"
)


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a continuous AutoDJ full-set POC WAV.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--audio-folder", type=Path, default=DEFAULT_AUDIO_FOLDER)
    parser.add_argument("--analysis-root", type=Path, default=DEFAULT_ANALYSIS_ROOT)
    parser.add_argument("--run-name", default=f"full-set-poc-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--track-count", type=int, default=48)
    parser.add_argument("--seed", default="full-set-poc-v1")
    parser.add_argument("--max-tempo-adjustment-bpm", type=float, default=10.0)
    parser.add_argument("--min-nudge-confidence", type=float, default=0.58)
    parser.add_argument("--max-nudge-anchor-disagreement-ms", type=float, default=30.0)
    parser.add_argument("--sample-rate", type=int, default=44_100)
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    output_root = project_root / ".autodj-cache" / "full-set-poc" / args.run_name
    pairs_root = output_root / "pairs"
    output_root.mkdir(parents=True, exist_ok=True)
    pairs_root.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    tracks = load_tracks(args.analysis_root.resolve())
    if len(tracks) < 2:
        raise SystemExit("Need at least two analyzed tracks.")

    mixplan_tool = project_root / "build" / "debug" / "core" / "dj" / "Debug" / "autodj_mixplan_poc.exe"
    if not mixplan_tool.exists():
        raise SystemExit(f"Missing planner tool: {mixplan_tool}")

    print(f"Loaded tracks: {len(tracks)}")
    print(f"Run root: {output_root}")
    print(f"Seed: {args.seed}")

    selected = build_set_sequence(
        tracks=tracks,
        rng=rng,
        track_count=min(args.track_count, len(tracks)),
        pairs_root=pairs_root,
        mixplan_tool=mixplan_tool,
        project_root=project_root,
        audio_folder=args.audio_folder.resolve(),
        max_tempo_adjustment_bpm=args.max_tempo_adjustment_bpm,
        min_nudge_confidence=args.min_nudge_confidence,
        max_nudge_anchor_disagreement_ms=args.max_nudge_anchor_disagreement_ms,
    )
    if not selected:
        raise SystemExit("Could not generate any transitions.")

    full_plan = merge_pair_plans(selected, args.run_name)
    validation = validate_full_set_plan(full_plan)
    if not validation["ok"]:
        raise SystemExit("Generated invalid full-set MixPlan: " + json.dumps(validation, indent=2))
    full_plan_path = output_root / "mix-plan-full-set.json"
    write_json(full_plan_path, full_plan)

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
        "renderPath": str(output_root / "render" / "audition.wav"),
        "validation": validation,
        "sequence": [
            {
                "index": index + 1,
                "kind": step["kind"],
                "outgoingTrackId": step["outgoing"].track_id,
                "incomingTrackId": step["incoming"].track_id,
                "pairPlanPath": str(step["final_plan_path"]),
                "nudgeConfidence": step.get("nudge", {}).get("confidence"),
                "nudgeMilliseconds": step.get("nudge", {}).get("nudgeMilliseconds"),
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

    if not args.skip_render:
        render_dir = output_root / "render"
        render_dir.mkdir(parents=True, exist_ok=True)
        render_result = run_wsl_json(
            project_root,
            "autodj-analysis render-mixplan "
            f"{quote_wsl(full_plan_path)} "
            f"--out {quote_wsl(render_dir)} "
            f"--asset-root {quote_wsl(args.audio_folder.resolve())} "
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
    min_nudge_confidence: float,
    max_nudge_anchor_disagreement_ms: float,
) -> list[dict[str, Any]]:
    unused = tracks[:]
    rng.shuffle(unused)
    starts = [track for track in unused if track.can_outgoing_drop_switch]
    current = rng.choice(starts or unused)
    unused.remove(current)
    selected: list[dict[str, Any]] = []
    print(f"Start track: {current.track_id}")

    step_index = 1
    while unused and len(selected) + 1 < track_count:
        print(f"\nPlanning step {step_index}: outgoing={current.track_id}, remaining={len(unused)}")
        accepted = None

        for candidate in drop_switch_candidates(
            current,
            unused,
            rng,
            max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
        ):
            accepted = try_create_pair(
                kind="drop-switch",
                index=step_index,
                outgoing=current,
                incoming=candidate,
                pairs_root=pairs_root,
                mixplan_tool=mixplan_tool,
                project_root=project_root,
                audio_folder=audio_folder,
                max_tempo_adjustment_bpm=max_tempo_adjustment_bpm,
                min_nudge_confidence=min_nudge_confidence,
                max_nudge_anchor_disagreement_ms=max_nudge_anchor_disagreement_ms,
            )
            if accepted is not None:
                break

        if accepted is None:
            for candidate in wash_out_candidates(current, unused, rng):
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
                    max_nudge_anchor_disagreement_ms=max_nudge_anchor_disagreement_ms,
                )
                if accepted is not None:
                    break

        if accepted is None:
            print(f"Could not find a valid transition out of {current.track_id}; stopping early.")
            break

        selected.append(accepted)
        current = accepted["incoming"]
        unused.remove(current)
        step_index += 1

    return selected


def drop_switch_candidates(
    outgoing: TrackRow,
    candidates: list[TrackRow],
    rng: random.Random,
    *,
    max_tempo_adjustment_bpm: float,
) -> list[TrackRow]:
    if not outgoing.can_outgoing_drop_switch:
        return []
    rows: list[tuple[int, float, float, float, TrackRow]] = []
    for incoming in candidates:
        if not incoming.can_incoming_drop_switch:
            continue
        key = key_compatibility(outgoing, incoming)
        if not key["compatible"]:
            continue
        tempo_delta = abs(outgoing.normalized_bpm - incoming.normalized_bpm)
        if tempo_delta > max_tempo_adjustment_bpm:
            continue
        tempo_priority = 0 if tempo_delta <= 0.0001 else 1
        rows.append((tempo_priority, -key["score"], tempo_delta, rng.random(), incoming))
    rows.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return [item[4] for item in rows]


def wash_out_candidates(outgoing: TrackRow, candidates: list[TrackRow], rng: random.Random) -> list[TrackRow]:
    if not outgoing.can_wash_out:
        return []
    rows: list[tuple[int, float, float, TrackRow]] = []
    for incoming in candidates:
        key = key_compatibility(outgoing, incoming)
        setup_priority = 0 if incoming.can_outgoing_drop_switch else 1
        rows.append((setup_priority, -key["score"], rng.random(), incoming))
    rows.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in rows]


def try_create_pair(
    *,
    kind: str,
    index: int,
    outgoing: TrackRow,
    incoming: TrackRow,
    pairs_root: Path,
    mixplan_tool: Path,
    project_root: Path,
    audio_folder: Path,
    max_tempo_adjustment_bpm: float,
    min_nudge_confidence: float,
    max_nudge_anchor_disagreement_ms: float,
) -> dict[str, Any] | None:
    safe_name = safe_transition_name(kind, index, outgoing.track_id, incoming.track_id)
    pair_dir = pairs_root / safe_name
    if pair_dir.exists():
        shutil.rmtree(pair_dir)
    pair_dir.mkdir(parents=True, exist_ok=True)

    expected_template = "second_build_drop_switch_v1" if kind == "drop-switch" else "drop_end_wash_out_v1"
    args = [
        str(mixplan_tool),
        "--out",
        str(pair_dir),
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
    args.extend([str(outgoing.artifact_path), str(incoming.artifact_path)])

    proc = subprocess.run(args, cwd=project_root, text=True, capture_output=True)
    (pair_dir / "planner-stdout.json").write_text(proc.stdout, encoding="utf-8")
    if proc.returncode != 0:
        shutil.rmtree(pair_dir, ignore_errors=True)
        return None
    summary = read_json(pair_dir / "planner-summary.json")
    if summary.get("selectedTemplateId") != expected_template:
        shutil.rmtree(pair_dir, ignore_errors=True)
        return None

    raw_plan = pair_dir / "mix-plan.json"
    nudged_plan = pair_dir / "mix-plan-nudged.json"
    nudge_summary: dict[str, Any]
    try:
        nudge_summary = run_wsl_json(
            project_root,
            "autodj-analysis nudge-mixplan "
            f"{quote_wsl(raw_plan)} "
            f"--out {quote_wsl(nudged_plan)} "
            f"--asset-root {quote_wsl(audio_folder)} "
            "--window-ms 80 --max-nudge-ms 80 --json",
        )
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
    if kind == "drop-switch" and not nudge_quality_ok(
        nudge_summary,
        min_nudge_confidence,
        max_nudge_anchor_disagreement_ms,
    ):
        print(
            "  rejected drop-switch nudge "
            f"{outgoing.track_id} -> {incoming.track_id}: "
            f"confidence={nudge_summary.get('confidence')} nudgeMs={nudge_summary.get('nudgeMilliseconds')}"
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
    }


def merge_pair_plans(steps: list[dict[str, Any]], run_name: str) -> dict[str, Any]:
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
            assets_by_id.setdefault(track_id, asset)

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


def validate_full_set_plan(plan: dict[str, Any]) -> dict[str, Any]:
    placements = {str(placement.get("placementId")): placement for placement in plan.get("tracks", []) if isinstance(placement, dict)}
    commands = [command for command in plan.get("commands", []) if isinstance(command, dict)]
    errors: list[dict[str, Any]] = []

    for transition in [item for item in plan.get("transitions", []) if isinstance(item, dict)]:
        from_id = str(transition.get("fromPlacementId", ""))
        from_placement = placements.get(from_id)
        if not from_placement:
            errors.append({"code": "missing_from_placement", "transitionId": transition.get("transitionId"), "placementId": from_id})
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

        if transition.get("templateId") != "second_build_drop_switch_v1":
            continue
        to_placement = placements.get(str(transition.get("toPlacementId", "")))
        if not to_placement:
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
            "outgoing placements must not outlive their transition stop command",
            "drop-switch transition windows must not contain positive reverb/tail/echo automation",
        ],
    }


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


def nudge_quality_ok(summary: dict[str, Any], min_confidence: float, max_disagreement_ms: float) -> bool:
    if not summary.get("ok"):
        return False
    if float(summary.get("confidence") or 0.0) < min_confidence:
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


def to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
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
