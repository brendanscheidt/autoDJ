"""Transient-nudge helpers for beat-aligned MixPlan transitions."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

from .canonical_audio import (
    CANONICAL_AUDIO_FILENAME,
    CANONICAL_AUDIO_METADATA_FILENAME,
    CANONICAL_TIMELINE_POLICY,
)
from .mixplan_renderer import LoadedAudio, _load_audio, _resolve_source_path
from .tempo_mapping import source_nudge_for_rendered_alignment


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
    preferred_window_seconds: float = 0.04
    debug_candidate_count: int = 8
    micro_alignment_seconds: float = 0.0
    micro_alignment_window_seconds: float = 0.03
    min_micro_alignment_improvement: float = 0.03
    refined_anchor_reports: tuple[Path, ...] = ()
    use_refined_anchors: bool = False
    refined_anchor_match_seconds: float = 0.50


@dataclass(frozen=True)
class TransientCandidate:
    offset_seconds: float
    strength: float
    normalized_strength: float
    confidence: float
    score: float
    selected: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "offsetSeconds": self.offset_seconds,
            "offsetMilliseconds": self.offset_seconds * 1000.0,
            "strength": self.strength,
            "normalizedStrength": self.normalized_strength,
            "confidence": self.confidence,
            "score": self.score,
            "selected": self.selected,
        }


@dataclass(frozen=True)
class TransientPick:
    offset_seconds: float
    confidence: float
    prominence_confidence: float
    candidates: tuple[TransientCandidate, ...]
    risk_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class RefinedAnchorMatch:
    track_id: str
    label: str
    source_seconds: float
    selected_wall_time_seconds: float
    distance_seconds: float
    report_path: Path
    risk_profile: dict[str, Any]

    @property
    def confidence(self) -> float:
        raw_score = self.risk_profile.get("score", 0.0)
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.0
        return max(0.0, min(1.0, score))

    @property
    def risk_flags(self) -> tuple[str, ...]:
        raw_flags = self.risk_profile.get("riskFlags", [])
        if not isinstance(raw_flags, list):
            return ()
        return tuple(str(flag) for flag in raw_flags)

    def to_dict(self) -> dict[str, object]:
        return {
            "trackId": self.track_id,
            "label": self.label,
            "sourceSeconds": self.source_seconds,
            "selectedWallTimeSeconds": self.selected_wall_time_seconds,
            "selectedWallOffsetMilliseconds": (self.selected_wall_time_seconds - self.source_seconds) * 1000.0,
            "matchDistanceMilliseconds": self.distance_seconds * 1000.0,
            "reportPath": str(self.report_path),
            "riskProfile": self.risk_profile,
        }


@dataclass(frozen=True)
class MicroAlignment:
    adjustment_source_seconds: float
    adjustment_timeline_seconds: float
    best_lag_seconds: float
    best_score: float
    zero_lag_score: float
    improvement: float
    applied: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "adjustmentSourceSeconds": self.adjustment_source_seconds,
            "adjustmentSourceMilliseconds": self.adjustment_source_seconds * 1000.0,
            "adjustmentTimelineSeconds": self.adjustment_timeline_seconds,
            "adjustmentTimelineMilliseconds": self.adjustment_timeline_seconds * 1000.0,
            "bestLagSeconds": self.best_lag_seconds,
            "bestLagMilliseconds": self.best_lag_seconds * 1000.0,
            "bestScore": self.best_score,
            "zeroLagScore": self.zero_lag_score,
            "improvement": self.improvement,
            "applied": self.applied,
        }


@dataclass(frozen=True)
class AnchorNudge:
    anchor_pair: str
    anchor_mode: str
    outgoing_peak_offset_seconds: float
    incoming_peak_offset_seconds: float
    nudge_seconds: float
    confidence: float
    prominence_confidence: float
    outgoing_candidates: tuple[TransientCandidate, ...] = ()
    incoming_candidates: tuple[TransientCandidate, ...] = ()
    risk_flags: tuple[str, ...] = ()
    base_nudge_seconds: float | None = None
    micro_alignment: MicroAlignment | None = None
    outgoing_refined_anchor: RefinedAnchorMatch | None = None
    incoming_refined_anchor: RefinedAnchorMatch | None = None

    def to_dict(self) -> dict[str, object]:
        payload = {
            "anchorPair": self.anchor_pair,
            "anchorMode": self.anchor_mode,
            "outgoingPeakOffsetSeconds": self.outgoing_peak_offset_seconds,
            "incomingPeakOffsetSeconds": self.incoming_peak_offset_seconds,
            "nudgeSeconds": self.nudge_seconds,
            "confidence": self.confidence,
            "prominenceConfidence": self.prominence_confidence,
            "riskFlags": list(self.risk_flags),
            "outgoingCandidates": [candidate.to_dict() for candidate in self.outgoing_candidates],
            "incomingCandidates": [candidate.to_dict() for candidate in self.incoming_candidates],
        }
        if self.base_nudge_seconds is not None:
            payload["baseNudgeSeconds"] = self.base_nudge_seconds
            payload["baseNudgeMilliseconds"] = self.base_nudge_seconds * 1000.0
        if self.micro_alignment is not None:
            payload["microAlignment"] = self.micro_alignment.to_dict()
        if self.outgoing_refined_anchor is not None:
            payload["outgoingRefinedAnchor"] = self.outgoing_refined_anchor.to_dict()
        if self.incoming_refined_anchor is not None:
            payload["incomingRefinedAnchor"] = self.incoming_refined_anchor.to_dict()
        return payload


@dataclass(frozen=True)
class NudgeResult:
    output_mix_plan: Path
    transition_id: str
    incoming_track_id: str
    incoming_placement_id: str
    nudge_seconds: float
    confidence: float
    prominence_confidence: float
    anchor_nudges: tuple[AnchorNudge, ...]
    selected_anchor_mode: str = "raw"
    risk_flags: tuple[str, ...] = ()
    raw_anchor_nudges: tuple[AnchorNudge, ...] = ()
    refined_anchor_nudges: tuple[AnchorNudge, ...] = ()
    refined_anchor_reason: str = ""
    audio_sources: tuple[dict[str, object], ...] = ()

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
            "prominenceConfidence": self.prominence_confidence,
            "selectedAnchorMode": self.selected_anchor_mode,
            "riskFlags": list(self.risk_flags),
            "audioSources": [dict(source) for source in self.audio_sources],
            "anchorNudges": [anchor.to_dict() for anchor in self.anchor_nudges],
            "refinedAnchorComparison": {
                "selectedAnchorMode": self.selected_anchor_mode,
                "reason": self.refined_anchor_reason,
                "rawAnchorNudges": [anchor.to_dict() for anchor in self.raw_anchor_nudges],
                "refinedAnchorNudges": [anchor.to_dict() for anchor in self.refined_anchor_nudges],
            },
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
    if options.preferred_window_seconds <= 0.0 or options.debug_candidate_count <= 0:
        raise MixPlanNudgeError(
            "invalid_nudge_options",
            "Preferred nudge window and debug candidate count must be positive",
        )
    if options.micro_alignment_seconds < 0.0 or options.micro_alignment_window_seconds <= 0.0:
        raise MixPlanNudgeError("invalid_nudge_options", "Micro-alignment limits must be valid")
    if options.refined_anchor_match_seconds <= 0.0:
        raise MixPlanNudgeError("invalid_nudge_options", "Refined anchor match tolerance must be positive")
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
    transition = _transition_to_nudge(transitions)
    placements = _placement_map(_list_field(plan, "tracks"))
    assets = _asset_map(plan)

    from_placement = placements.get(_required_string(transition, "fromPlacementId"))
    to_placement = placements.get(_required_string(transition, "toPlacementId"))
    if from_placement is None or to_placement is None:
        raise MixPlanNudgeError("missing_transition_placement", "Transition placements were not found")

    outgoing_track_id = _required_string(from_placement, "trackId")
    incoming_track_id = _required_string(to_placement, "trackId")
    outgoing_tempo_ratio = _tempo_ratio_from_placement(from_placement)
    incoming_tempo_ratio = _tempo_ratio_from_placement(to_placement)
    outgoing_audio = _load_plan_audio(outgoing_track_id, assets, mix_plan_path=mix_plan_path, options=options)
    incoming_audio = _load_plan_audio(incoming_track_id, assets, mix_plan_path=mix_plan_path, options=options)

    refined_reports = _load_refined_anchor_reports(options.refined_anchor_reports)
    outgoing_anchor_name, incoming_anchor_name = _anchor_pair_names(transition)
    raw_drop_nudge = _anchor_pair_nudge(
        transition,
        outgoing_anchor_name,
        incoming_anchor_name,
        outgoing_audio=outgoing_audio,
        incoming_audio=incoming_audio,
        outgoing_tempo_ratio=outgoing_tempo_ratio,
        incoming_tempo_ratio=incoming_tempo_ratio,
        options=options,
    )
    raw_anchor_nudges = tuple(anchor for anchor in (raw_drop_nudge,) if anchor is not None)
    refined_drop_nudge = _anchor_pair_refined_nudge(
        transition,
        outgoing_anchor_name,
        incoming_anchor_name,
        outgoing_audio=outgoing_audio,
        incoming_audio=incoming_audio,
        outgoing_tempo_ratio=outgoing_tempo_ratio,
        incoming_tempo_ratio=incoming_tempo_ratio,
        refined_reports=refined_reports,
        options=options,
    )
    refined_anchor_nudges = tuple(anchor for anchor in (refined_drop_nudge,) if anchor is not None)
    selected_anchor_mode, anchor_nudges, refined_anchor_reason = _select_anchor_nudges(
        raw_anchor_nudges=raw_anchor_nudges,
        refined_anchor_nudges=refined_anchor_nudges,
        use_refined_anchors=options.use_refined_anchors,
    )
    if not anchor_nudges:
        raise MixPlanNudgeError("missing_nudge_anchors", "No usable drop anchor pair was found")

    nudge_seconds = _combined_nudge(anchor_nudges, max_nudge_seconds=options.max_nudge_seconds)
    if not math.isfinite(nudge_seconds):
        raise MixPlanNudgeError("invalid_nudge", "Calculated nudge was not finite")
    risk_flags = _nudge_risk_flags(
        nudge_seconds,
        anchor_nudges=anchor_nudges,
        max_nudge_seconds=options.max_nudge_seconds,
        preferred_window_seconds=options.preferred_window_seconds,
    )

    adjusted_nudge_seconds = _apply_incoming_nudge(
        plan,
        to_placement,
        incoming_track_id=incoming_track_id,
        nudge_seconds=nudge_seconds,
    )
    confidence = sum(anchor.confidence for anchor in anchor_nudges) / len(anchor_nudges)
    prominence_confidence = min(anchor.prominence_confidence for anchor in anchor_nudges)

    _append_nudge_annotation(
        plan,
        transition,
        to_placement,
        nudge_seconds=adjusted_nudge_seconds,
        confidence=confidence,
        anchor_nudges=anchor_nudges,
        risk_flags=risk_flags,
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
        prominence_confidence=prominence_confidence,
        anchor_nudges=anchor_nudges,
        selected_anchor_mode=selected_anchor_mode,
        risk_flags=risk_flags,
        raw_anchor_nudges=raw_anchor_nudges,
        refined_anchor_nudges=refined_anchor_nudges,
        refined_anchor_reason=refined_anchor_reason,
        audio_sources=(
            _audio_source_report(outgoing_track_id, outgoing_audio),
            _audio_source_report(incoming_track_id, incoming_audio),
        ),
    )


def _transition_to_nudge(transitions: list[Any]) -> dict[str, Any]:
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        technique = transition.get("technique")
        template_id = transition.get("templateId")
        if technique == "build_to_drop_swap":
            return transition
        if technique in {"wash_out", "drop_end_reverb_exit"}:
            return transition
        if template_id in {"drop_end_wash_out_v1", "drop_end_reverb_exit_v1"}:
            return transition
    raise MixPlanNudgeError(
        "missing_nudgeable_transition",
        "MixPlan has no build_to_drop_swap or wash_out transition",
    )


def _anchor_pair_names(transition: dict[str, Any]) -> tuple[str, str]:
    technique = transition.get("technique")
    template_id = transition.get("templateId")
    if technique in {"wash_out", "drop_end_reverb_exit"} or template_id in {"drop_end_wash_out_v1", "drop_end_reverb_exit_v1"}:
        return "fromDropEnd", "toFirstBeat"
    return "fromDropStart", "toDropStart"


def _anchor_pair_nudge(
    transition: dict[str, Any],
    outgoing_anchor_name: str,
    incoming_anchor_name: str,
    *,
    outgoing_audio: LoadedAudio,
    incoming_audio: LoadedAudio,
    outgoing_tempo_ratio: float,
    incoming_tempo_ratio: float,
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
    outgoing_peak_offset = outgoing_peak.offset_seconds
    incoming_peak_offset = incoming_peak.offset_seconds
    prominence_confidence = min(outgoing_peak.prominence_confidence, incoming_peak.prominence_confidence)
    confidence = math.sqrt(max(0.0, outgoing_peak.confidence) * max(0.0, incoming_peak.confidence))
    if prominence_confidence < options.min_peak_prominence:
        return None
    base_nudge_seconds = source_nudge_for_rendered_alignment(
        outgoing_source_offset_seconds=outgoing_peak_offset,
        outgoing_tempo_ratio=outgoing_tempo_ratio,
        incoming_source_offset_seconds=incoming_peak_offset,
        incoming_tempo_ratio=incoming_tempo_ratio,
    )
    micro_alignment = _micro_alignment_adjustment(
        outgoing_audio,
        incoming_audio,
        outgoing_source_seconds + outgoing_peak_offset,
        incoming_source_seconds + incoming_peak_offset,
        outgoing_tempo_ratio=outgoing_tempo_ratio,
        incoming_tempo_ratio=incoming_tempo_ratio,
        options=options,
    )
    nudge_seconds = base_nudge_seconds
    if micro_alignment is not None and micro_alignment.applied:
        nudge_seconds += micro_alignment.adjustment_source_seconds
    risk_flags = tuple(
        sorted(
            set(
                outgoing_peak.risk_flags
                + incoming_peak.risk_flags
                + _anchor_nudge_risk_flags(
                    nudge_seconds,
                    outgoing_peak_offset_seconds=outgoing_peak_offset,
                    incoming_peak_offset_seconds=incoming_peak_offset,
                    preferred_window_seconds=options.preferred_window_seconds,
                )
            )
        )
    )

    return AnchorNudge(
        anchor_pair=f"{outgoing_anchor_name}->{incoming_anchor_name}",
        anchor_mode="raw",
        outgoing_peak_offset_seconds=outgoing_peak_offset,
        incoming_peak_offset_seconds=incoming_peak_offset,
        nudge_seconds=nudge_seconds,
        confidence=confidence,
        prominence_confidence=prominence_confidence,
        outgoing_candidates=outgoing_peak.candidates,
        incoming_candidates=incoming_peak.candidates,
        risk_flags=risk_flags,
        base_nudge_seconds=base_nudge_seconds,
        micro_alignment=micro_alignment,
    )


def _anchor_pair_refined_nudge(
    transition: dict[str, Any],
    outgoing_anchor_name: str,
    incoming_anchor_name: str,
    *,
    outgoing_audio: LoadedAudio,
    incoming_audio: LoadedAudio,
    outgoing_tempo_ratio: float,
    incoming_tempo_ratio: float,
    refined_reports: tuple[tuple[Path, dict[str, Any]], ...],
    options: NudgeOptions,
) -> AnchorNudge | None:
    if not refined_reports:
        return None
    anchors = transition.get("sourceAnchors", {})
    if not isinstance(anchors, dict):
        return None
    outgoing_anchor = anchors.get(outgoing_anchor_name)
    incoming_anchor = anchors.get(incoming_anchor_name)
    if not isinstance(outgoing_anchor, dict) or not isinstance(incoming_anchor, dict):
        return None
    outgoing_source_seconds = _optional_number(outgoing_anchor, "sourceSeconds")
    incoming_source_seconds = _optional_number(incoming_anchor, "sourceSeconds")
    outgoing_track_id = _optional_string(outgoing_anchor, "trackId")
    incoming_track_id = _optional_string(incoming_anchor, "trackId")
    if (
        outgoing_source_seconds is None
        or incoming_source_seconds is None
        or outgoing_track_id is None
        or incoming_track_id is None
    ):
        return None

    outgoing_match = _refined_anchor_match(
        refined_reports,
        track_id=outgoing_track_id,
        source_seconds=outgoing_source_seconds,
        tolerance_seconds=options.refined_anchor_match_seconds,
    )
    incoming_match = _refined_anchor_match(
        refined_reports,
        track_id=incoming_track_id,
        source_seconds=incoming_source_seconds,
        tolerance_seconds=options.refined_anchor_match_seconds,
    )
    if outgoing_match is None or incoming_match is None:
        return None

    outgoing_peak_offset = outgoing_match.selected_wall_time_seconds - outgoing_source_seconds
    incoming_peak_offset = incoming_match.selected_wall_time_seconds - incoming_source_seconds
    confidence = math.sqrt(max(0.0, outgoing_match.confidence) * max(0.0, incoming_match.confidence))
    prominence_confidence = min(outgoing_match.confidence, incoming_match.confidence)
    base_nudge_seconds = source_nudge_for_rendered_alignment(
        outgoing_source_offset_seconds=outgoing_peak_offset,
        outgoing_tempo_ratio=outgoing_tempo_ratio,
        incoming_source_offset_seconds=incoming_peak_offset,
        incoming_tempo_ratio=incoming_tempo_ratio,
    )
    micro_alignment = _micro_alignment_adjustment(
        outgoing_audio,
        incoming_audio,
        outgoing_match.selected_wall_time_seconds,
        incoming_match.selected_wall_time_seconds,
        outgoing_tempo_ratio=outgoing_tempo_ratio,
        incoming_tempo_ratio=incoming_tempo_ratio,
        options=options,
    )
    nudge_seconds = base_nudge_seconds
    if micro_alignment is not None and micro_alignment.applied:
        nudge_seconds += micro_alignment.adjustment_source_seconds

    risk_flags = set(outgoing_match.risk_flags + incoming_match.risk_flags)
    risk_flags.update(
        _anchor_nudge_risk_flags(
            nudge_seconds,
            outgoing_peak_offset_seconds=outgoing_peak_offset,
            incoming_peak_offset_seconds=incoming_peak_offset,
            preferred_window_seconds=options.preferred_window_seconds,
        )
    )
    if not bool(outgoing_match.risk_profile.get("dropSwitchSafe", False)):
        risk_flags.add("outgoing_refined_anchor_not_drop_switch_safe")
    if not bool(incoming_match.risk_profile.get("dropSwitchSafe", False)):
        risk_flags.add("incoming_refined_anchor_not_drop_switch_safe")
    if outgoing_match.distance_seconds > options.preferred_window_seconds:
        risk_flags.add("outgoing_refined_match_far_from_plan_anchor")
    if incoming_match.distance_seconds > options.preferred_window_seconds:
        risk_flags.add("incoming_refined_match_far_from_plan_anchor")

    return AnchorNudge(
        anchor_pair=f"{outgoing_anchor_name}->{incoming_anchor_name}",
        anchor_mode="refined",
        outgoing_peak_offset_seconds=outgoing_peak_offset,
        incoming_peak_offset_seconds=incoming_peak_offset,
        nudge_seconds=nudge_seconds,
        confidence=confidence,
        prominence_confidence=prominence_confidence,
        outgoing_candidates=(
            TransientCandidate(
                offset_seconds=outgoing_peak_offset,
                strength=outgoing_match.confidence,
                normalized_strength=1.0,
                confidence=outgoing_match.confidence,
                score=outgoing_match.confidence,
                selected=True,
            ),
        ),
        incoming_candidates=(
            TransientCandidate(
                offset_seconds=incoming_peak_offset,
                strength=incoming_match.confidence,
                normalized_strength=1.0,
                confidence=incoming_match.confidence,
                score=incoming_match.confidence,
                selected=True,
            ),
        ),
        risk_flags=tuple(sorted(risk_flags)),
        base_nudge_seconds=base_nudge_seconds,
        micro_alignment=micro_alignment,
        outgoing_refined_anchor=outgoing_match,
        incoming_refined_anchor=incoming_match,
    )


def _select_anchor_nudges(
    *,
    raw_anchor_nudges: tuple[AnchorNudge, ...],
    refined_anchor_nudges: tuple[AnchorNudge, ...],
    use_refined_anchors: bool,
) -> tuple[str, tuple[AnchorNudge, ...], str]:
    if use_refined_anchors and refined_anchor_nudges:
        return "refined", refined_anchor_nudges, "using refined anchor reports because --use-refined-anchors was requested"
    if use_refined_anchors and raw_anchor_nudges:
        return "raw", raw_anchor_nudges, "using raw transient anchors because no matching refined anchor report was available"
    if raw_anchor_nudges:
        reason = "using raw transient anchors"
        if refined_anchor_nudges:
            reason += "; refined anchors were computed for comparison only"
        return "raw", raw_anchor_nudges, reason
    if refined_anchor_nudges:
        return "refined", refined_anchor_nudges, "using refined anchor reports because raw transient anchors were unavailable"
    return "none", (), "no usable raw or refined anchors were available"


def _load_refined_anchor_reports(paths: tuple[Path, ...]) -> tuple[tuple[Path, dict[str, Any]], ...]:
    reports: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        report_path = Path(path)
        if not report_path.exists():
            raise MixPlanNudgeError("refined_anchor_report_missing", f"Refined anchor report does not exist: {report_path}")
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise MixPlanNudgeError(
                "invalid_refined_anchor_report_json",
                f"Could not parse refined anchor report JSON: {report_path}: {exc}",
            ) from exc
        if not isinstance(payload, dict):
            raise MixPlanNudgeError("invalid_refined_anchor_report", f"Refined anchor report must be an object: {report_path}")
        reports.append((report_path, payload))
    return tuple(reports)


def _refined_anchor_match(
    reports: tuple[tuple[Path, dict[str, Any]], ...],
    *,
    track_id: str,
    source_seconds: float,
    tolerance_seconds: float,
) -> RefinedAnchorMatch | None:
    matches: list[RefinedAnchorMatch] = []
    for report_path, report in reports:
        if str(report.get("trackId", "")) != track_id:
            continue
        anchors = report.get("anchors") if isinstance(report.get("anchors"), list) else []
        for anchor in anchors:
            if not isinstance(anchor, dict) or not bool(anchor.get("accepted", False)):
                continue
            selected_wall_time = _optional_number(anchor, "selectedWallTimeSeconds")
            if selected_wall_time is None:
                continue
            match_times = [
                value
                for value in (
                    _optional_number(anchor, "anchorTimeSeconds"),
                    _optional_number(anchor, "nearestBeatTimeSeconds"),
                    selected_wall_time,
                )
                if value is not None
            ]
            if not match_times:
                continue
            distance = min(abs(value - source_seconds) for value in match_times)
            if distance > tolerance_seconds:
                continue
            risk_profile = anchor.get("riskProfile") if isinstance(anchor.get("riskProfile"), dict) else {}
            matches.append(
                RefinedAnchorMatch(
                    track_id=track_id,
                    label=str(anchor.get("label", "drop")),
                    source_seconds=source_seconds,
                    selected_wall_time_seconds=selected_wall_time,
                    distance_seconds=distance,
                    report_path=report_path,
                    risk_profile=dict(risk_profile),
                )
            )
    if not matches:
        return None
    return min(matches, key=lambda match: (match.distance_seconds, -match.confidence))


def _nearest_transient(audio: LoadedAudio, source_seconds: float, *, options: NudgeOptions) -> TransientPick | None:
    candidates = _transient_candidates(audio, source_seconds, options=options)
    if not candidates:
        return None
    preferred_window = min(options.window_seconds, options.preferred_window_seconds)
    strongest = max(candidates, key=lambda candidate: candidate.strength)
    if abs(strongest.offset_seconds) <= preferred_window:
        selected = strongest
    else:
        preferred_candidates = [
            candidate
            for candidate in candidates
            if (
                abs(candidate.offset_seconds) <= preferred_window
                and candidate.normalized_strength >= 0.35
                and candidate.confidence >= options.min_peak_prominence
            )
        ]
        selected = max(preferred_candidates, key=lambda candidate: candidate.score) if preferred_candidates else strongest
    debug_candidates = _debug_transient_candidates(candidates, selected, count=options.debug_candidate_count)
    selected_candidates = tuple(
        TransientCandidate(
            offset_seconds=candidate.offset_seconds,
            strength=candidate.strength,
            normalized_strength=candidate.normalized_strength,
            confidence=candidate.confidence,
            score=candidate.score,
            selected=candidate.offset_seconds == selected.offset_seconds,
        )
        for candidate in debug_candidates
    )
    risk_flags: list[str] = []
    if abs(selected.offset_seconds) > options.preferred_window_seconds:
        risk_flags.append("selected_transient_outside_preferred_window")
    if strongest.offset_seconds != selected.offset_seconds:
        risk_flags.append("strongest_transient_was_not_selected")
    return TransientPick(
        offset_seconds=selected.offset_seconds,
        confidence=max(0.0, min(1.0, selected.score)),
        prominence_confidence=selected.confidence,
        candidates=selected_candidates,
        risk_flags=tuple(risk_flags),
    )


def _transient_candidates(
    audio: LoadedAudio,
    source_seconds: float,
    *,
    options: NudgeOptions,
) -> tuple[TransientCandidate, ...]:
    center = round(source_seconds * audio.sample_rate)
    half_window = max(1, round(options.window_seconds * audio.sample_rate))
    start = max(1, center - half_window)
    end = min(len(audio.samples), center + half_window + 1)
    if end <= start + 2:
        return ()

    envelope = []
    previous = float(audio.samples[start - 1])
    for sample in audio.samples[start:end]:
        current = float(sample)
        envelope.append(abs(current - previous))
        previous = current
    envelope = _moving_average(envelope, max(1, round(0.002 * audio.sample_rate)))
    if not envelope:
        return ()

    average_value = sum(envelope) / len(envelope)
    peak_indexes = _grouped_peak_indexes(envelope, min_spacing=max(1, round(0.005 * audio.sample_rate)))
    if not peak_indexes:
        return ()

    strongest_value = max(envelope[index] for index in peak_indexes)
    candidates: list[TransientCandidate] = []
    preferred_window = min(options.window_seconds, options.preferred_window_seconds)
    falloff_window = max(options.window_seconds, preferred_window + 1.0e-9)
    for peak_index in peak_indexes:
        peak_value = envelope[peak_index]
        offset_seconds = (start + peak_index) / audio.sample_rate - source_seconds
        confidence = (peak_value - average_value) / max(peak_value, 1.0e-9)
        normalized_strength = peak_value / max(strongest_value, 1.0e-9)
        distance = abs(offset_seconds)
        closeness = max(0.0, 1.0 - distance / max(preferred_window, 1.0e-9))
        far_penalty = max(0.0, (distance - preferred_window) / max(falloff_window - preferred_window, 1.0e-9))
        score = (0.58 * normalized_strength) + (0.42 * closeness) - (0.42 * far_penalty)
        candidates.append(
            TransientCandidate(
                offset_seconds=offset_seconds,
                strength=peak_value,
                normalized_strength=normalized_strength,
                confidence=max(0.0, min(1.0, confidence)),
                score=score,
            )
        )

    return tuple(candidates)


def _micro_alignment_adjustment(
    outgoing_audio: LoadedAudio,
    incoming_audio: LoadedAudio,
    outgoing_source_center_seconds: float,
    incoming_source_center_seconds: float,
    *,
    outgoing_tempo_ratio: float,
    incoming_tempo_ratio: float,
    options: NudgeOptions,
) -> MicroAlignment | None:
    max_lag_samples = round(options.micro_alignment_seconds * options.sample_rate)
    if max_lag_samples <= 0:
        return None
    outgoing_window = _rendered_onset_window(
        outgoing_audio,
        outgoing_source_center_seconds,
        tempo_ratio=outgoing_tempo_ratio,
        radius_seconds=options.micro_alignment_window_seconds,
        sample_rate=options.sample_rate,
    )
    incoming_window = _rendered_onset_window(
        incoming_audio,
        incoming_source_center_seconds,
        tempo_ratio=incoming_tempo_ratio,
        radius_seconds=options.micro_alignment_window_seconds,
        sample_rate=options.sample_rate,
    )
    if not outgoing_window or len(outgoing_window) != len(incoming_window):
        return None

    scores = {
        lag_samples: _normalized_dot(outgoing_window, incoming_window, lag_samples)
        for lag_samples in range(-max_lag_samples, max_lag_samples + 1)
    }
    zero_score = scores.get(0, 0.0)
    best_lag_samples, best_score = max(scores.items(), key=lambda item: item[1])
    best_lag_seconds = best_lag_samples / options.sample_rate
    improvement = best_score - zero_score
    applied = best_lag_samples != 0 and improvement >= options.min_micro_alignment_improvement
    adjustment_timeline_seconds = best_lag_seconds if applied else 0.0
    adjustment_source_seconds = adjustment_timeline_seconds * incoming_tempo_ratio
    return MicroAlignment(
        adjustment_source_seconds=adjustment_source_seconds,
        adjustment_timeline_seconds=adjustment_timeline_seconds,
        best_lag_seconds=best_lag_seconds,
        best_score=best_score,
        zero_lag_score=zero_score,
        improvement=improvement,
        applied=applied,
    )


def _rendered_onset_window(
    audio: LoadedAudio,
    source_center_seconds: float,
    *,
    tempo_ratio: float,
    radius_seconds: float,
    sample_rate: int,
) -> tuple[float, ...]:
    radius_samples = max(1, round(radius_seconds * sample_rate))
    values: list[float] = []
    previous = _sample_source_at_rendered_offset(
        audio,
        source_center_seconds,
        rendered_offset_seconds=(-radius_samples - 1) / sample_rate,
        tempo_ratio=tempo_ratio,
    )
    for sample_index in range(-radius_samples, radius_samples + 1):
        current = _sample_source_at_rendered_offset(
            audio,
            source_center_seconds,
            rendered_offset_seconds=sample_index / sample_rate,
            tempo_ratio=tempo_ratio,
        )
        values.append(abs(current - previous))
        previous = current
    smoothed = _moving_average(values, max(1, round(0.00075 * sample_rate)))
    return _normalize_vector(smoothed)


def _sample_source_at_rendered_offset(
    audio: LoadedAudio,
    source_center_seconds: float,
    *,
    rendered_offset_seconds: float,
    tempo_ratio: float,
) -> float:
    source_seconds = source_center_seconds + rendered_offset_seconds * tempo_ratio
    index = round(source_seconds * audio.sample_rate)
    if index < 0 or index >= len(audio.samples):
        return 0.0
    return float(audio.samples[index])


def _normalize_vector(values: list[float]) -> tuple[float, ...]:
    if not values:
        return ()
    mean = sum(values) / len(values)
    centered = [value - mean for value in values]
    norm = math.sqrt(sum(value * value for value in centered))
    if norm <= 1.0e-12:
        return tuple(0.0 for _ in values)
    return tuple(value / norm for value in centered)


def _normalized_dot(left: tuple[float, ...], right: tuple[float, ...], lag_samples: int) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    total = 0.0
    count = 0
    for index, left_value in enumerate(left):
        right_index = index + lag_samples
        if right_index < 0 or right_index >= len(right):
            continue
        total += left_value * right[right_index]
        count += 1
    if count == 0:
        return 0.0
    overlap_scale = count / len(left)
    return total * overlap_scale


def _debug_transient_candidates(
    candidates: tuple[TransientCandidate, ...],
    selected: TransientCandidate,
    *,
    count: int,
) -> tuple[TransientCandidate, ...]:
    ranked: list[TransientCandidate] = []
    for candidate in [selected, *sorted(candidates, key=lambda candidate: candidate.strength, reverse=True)]:
        if all(candidate.offset_seconds != existing.offset_seconds for existing in ranked):
            ranked.append(candidate)
        if len(ranked) >= count:
            return tuple(ranked)
    for candidate in sorted(candidates, key=lambda candidate: candidate.score, reverse=True):
        if all(candidate.offset_seconds != existing.offset_seconds for existing in ranked):
            ranked.append(candidate)
        if len(ranked) >= count:
            break
    return tuple(ranked)


def _grouped_peak_indexes(values: list[float], *, min_spacing: int) -> list[int]:
    local_peaks = [
        index
        for index in range(1, len(values) - 1)
        if values[index] >= values[index - 1] and values[index] >= values[index + 1]
    ]
    local_peaks.sort(key=lambda index: values[index], reverse=True)
    grouped: list[int] = []
    for index in local_peaks:
        if any(abs(index - existing) < min_spacing for existing in grouped):
            continue
        grouped.append(index)
    return grouped


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


def _anchor_nudge_risk_flags(
    nudge_seconds: float,
    *,
    outgoing_peak_offset_seconds: float,
    incoming_peak_offset_seconds: float,
    preferred_window_seconds: float,
) -> tuple[str, ...]:
    risk_flags: list[str] = []
    if abs(outgoing_peak_offset_seconds) > preferred_window_seconds:
        risk_flags.append("outgoing_offset_outside_preferred_window")
    if abs(incoming_peak_offset_seconds) > preferred_window_seconds:
        risk_flags.append("incoming_offset_outside_preferred_window")
    if abs(nudge_seconds) > preferred_window_seconds:
        risk_flags.append("large_anchor_nudge")
    return tuple(risk_flags)


def _nudge_risk_flags(
    nudge_seconds: float,
    *,
    anchor_nudges: tuple[AnchorNudge, ...],
    max_nudge_seconds: float,
    preferred_window_seconds: float,
) -> tuple[str, ...]:
    risk_flags = {flag for anchor in anchor_nudges for flag in anchor.risk_flags}
    raw_nudges = [anchor.nudge_seconds for anchor in anchor_nudges]
    if any(abs(raw_nudge) > preferred_window_seconds for raw_nudge in raw_nudges):
        risk_flags.add("large_raw_nudge")
    if any(abs(raw_nudge) > max_nudge_seconds for raw_nudge in raw_nudges):
        risk_flags.add("raw_nudge_clipped")
    if abs(nudge_seconds) >= max_nudge_seconds * 0.98:
        risk_flags.add("final_nudge_near_limit")
    return tuple(sorted(risk_flags))


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
    risk_flags: tuple[str, ...],
) -> None:
    annotations = plan.setdefault("annotations", [])
    if not isinstance(annotations, list):
        return
    details = ", ".join(
        f"{anchor.anchor_pair}/{anchor.anchor_mode}={anchor.nudge_seconds * 1000.0:.1f}ms"
        for anchor in anchor_nudges
    )
    annotations.append(
        {
            "at": _number(transition, "timelineStartSeconds", 0.0),
            "placementId": placement.get("placementId"),
            "transitionId": transition.get("transitionId"),
            "message": (
                f"Incoming source transient nudge applied: {nudge_seconds * 1000.0:.1f}ms "
                f"(confidence {confidence:.3f}; {details}; risk={','.join(risk_flags) or 'none'})"
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


def _audio_source_report(track_id: str, audio: LoadedAudio) -> dict[str, object]:
    return {
        "trackId": track_id,
        "sourcePath": str(audio.source_path),
        "timelinePolicy": _timeline_policy_for_audio_path(audio.source_path),
    }


def _timeline_policy_for_audio_path(path: Path) -> str:
    if path.name == CANONICAL_AUDIO_FILENAME and (path.parent / CANONICAL_AUDIO_METADATA_FILENAME).exists():
        return CANONICAL_TIMELINE_POLICY
    return "direct-audio-path"


def _tempo_ratio_from_placement(placement: dict[str, Any]) -> float:
    tempo_plan = placement.get("tempoPlan")
    if tempo_plan is None:
        return 1.0
    if not isinstance(tempo_plan, dict):
        raise MixPlanNudgeError("invalid_tempo_plan", "tempoPlan must be an object")
    tempo_ratio = _optional_number(tempo_plan, "tempoRatio")
    if tempo_ratio is not None:
        if tempo_ratio <= 0.0:
            raise MixPlanNudgeError("invalid_tempo_ratio", "tempoPlan.tempoRatio must be greater than zero")
        return tempo_ratio
    source_bpm = _optional_number(tempo_plan, "sourceBpm")
    target_bpm = _optional_number(tempo_plan, "targetBpm")
    if source_bpm is None or target_bpm is None:
        return 1.0
    if source_bpm <= 0.0 or target_bpm <= 0.0:
        raise MixPlanNudgeError("invalid_tempo_plan", "tempoPlan sourceBpm and targetBpm must be greater than zero")
    return target_bpm / source_bpm


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


def _optional_string(value: dict[str, Any], field: str) -> str | None:
    field_value = value.get(field)
    if field_value is None:
        return None
    if not isinstance(field_value, str) or not field_value:
        raise MixPlanNudgeError(f"invalid_{field}", f"Expected non-empty string field: {field}")
    return field_value
