"""Transient-nudge helpers for beat-aligned MixPlan transitions."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

from .mixplan_renderer import LoadedAudio, _load_audio, _resolve_source_path


class MixPlanNudgeError(ValueError):
    """Expected MixPlan transient-nudge failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class NudgeOptions:
    sample_rate: int = 44_100
    asset_root: Path | None = None
    window_seconds: float = 0.08
    max_nudge_seconds: float = 0.05
    min_peak_prominence: float = 0.08


@dataclass(frozen=True)
class AnchorNudge:
    anchor_pair: str
    outgoing_peak_offset_seconds: float
    incoming_peak_offset_seconds: float
    nudge_seconds: float
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return {
            "anchorPair": self.anchor_pair,
            "outgoingPeakOffsetSeconds": self.outgoing_peak_offset_seconds,
            "incomingPeakOffsetSeconds": self.incoming_peak_offset_seconds,
            "nudgeSeconds": self.nudge_seconds,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class NudgeResult:
    output_mix_plan: Path
    transition_id: str
    incoming_track_id: str
    incoming_placement_id: str
    nudge_seconds: float
    confidence: float
    anchor_nudges: tuple[AnchorNudge, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "artifact": "mixplan-transient-nudge",
            "outputMixPlan": str(self.output_mix_plan),
            "transitionId": self.transition_id,
            "incomingTrackId": self.incoming_track_id,
            "incomingPlacementId": self.incoming_placement_id,
            "nudgeSeconds": self.nudge_seconds,
            "nudgeMilliseconds": self.nudge_seconds * 1000.0,
            "confidence": self.confidence,
            "anchorNudges": [anchor.to_dict() for anchor in self.anchor_nudges],
        }


def nudge_mix_plan_file(
    mix_plan_path: str | Path,
    output_mix_plan_path: str | Path,
    options: NudgeOptions | None = None,
) -> NudgeResult:
    """Write a copy of a MixPlan with a small incoming source-start nudge."""

    mix_plan_path = Path(mix_plan_path)
    output_mix_plan_path = Path(output_mix_plan_path)
    options = options or NudgeOptions()
    if options.sample_rate <= 0:
        raise MixPlanNudgeError("invalid_sample_rate", "Nudge sample rate must be greater than zero")
    if options.window_seconds <= 0.0 or options.max_nudge_seconds <= 0.0:
        raise MixPlanNudgeError("invalid_nudge_options", "Nudge windows and limits must be positive")
    if not mix_plan_path.exists():
        raise MixPlanNudgeError("mix_plan_missing", f"MixPlan file does not exist: {mix_plan_path}")

    try:
        plan = json.loads(mix_plan_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise MixPlanNudgeError("invalid_mix_plan_json", f"Could not parse MixPlan JSON: {exc}") from exc

    result = nudge_mix_plan(
        plan,
        mix_plan_path=mix_plan_path,
        output_mix_plan_path=output_mix_plan_path,
        options=options,
    )
    return result


def nudge_mix_plan(
    plan: dict[str, Any],
    *,
    mix_plan_path: Path,
    output_mix_plan_path: Path,
    options: NudgeOptions,
) -> NudgeResult:
    transitions = _list_field(plan, "transitions")
    transition = _drop_switch_transition(transitions)
    placements = _placement_map(_list_field(plan, "tracks"))
    assets = _asset_map(plan)

    from_placement = placements.get(_required_string(transition, "fromPlacementId"))
    to_placement = placements.get(_required_string(transition, "toPlacementId"))
    if from_placement is None or to_placement is None:
        raise MixPlanNudgeError("missing_transition_placement", "Transition placements were not found")

    outgoing_track_id = _required_string(from_placement, "trackId")
    incoming_track_id = _required_string(to_placement, "trackId")
    outgoing_audio = _load_plan_audio(outgoing_track_id, assets, mix_plan_path=mix_plan_path, options=options)
    incoming_audio = _load_plan_audio(incoming_track_id, assets, mix_plan_path=mix_plan_path, options=options)

    anchor_nudges = tuple(
        anchor_nudge
        for anchor_nudge in (
            _anchor_pair_nudge(
                transition,
                "fromBuildStart",
                "toBuildStart",
                outgoing_audio=outgoing_audio,
                incoming_audio=incoming_audio,
                options=options,
            ),
            _anchor_pair_nudge(
                transition,
                "fromDropStart",
                "toDropStart",
                outgoing_audio=outgoing_audio,
                incoming_audio=incoming_audio,
                options=options,
            ),
        )
        if anchor_nudge is not None
    )
    if not anchor_nudges:
        raise MixPlanNudgeError("missing_nudge_anchors", "No usable build/drop anchor pairs were found")

    nudge_seconds = _combined_nudge(anchor_nudges, max_nudge_seconds=options.max_nudge_seconds)
    if not math.isfinite(nudge_seconds):
        raise MixPlanNudgeError("invalid_nudge", "Calculated nudge was not finite")

    adjusted_nudge_seconds = _apply_incoming_nudge(
        plan,
        to_placement,
        incoming_track_id=incoming_track_id,
        nudge_seconds=nudge_seconds,
    )
    confidence = sum(anchor.confidence for anchor in anchor_nudges) / len(anchor_nudges)

    _append_nudge_annotation(
        plan,
        transition,
        to_placement,
        nudge_seconds=adjusted_nudge_seconds,
        confidence=confidence,
        anchor_nudges=anchor_nudges,
    )

    output_mix_plan_path.parent.mkdir(parents=True, exist_ok=True)
    output_mix_plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    return NudgeResult(
        output_mix_plan=output_mix_plan_path,
        transition_id=_required_string(transition, "transitionId"),
        incoming_track_id=incoming_track_id,
        incoming_placement_id=_required_string(to_placement, "placementId"),
        nudge_seconds=adjusted_nudge_seconds,
        confidence=confidence,
        anchor_nudges=anchor_nudges,
    )


def _drop_switch_transition(transitions: list[Any]) -> dict[str, Any]:
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        if transition.get("technique") == "build_to_drop_swap":
            return transition
    raise MixPlanNudgeError("missing_drop_switch_transition", "MixPlan has no build_to_drop_swap transition")


def _anchor_pair_nudge(
    transition: dict[str, Any],
    outgoing_anchor_name: str,
    incoming_anchor_name: str,
    *,
    outgoing_audio: LoadedAudio,
    incoming_audio: LoadedAudio,
    options: NudgeOptions,
) -> AnchorNudge | None:
    anchors = transition.get("sourceAnchors", {})
    if not isinstance(anchors, dict):
        return None
    outgoing_anchor = anchors.get(outgoing_anchor_name)
    incoming_anchor = anchors.get(incoming_anchor_name)
    if not isinstance(outgoing_anchor, dict) or not isinstance(incoming_anchor, dict):
        return None
    outgoing_source_seconds = _optional_number(outgoing_anchor, "sourceSeconds")
    incoming_source_seconds = _optional_number(incoming_anchor, "sourceSeconds")
    if outgoing_source_seconds is None or incoming_source_seconds is None:
        return None

    outgoing_peak = _nearest_transient(outgoing_audio, outgoing_source_seconds, options=options)
    incoming_peak = _nearest_transient(incoming_audio, incoming_source_seconds, options=options)
    if outgoing_peak is None or incoming_peak is None:
        return None
    outgoing_peak_offset, outgoing_confidence = outgoing_peak
    incoming_peak_offset, incoming_confidence = incoming_peak
    confidence = min(outgoing_confidence, incoming_confidence)
    if confidence < options.min_peak_prominence:
        return None

    return AnchorNudge(
        anchor_pair=f"{outgoing_anchor_name}->{incoming_anchor_name}",
        outgoing_peak_offset_seconds=outgoing_peak_offset,
        incoming_peak_offset_seconds=incoming_peak_offset,
        nudge_seconds=incoming_peak_offset - outgoing_peak_offset,
        confidence=confidence,
    )


def _nearest_transient(audio: LoadedAudio, source_seconds: float, *, options: NudgeOptions) -> tuple[float, float] | None:
    center = round(source_seconds * audio.sample_rate)
    half_window = max(1, round(options.window_seconds * audio.sample_rate))
    start = max(1, center - half_window)
    end = min(len(audio.samples), center + half_window + 1)
    if end <= start + 2:
        return None

    envelope = []
    previous = float(audio.samples[start - 1])
    for sample in audio.samples[start:end]:
        current = float(sample)
        envelope.append(abs(current - previous))
        previous = current
    envelope = _moving_average(envelope, max(1, round(0.002 * audio.sample_rate)))
    if not envelope:
        return None

    peak_index = max(range(len(envelope)), key=lambda index: envelope[index])
    peak_value = envelope[peak_index]
    average_value = sum(envelope) / len(envelope)
    confidence = (peak_value - average_value) / max(peak_value, 1.0e-9)
    peak_sample = start + peak_index
    return (peak_sample / audio.sample_rate - source_seconds, max(0.0, min(1.0, confidence)))


def _moving_average(values: list[float], radius: int) -> list[float]:
    if radius <= 1 or len(values) <= 2:
        return values
    result: list[float] = []
    running = 0.0
    window: list[float] = []
    for value in values:
        window.append(value)
        running += value
        if len(window) > radius:
            running -= window.pop(0)
        result.append(running / len(window))
    return result


def _combined_nudge(anchor_nudges: tuple[AnchorNudge, ...], *, max_nudge_seconds: float) -> float:
    total_weight = sum(anchor.confidence for anchor in anchor_nudges)
    if total_weight <= 0.0:
        nudge_seconds = sum(anchor.nudge_seconds for anchor in anchor_nudges) / len(anchor_nudges)
    else:
        nudge_seconds = sum(anchor.nudge_seconds * anchor.confidence for anchor in anchor_nudges) / total_weight
    return max(-max_nudge_seconds, min(max_nudge_seconds, nudge_seconds))


def _apply_incoming_nudge(
    plan: dict[str, Any],
    placement: dict[str, Any],
    *,
    incoming_track_id: str,
    nudge_seconds: float,
) -> float:
    old_source_start = _number(placement, "sourceStartSeconds")
    new_source_start = max(0.0, old_source_start + nudge_seconds)
    adjusted_nudge = new_source_start - old_source_start
    placement["sourceStartSeconds"] = new_source_start

    for command in _list_field(plan, "commands"):
        if not isinstance(command, dict) or command.get("type") != "load":
            continue
        if command.get("trackId") != incoming_track_id:
            continue
        cue_seconds = _optional_number(command, "cueSeconds")
        if cue_seconds is not None:
            command["cueSeconds"] = max(0.0, cue_seconds + adjusted_nudge)
    return adjusted_nudge


def _append_nudge_annotation(
    plan: dict[str, Any],
    transition: dict[str, Any],
    placement: dict[str, Any],
    *,
    nudge_seconds: float,
    confidence: float,
    anchor_nudges: tuple[AnchorNudge, ...],
) -> None:
    annotations = plan.setdefault("annotations", [])
    if not isinstance(annotations, list):
        return
    details = ", ".join(
        f"{anchor.anchor_pair}={anchor.nudge_seconds * 1000.0:.1f}ms"
        for anchor in anchor_nudges
    )
    annotations.append(
        {
            "at": _number(transition, "timelineStartSeconds", 0.0),
            "placementId": placement.get("placementId"),
            "transitionId": transition.get("transitionId"),
            "message": (
                f"Incoming source transient nudge applied: {nudge_seconds * 1000.0:.1f}ms "
                f"(confidence {confidence:.3f}; {details})"
            ),
        }
    )


def _load_plan_audio(
    track_id: str,
    assets: dict[str, dict[str, Any]],
    *,
    mix_plan_path: Path,
    options: NudgeOptions,
) -> LoadedAudio:
    asset = assets.get(track_id)
    if asset is None:
        raise MixPlanNudgeError("missing_asset", f"MixPlan has no asset entry for trackId: {track_id}")
    source_uri = _required_string(asset, "sourceUri")
    source_path = _resolve_source_path(source_uri, mix_plan_path=mix_plan_path, asset_root=options.asset_root)
    try:
        return _load_audio(source_path, sample_rate=options.sample_rate)
    except ValueError as exc:
        raise MixPlanNudgeError("audio_load_failed", str(exc)) from exc


def _asset_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for asset in _list_field(plan, "assets"):
        if not isinstance(asset, dict):
            raise MixPlanNudgeError("invalid_asset", "MixPlan assets must be objects")
        result[_required_string(asset, "trackId")] = asset
    return result


def _placement_map(placements: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for placement in placements:
        if not isinstance(placement, dict):
            raise MixPlanNudgeError("invalid_placement", "MixPlan placements must be objects")
        result[_required_string(placement, "placementId")] = placement
    return result


def _list_field(plan: dict[str, Any], field: str) -> list[Any]:
    value = plan.get(field, [])
    if not isinstance(value, list):
        raise MixPlanNudgeError(f"invalid_{field}", f"MixPlan {field} must be an array")
    return value


def _required_string(value: dict[str, Any], field: str) -> str:
    field_value = value.get(field)
    if not isinstance(field_value, str) or not field_value:
        raise MixPlanNudgeError(f"missing_{field}", f"Expected non-empty string field: {field}")
    return field_value


def _number(value: dict[str, Any], field: str, default: float | None = None) -> float:
    field_value = value.get(field, default)
    if not isinstance(field_value, int | float):
        raise MixPlanNudgeError(f"missing_{field}", f"Expected numeric field: {field}")
    return float(field_value)


def _optional_number(value: dict[str, Any], field: str) -> float | None:
    field_value = value.get(field)
    if field_value is None:
        return None
    if not isinstance(field_value, int | float):
        raise MixPlanNudgeError(f"invalid_{field}", f"Expected numeric field: {field}")
    return float(field_value)
