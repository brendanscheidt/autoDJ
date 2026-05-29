"""Transition preview MixPlan extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TransitionPreviewOptions:
    pre_seconds: float = 32.0
    post_seconds: float = 24.0
    fx_preroll_seconds: float = 2.0


class TransitionPreviewError(ValueError):
    """Expected transition preview extraction failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TransitionPreviewPackOptions:
    preview: TransitionPreviewOptions = field(default_factory=TransitionPreviewOptions)
    render: bool = False
    asset_root: Path | None = None
    sample_rate: int = 44_100


def extract_transition_preview_plan(
    plan: dict[str, Any],
    transition_id: str,
    *,
    options: TransitionPreviewOptions | None = None,
) -> dict[str, Any]:
    """Return a cropped MixPlan around one transition."""

    options = options or TransitionPreviewOptions()
    if options.pre_seconds < 0.0 or options.post_seconds < 0.0 or options.fx_preroll_seconds < 0.0:
        raise TransitionPreviewError("invalid_preview_options", "Preview timing options must be non-negative")

    transition = _find_transition(plan, transition_id)
    transition_start = _number(transition, "timelineStartSeconds", 0.0)
    transition_end = _transition_audition_end(transition)
    audition_start = max(0.0, transition_start - options.pre_seconds)
    preview_start = max(0.0, audition_start - options.fx_preroll_seconds)
    preview_end = max(transition_end, transition_start) + options.post_seconds
    if preview_end <= preview_start:
        raise TransitionPreviewError("invalid_preview_window", "Preview window must have positive duration")

    shifted_transition = _shift_timed_object(transition, preview_start)
    assets_by_track_id = {
        str(asset.get("trackId")): deepcopy(asset)
        for asset in plan.get("assets", [])
        if isinstance(asset, dict) and asset.get("trackId")
    }

    preview_tracks: list[dict[str, Any]] = []
    included_track_ids: set[str] = set()
    for placement in plan.get("tracks", []):
        if not isinstance(placement, dict):
            continue
        clipped = _clip_placement(placement, preview_start, preview_end)
        if clipped is None:
            continue
        preview_tracks.append(clipped)
        included_track_ids.add(str(clipped.get("trackId")))

    if not preview_tracks:
        raise TransitionPreviewError("empty_preview", "No track placements overlap the transition preview window")

    preview_commands = _synthetic_transport_commands(preview_tracks)
    preview_commands.extend(_preview_automation_commands(plan.get("commands", []), preview_start, preview_end))
    preview_commands.sort(key=lambda command: (float(command.get("at", 0.0)), _command_priority(command)))

    preview_annotations = [
        _shift_timed_object(annotation, preview_start)
        for annotation in plan.get("annotations", [])
        if isinstance(annotation, dict)
        and preview_start <= float(annotation.get("at", preview_start - 1.0)) <= preview_end
    ]

    return {
        "schemaVersion": str(plan.get("schemaVersion", "1.0.0")),
        "planId": f"{plan.get('planId', 'mix-plan')}-preview-{transition_id}",
        "createdAtUtc": str(plan.get("createdAtUtc", "")),
        "strategy": deepcopy(plan.get("strategy", {})),
        "assets": [assets_by_track_id[track_id] for track_id in sorted(included_track_ids) if track_id in assets_by_track_id],
        "tracks": sorted(preview_tracks, key=lambda item: (float(item.get("timelineStartSeconds", 0.0)), int(item.get("deck", 0)))),
        "transitions": [shifted_transition],
        "commands": preview_commands,
        "annotations": preview_annotations,
        "preview": {
            "sourcePlanId": plan.get("planId"),
            "sourceTransitionId": transition_id,
            "sourceWindowStartSeconds": _round(preview_start),
            "sourceAuditionStartSeconds": _round(audition_start),
            "sourceWindowEndSeconds": _round(preview_end),
            "durationSeconds": _round(preview_end - preview_start),
        },
    }


def write_transition_preview_pack(
    mix_plan_path: str | Path,
    out_dir: str | Path,
    *,
    options: TransitionPreviewPackOptions | None = None,
) -> dict[str, Any]:
    """Write per-transition preview MixPlans and an index JSON file."""

    options = options or TransitionPreviewPackOptions()
    mix_plan_path = Path(mix_plan_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = json.loads(mix_plan_path.read_text(encoding="utf-8-sig"))
    rows: list[dict[str, Any]] = []

    for index, transition in enumerate(plan.get("transitions", []), start=1):
        if not isinstance(transition, dict):
            continue
        transition_id = str(transition.get("transitionId") or f"transition-{index:03d}")
        preview_dir = out_dir / f"{index:03d}-{_safe_slug(transition_id)}"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_plan_path = preview_dir / "mix-plan-preview.json"
        row: dict[str, Any] = {
            "index": index,
            "transitionId": transition_id,
            "templateId": transition.get("templateId"),
            "technique": transition.get("technique"),
            "previewDir": str(preview_dir),
            "mixPlanPath": str(preview_plan_path),
            "status": "pending",
            "errors": [],
        }
        try:
            preview_plan = extract_transition_preview_plan(plan, transition_id, options=options.preview)
            _write_json(preview_plan_path, preview_plan)
            row["status"] = "planned"
            row["sourceWindowStartSeconds"] = preview_plan["preview"]["sourceWindowStartSeconds"]
            row["sourceWindowEndSeconds"] = preview_plan["preview"]["sourceWindowEndSeconds"]
            row["durationSeconds"] = preview_plan["preview"]["durationSeconds"]
            if options.render:
                from .mixplan_renderer import RenderOptions, render_mix_plan_file

                result = render_mix_plan_file(
                    preview_plan_path,
                    preview_dir,
                    RenderOptions(sample_rate=options.sample_rate, asset_root=options.asset_root),
                )
                row["status"] = "rendered"
                row["outputWav"] = str(result.output_wav)
                row["renderSummaryPath"] = str(result.summary_path)
        except Exception as exc:
            row["status"] = "failed"
            row["errors"].append(
                {
                    "code": getattr(exc, "code", exc.__class__.__name__),
                    "message": getattr(exc, "message", str(exc)),
                }
            )
        rows.append(row)

    summary = {
        "ok": True,
        "artifact": "transition-preview-pack",
        "mixPlanPath": str(mix_plan_path),
        "outDir": str(out_dir),
        "total": len(rows),
        "planned": sum(1 for row in rows if row["status"] in {"planned", "rendered"}),
        "rendered": sum(1 for row in rows if row["status"] == "rendered"),
        "failed": sum(1 for row in rows if row["status"] == "failed"),
        "previews": rows,
    }
    _write_json(out_dir / "index.json", summary)
    return summary


def _find_transition(plan: dict[str, Any], transition_id: str) -> dict[str, Any]:
    for transition in plan.get("transitions", []):
        if isinstance(transition, dict) and transition.get("transitionId") == transition_id:
            return transition
    raise TransitionPreviewError("transition_not_found", f"Transition not found: {transition_id}")


def _transition_audition_end(transition: dict[str, Any]) -> float:
    candidates = [
        transition.get("timelineEndSeconds"),
        transition.get("handoffTimelineSeconds"),
        transition.get("alignedDropTimelineSeconds"),
        transition.get("timelineStartSeconds"),
    ]
    return max(float(value) for value in candidates if isinstance(value, int | float))


def _clip_placement(
    placement: dict[str, Any],
    preview_start: float,
    preview_end: float,
) -> dict[str, Any] | None:
    timeline_start = _number(placement, "timelineStartSeconds", 0.0)
    timeline_end = placement.get("timelineEndSeconds")
    placement_end = float(timeline_end) if isinstance(timeline_end, int | float) else math.inf
    if placement_end <= preview_start or timeline_start >= preview_end:
        return None

    clip_start = max(timeline_start, preview_start)
    clip_end = min(placement_end, preview_end)
    if not math.isfinite(clip_end) or clip_end <= clip_start:
        return None

    ratio = _tempo_ratio(placement)
    source_start = _number(placement, "sourceStartSeconds", 0.0)
    new_source_start = source_start + max(0.0, clip_start - timeline_start) * ratio
    new_source_end = source_start + max(0.0, clip_end - timeline_start) * ratio
    original_source_end = placement.get("sourceEndSeconds")
    if isinstance(original_source_end, int | float):
        new_source_end = min(new_source_end, float(original_source_end))

    clipped = deepcopy(placement)
    clipped["timelineStartSeconds"] = _round(clip_start - preview_start)
    clipped["timelineEndSeconds"] = _round(clip_end - preview_start)
    clipped["sourceStartSeconds"] = _round(new_source_start)
    clipped["sourceEndSeconds"] = _round(new_source_end)
    return clipped


def _synthetic_transport_commands(placements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for placement in placements:
        at = _round(float(placement.get("timelineStartSeconds", 0.0)))
        deck = int(placement.get("deck", 0))
        track_id = str(placement.get("trackId", ""))
        source_start = _round(float(placement.get("sourceStartSeconds", 0.0)))
        commands.append({"type": "load", "at": at, "deck": deck, "trackId": track_id, "cueSeconds": source_start})
        commands.append({"type": "play", "at": at, "deck": deck})
        if isinstance(placement.get("timelineEndSeconds"), int | float):
            commands.append({"type": "stop", "at": _round(float(placement["timelineEndSeconds"])), "deck": deck})
    return commands


def _preview_automation_commands(commands: Any, preview_start: float, preview_end: float) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for command in commands if isinstance(commands, list) else []:
        if not isinstance(command, dict) or command.get("type") != "automate":
            continue
        keyframes = [keyframe for keyframe in command.get("keyframes", []) if isinstance(keyframe, dict)]
        if not keyframes:
            continue
        keyframes.sort(key=lambda item: float(item.get("at", 0.0)))
        shifted_keyframes = []
        has_prior = any(float(keyframe.get("at", 0.0)) < preview_start for keyframe in keyframes)
        if has_prior:
            state = _control_value(keyframes, preview_start)
            shifted_keyframes.append({"at": 0.0, "value": _round(state), "interpolation": "hold"})
        for keyframe in keyframes:
            at = float(keyframe.get("at", 0.0))
            if preview_start <= at <= preview_end:
                shifted = deepcopy(keyframe)
                shifted["at"] = _round(at - preview_start)
                shifted_keyframes.append(shifted)
        if not shifted_keyframes:
            continue
        preview_command = deepcopy(command)
        preview_command["at"] = _round(min(float(item.get("at", 0.0)) for item in shifted_keyframes))
        preview_command["keyframes"] = shifted_keyframes
        result.append(preview_command)
    return result


def _control_value(keyframes: list[dict[str, Any]], time_seconds: float) -> float:
    if time_seconds < float(keyframes[0].get("at", 0.0)):
        return float(keyframes[0].get("value", 0.0))
    if len(keyframes) == 1:
        return float(keyframes[0].get("value", 0.0))

    previous = keyframes[0]
    for keyframe in keyframes[1:]:
        keyframe_at = float(keyframe.get("at", 0.0))
        if time_seconds <= keyframe_at:
            previous_at = float(previous.get("at", 0.0))
            previous_value = float(previous.get("value", 0.0))
            next_value = float(keyframe.get("value", previous_value))
            if keyframe_at <= previous_at:
                return next_value
            progress = (time_seconds - previous_at) / (keyframe_at - previous_at)
            interpolation = str(keyframe.get("interpolation", "linear"))
            if interpolation == "hold":
                return previous_value
            if interpolation == "smoothstep":
                progress = progress * progress * (3.0 - 2.0 * progress)
            elif interpolation == "exponential":
                progress = progress * progress
            return previous_value * (1.0 - progress) + next_value * progress
        previous = keyframe
    return float(keyframes[-1].get("value", 0.0))


def _shift_timed_object(value: dict[str, Any], preview_start: float) -> dict[str, Any]:
    shifted = deepcopy(value)
    for field in ("at", "timelineStartSeconds", "timelineEndSeconds", "handoffTimelineSeconds", "alignedDropTimelineSeconds"):
        if isinstance(shifted.get(field), int | float):
            shifted[field] = _round(float(shifted[field]) - preview_start)
    return shifted


def _tempo_ratio(placement: dict[str, Any]) -> float:
    plan = placement.get("tempoPlan") or {}
    if not isinstance(plan, dict):
        return 1.0
    source_bpm = plan.get("sourceBpm")
    target_bpm = plan.get("targetBpm")
    bias = float(plan.get("targetBpmBias", 0.0) or 0.0)
    if isinstance(source_bpm, int | float) and isinstance(target_bpm, int | float):
        effective_target = float(target_bpm) + bias
        if source_bpm > 0.0 and effective_target > 0.0:
            return effective_target / float(source_bpm)
    ratio = plan.get("tempoRatio")
    if isinstance(ratio, int | float) and ratio > 0.0:
        return float(ratio)
    return 1.0


def _number(value: dict[str, Any], field: str, default: float) -> float:
    field_value = value.get(field, default)
    if not isinstance(field_value, int | float):
        return default
    return float(field_value)


def _command_priority(command: dict[str, Any]) -> int:
    return {"stop": 0, "load": 1, "seek": 2, "automate": 3, "setLoop": 3, "play": 4}.get(
        str(command.get("type")),
        5,
    )


def _round(value: float) -> float:
    return round(float(value), 12)


def _safe_slug(value: str, limit: int = 80) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return (slug.strip("-") or "transition")[:limit].strip("-")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
