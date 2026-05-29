"""Drop-switch energy compatibility and gain-planning helpers."""

from __future__ import annotations

from dataclasses import dataclass
import copy
import json
import math
from pathlib import Path
from typing import Any

from .mixplan_renderer import LoadedAudio, _load_audio, _resolve_source_path, _split_low_high


DEFAULT_SAMPLE_RATE = 44_100
DEFAULT_LOW_CUTOFF_HZ = 180.0
DEFAULT_HIGH_CUTOFF_HZ = 2_000.0
_EPSILON = 1.0e-9


class MixPlanEnergyError(ValueError):
    """Expected MixPlan energy post-pass failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class GainPlanOptions:
    sample_rate: int = DEFAULT_SAMPLE_RATE
    asset_root: Path | None = None
    target_headroom_db: float = 1.5
    max_overlap_gain_reduction_db: float = 4.0
    drop_energy_floor_db: float = -3.0
    window_measures: float = 8.0
    low_cutoff_hz: float = DEFAULT_LOW_CUTOFF_HZ
    high_cutoff_hz: float = DEFAULT_HIGH_CUTOFF_HZ
    target_drop_loudness_tolerance_db: float = 0.5
    max_incoming_boost_db: float = 6.0
    max_incoming_trim_db: float = 0.0
    drop_peak_match_tolerance_db: float = 0.25
    max_drop_peak_match_boost_db: float = 4.0
    drop_peak_window_beats: float = 1.0


@dataclass(frozen=True)
class GainPlanResult:
    output_mix_plan: Path
    report_path: Path
    transition_id: str
    verdict: str
    outgoing_overlap_gain: float
    outgoing_overlap_trim_db: float
    incoming_drop_gain: float
    incoming_drop_gain_db: float
    b_drop_vs_post_gain_layered_db: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "artifact": "mixplan-drop-switch-gain-plan",
            "outputMixPlan": str(self.output_mix_plan),
            "reportPath": str(self.report_path),
            "transitionId": self.transition_id,
            "verdict": self.verdict,
            "outgoingOverlapGain": self.outgoing_overlap_gain,
            "outgoingOverlapTrimDb": self.outgoing_overlap_trim_db,
            "incomingDropGain": self.incoming_drop_gain,
            "incomingDropGainDb": self.incoming_drop_gain_db,
            "bDropVsPostGainLayeredDb": self.b_drop_vs_post_gain_layered_db,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class _PlanContext:
    plan: dict[str, Any]
    transition: dict[str, Any]
    outgoing_placement: dict[str, Any]
    incoming_placement: dict[str, Any]
    outgoing_audio: LoadedAudio
    incoming_audio: LoadedAudio


@dataclass(frozen=True)
class _WindowMetrics:
    id: str
    track_id: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    rms_linear: float
    rms_db: float
    peak_linear: float
    peak_db: float
    low_rms_linear: float
    low_rms_db: float
    mid_rms_linear: float
    mid_rms_db: float
    high_rms_linear: float
    high_rms_db: float
    non_low_rms_linear: float
    non_low_rms_db: float
    crest_factor_db: float
    impact_score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "trackId": self.track_id,
            "startSeconds": _round(self.start_seconds),
            "endSeconds": _round(self.end_seconds),
            "durationSeconds": _round(self.duration_seconds),
            "rmsDb": _round(self.rms_db),
            "peakDb": _round(self.peak_db),
            "lowRmsDb": _round(self.low_rms_db),
            "midRmsDb": _round(self.mid_rms_db),
            "highRmsDb": _round(self.high_rms_db),
            "nonLowRmsDb": _round(self.non_low_rms_db),
            "crestFactorDb": _round(self.crest_factor_db),
            "impactScore": _round(self.impact_score),
        }


def gain_plan_drop_switch_file(
    mix_plan_path: str | Path,
    output_mix_plan_path: str | Path,
    report_path: str | Path,
    options: GainPlanOptions | None = None,
) -> GainPlanResult:
    """Write a gain-planned copy of a drop-switch MixPlan and an energy report."""

    mix_plan_path = Path(mix_plan_path)
    output_mix_plan_path = Path(output_mix_plan_path)
    report_path = Path(report_path)
    options = options or GainPlanOptions()
    _validate_options(options)
    if not mix_plan_path.exists():
        raise MixPlanEnergyError("mix_plan_missing", f"MixPlan file does not exist: {mix_plan_path}")

    try:
        plan = json.loads(mix_plan_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise MixPlanEnergyError("invalid_mix_plan_json", f"Could not parse MixPlan JSON: {exc}") from exc

    return gain_plan_drop_switch(
        plan,
        mix_plan_path=mix_plan_path,
        output_mix_plan_path=output_mix_plan_path,
        report_path=report_path,
        options=options,
    )


def gain_plan_drop_switch(
    plan: dict[str, Any],
    *,
    mix_plan_path: Path,
    output_mix_plan_path: Path,
    report_path: Path,
    options: GainPlanOptions,
) -> GainPlanResult:
    """Apply the energy/gain post-pass to an already parsed MixPlan object."""

    _validate_options(options)
    working_plan = copy.deepcopy(plan)
    context = _context(working_plan, mix_plan_path=mix_plan_path, options=options)
    windows = _window_metrics(context, options=options)
    incoming_gain, incoming_gain_db, incoming_gain_reasons = _recommended_incoming_drop_gain(
        windows,
        options=options,
    )
    comparisons = _energy_comparisons(windows, options=options)
    outgoing_gain, outgoing_trim_db, gain_reasons = _recommended_outgoing_gain(
        windows,
        incoming_gain=incoming_gain,
        options=options,
    )
    post_gain_layered_rms_db = _layered_build_rms_db(
        windows["aBuildFinal"],
        windows["bBuildFinal"],
        outgoing_gain=outgoing_gain,
        incoming_gain=incoming_gain,
    )
    comparisons["postGainLayeredBuildRmsDb"] = post_gain_layered_rms_db
    comparisons["incomingDropGainDb"] = incoming_gain_db
    comparisons["aDropVsRawBDropDb"] = windows["aDropFirst"].rms_db - windows["bDropFirst"].rms_db
    comparisons["aReferenceDropVsRawBDropDb"] = windows["aReferenceDrop"].rms_db - windows["bDropFirst"].rms_db
    comparisons["targetIncomingDropRmsDb"] = _target_incoming_drop_db(windows, options=options)
    comparisons["postGainBDropRmsDb"] = _linear_to_db(windows["bDropFirst"].rms_linear * incoming_gain)
    comparisons["bDropVsPostGainLayeredDb"] = comparisons["postGainBDropRmsDb"] - post_gain_layered_rms_db
    comparisons["aReferenceDropPeakDb"] = windows["aReferenceDrop"].peak_db
    comparisons["targetReferenceDropPeakDb"] = _target_reference_peak_db(windows)
    comparisons["aDropImpactPeakDb"] = windows["aDropImpact"].peak_db
    comparisons["bDropImpactPeakDb"] = windows["bDropImpact"].peak_db
    comparisons["postGainBDropPeakDb"] = _linear_to_db(windows["bDropFirst"].peak_linear * incoming_gain)
    comparisons["postGainBDropImpactPeakDb"] = _linear_to_db(windows["bDropImpact"].peak_linear * incoming_gain)
    comparisons["bDropImpactPeakVsADropImpactDb"] = (
        comparisons["postGainBDropImpactPeakDb"] - windows["aDropImpact"].peak_db
    )

    verdict, verdict_reasons = _compatibility_verdict(windows, comparisons, options=options)
    reasons = tuple(incoming_gain_reasons + gain_reasons + verdict_reasons)
    outgoing_keyframes = _apply_outgoing_gain(
        working_plan,
        context.transition,
        context.outgoing_placement,
        context.incoming_placement,
        outgoing_gain=outgoing_gain,
    )
    incoming_keyframes = _apply_incoming_gain(
        working_plan,
        context.incoming_placement,
        incoming_gain=incoming_gain,
    )
    _append_gain_annotation(
        working_plan,
        context.transition,
        context.outgoing_placement,
        verdict=verdict,
        trim_db=outgoing_trim_db,
        incoming_gain_db=incoming_gain_db,
        b_drop_delta_db=comparisons["bDropVsPostGainLayeredDb"],
    )

    report = _report_payload(
        input_mix_plan=mix_plan_path,
        output_mix_plan=output_mix_plan_path,
        report_path=report_path,
        context=context,
        windows=windows,
        comparisons=comparisons,
        verdict=verdict,
        reasons=reasons,
        outgoing_gain=outgoing_gain,
        outgoing_trim_db=outgoing_trim_db,
        incoming_gain=incoming_gain,
        incoming_gain_db=incoming_gain_db,
        outgoing_keyframes=outgoing_keyframes,
        incoming_keyframes=incoming_keyframes,
        options=options,
    )

    output_mix_plan_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_mix_plan_path.write_text(json.dumps(working_plan, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    return GainPlanResult(
        output_mix_plan=output_mix_plan_path,
        report_path=report_path,
        transition_id=_required_string(context.transition, "transitionId"),
        verdict=verdict,
        outgoing_overlap_gain=outgoing_gain,
        outgoing_overlap_trim_db=outgoing_trim_db,
        incoming_drop_gain=incoming_gain,
        incoming_drop_gain_db=incoming_gain_db,
        b_drop_vs_post_gain_layered_db=comparisons["bDropVsPostGainLayeredDb"],
        reasons=reasons,
    )


def _validate_options(options: GainPlanOptions) -> None:
    if options.sample_rate <= 0:
        raise MixPlanEnergyError("invalid_sample_rate", "Gain planner sample rate must be greater than zero")
    if options.target_headroom_db < 0.0:
        raise MixPlanEnergyError("invalid_headroom", "Target headroom must be non-negative")
    if options.max_overlap_gain_reduction_db < 0.0:
        raise MixPlanEnergyError("invalid_overlap_reduction", "Maximum overlap gain reduction must be non-negative")
    if options.window_measures <= 0.0:
        raise MixPlanEnergyError("invalid_window_measures", "Energy window measure count must be greater than zero")
    if options.low_cutoff_hz <= 0.0 or options.high_cutoff_hz <= options.low_cutoff_hz:
        raise MixPlanEnergyError("invalid_band_cutoffs", "Band cutoff frequencies are invalid")
    if options.target_drop_loudness_tolerance_db < 0.0:
        raise MixPlanEnergyError("invalid_loudness_tolerance", "Drop loudness tolerance must be non-negative")
    if options.max_incoming_boost_db < 0.0 or options.max_incoming_trim_db < 0.0:
        raise MixPlanEnergyError("invalid_incoming_gain", "Incoming gain limits must be non-negative")
    if options.drop_peak_match_tolerance_db < 0.0 or options.max_drop_peak_match_boost_db < 0.0:
        raise MixPlanEnergyError("invalid_peak_match", "Drop peak matching limits must be non-negative")
    if options.drop_peak_window_beats <= 0.0:
        raise MixPlanEnergyError("invalid_peak_window", "Drop peak matching window must be greater than zero")


def _context(plan: dict[str, Any], *, mix_plan_path: Path, options: GainPlanOptions) -> _PlanContext:
    transition = _drop_switch_transition(_list_field(plan, "transitions"))
    placements = _placement_map(_list_field(plan, "tracks"))
    assets = _asset_map(plan)

    from_placement = placements.get(_required_string(transition, "fromPlacementId"))
    to_placement = placements.get(_required_string(transition, "toPlacementId"))
    if from_placement is None or to_placement is None:
        raise MixPlanEnergyError("missing_transition_placement", "Transition placements were not found")

    outgoing_track_id = _required_string(from_placement, "trackId")
    incoming_track_id = _required_string(to_placement, "trackId")
    return _PlanContext(
        plan=plan,
        transition=transition,
        outgoing_placement=from_placement,
        incoming_placement=to_placement,
        outgoing_audio=_load_plan_audio(outgoing_track_id, assets, mix_plan_path=mix_plan_path, options=options),
        incoming_audio=_load_plan_audio(incoming_track_id, assets, mix_plan_path=mix_plan_path, options=options),
    )


def _window_metrics(context: _PlanContext, *, options: GainPlanOptions) -> dict[str, _WindowMetrics]:
    anchors = context.transition.get("sourceAnchors", {})
    if not isinstance(anchors, dict):
        raise MixPlanEnergyError("missing_source_anchors", "Drop-switch transition has no source anchors")

    from_build = _anchor_seconds(anchors, "fromBuildStart")
    from_drop = _anchor_seconds(anchors, "fromDropStart")
    to_build = _anchor_seconds(anchors, "toBuildStart")
    to_drop = _anchor_seconds(anchors, "toDropStart")
    measure_count = _number(context.transition, "measureCountToTarget", 0.0)
    if measure_count <= 0.0:
        raise MixPlanEnergyError("missing_measure_count", "Drop-switch transition has no usable measureCountToTarget")

    outgoing_measure_seconds = max((from_drop - from_build) / measure_count, _EPSILON)
    incoming_measure_seconds = max((to_drop - to_build) / measure_count, outgoing_measure_seconds)
    outgoing_window_seconds = min(options.window_measures, measure_count) * outgoing_measure_seconds
    incoming_window_seconds = min(options.window_measures, measure_count) * incoming_measure_seconds
    outgoing_peak_window_seconds = options.drop_peak_window_beats * outgoing_measure_seconds / 4.0
    incoming_peak_window_seconds = options.drop_peak_window_beats * incoming_measure_seconds / 4.0
    outgoing_source_start = _number(context.outgoing_placement, "sourceStartSeconds", 0.0)

    outgoing_track_id = _required_string(context.outgoing_placement, "trackId")
    incoming_track_id = _required_string(context.incoming_placement, "trackId")
    return {
        "aBuildFinal": _metrics_for_window(
            "aBuildFinal",
            outgoing_track_id,
            context.outgoing_audio,
            from_drop - outgoing_window_seconds,
            from_drop,
            options=options,
        ),
        "bBuildFinal": _metrics_for_window(
            "bBuildFinal",
            incoming_track_id,
            context.incoming_audio,
            to_drop - incoming_window_seconds,
            to_drop,
            options=options,
        ),
        "bDropFirst": _metrics_for_window(
            "bDropFirst",
            incoming_track_id,
            context.incoming_audio,
            to_drop,
            to_drop + incoming_window_seconds,
            options=options,
        ),
        "aDropFirst": _metrics_for_window(
            "aDropFirst",
            outgoing_track_id,
            context.outgoing_audio,
            from_drop,
            from_drop + outgoing_window_seconds,
            options=options,
        ),
        "aReferenceDrop": _strongest_metrics_for_window(
            "aReferenceDrop",
            outgoing_track_id,
            context.outgoing_audio,
            outgoing_source_start,
            from_build,
            outgoing_window_seconds,
            hop_seconds=outgoing_measure_seconds,
            fallback_start_seconds=from_drop,
            options=options,
        ),
        "aDropImpact": _metrics_for_window(
            "aDropImpact",
            outgoing_track_id,
            context.outgoing_audio,
            from_drop,
            from_drop + outgoing_peak_window_seconds,
            options=options,
        ),
        "bDropImpact": _metrics_for_window(
            "bDropImpact",
            incoming_track_id,
            context.incoming_audio,
            to_drop,
            to_drop + incoming_peak_window_seconds,
            options=options,
        ),
    }


def _strongest_metrics_for_window(
    window_id: str,
    track_id: str,
    audio: LoadedAudio,
    start_seconds: float,
    end_seconds: float,
    window_seconds: float,
    *,
    hop_seconds: float,
    fallback_start_seconds: float,
    options: GainPlanOptions,
) -> _WindowMetrics:
    duration = len(audio.samples) / audio.sample_rate
    start_seconds = max(0.0, min(duration, start_seconds))
    end_seconds = max(start_seconds, min(duration, end_seconds))
    window_seconds = max(_EPSILON, min(window_seconds, duration))
    hop_seconds = max(_EPSILON, hop_seconds)
    if end_seconds - start_seconds < window_seconds * 0.75:
        return _metrics_for_window(
            window_id,
            track_id,
            audio,
            fallback_start_seconds,
            fallback_start_seconds + window_seconds,
            options=options,
        )

    best: _WindowMetrics | None = None
    cursor = start_seconds
    last_start = max(start_seconds, end_seconds - window_seconds)
    while cursor <= last_start + 0.000001:
        metrics = _metrics_for_window(
            window_id,
            track_id,
            audio,
            cursor,
            cursor + window_seconds,
            options=options,
        )
        if best is None or _reference_drop_score(metrics) > _reference_drop_score(best):
            best = metrics
        cursor += hop_seconds
    if best is None:
        return _metrics_for_window(
            window_id,
            track_id,
            audio,
            fallback_start_seconds,
            fallback_start_seconds + window_seconds,
            options=options,
        )
    return best


def _reference_drop_score(metrics: _WindowMetrics) -> float:
    return metrics.rms_linear + 0.35 * metrics.low_rms_linear + 0.15 * metrics.peak_linear


def _metrics_for_window(
    window_id: str,
    track_id: str,
    audio: LoadedAudio,
    start_seconds: float,
    end_seconds: float,
    *,
    options: GainPlanOptions,
) -> _WindowMetrics:
    duration = len(audio.samples) / audio.sample_rate
    start_seconds = max(0.0, min(duration, start_seconds))
    end_seconds = max(start_seconds, min(duration, end_seconds))
    start = max(0, min(len(audio.samples), math.floor(start_seconds * audio.sample_rate)))
    end = max(start, min(len(audio.samples), math.ceil(end_seconds * audio.sample_rate)))
    samples = tuple(audio.samples[start:end])
    if not samples:
        samples = (0.0,)

    low_full, low_remainder = _split_low_high(samples, sample_rate=audio.sample_rate, cutoff_hz=options.low_cutoff_hz)
    low_mid, high = _split_low_high(samples, sample_rate=audio.sample_rate, cutoff_hz=options.high_cutoff_hz)
    mid = [low_mid[index] - low_full[index] for index in range(len(low_mid))]
    full_rms = _rms(samples)
    low_rms = _rms(low_full)
    mid_rms = _rms(mid)
    high_rms = _rms(high)
    non_low_rms = math.sqrt(mid_rms * mid_rms + high_rms * high_rms)
    peak = max(abs(sample) for sample in samples)
    rms_db = _linear_to_db(full_rms)
    peak_db = _linear_to_db(peak)
    return _WindowMetrics(
        id=window_id,
        track_id=track_id,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        duration_seconds=end_seconds - start_seconds,
        rms_linear=full_rms,
        rms_db=rms_db,
        peak_linear=peak,
        peak_db=peak_db,
        low_rms_linear=low_rms,
        low_rms_db=_linear_to_db(low_rms),
        mid_rms_linear=mid_rms,
        mid_rms_db=_linear_to_db(mid_rms),
        high_rms_linear=high_rms,
        high_rms_db=_linear_to_db(high_rms),
        non_low_rms_linear=non_low_rms,
        non_low_rms_db=_linear_to_db(non_low_rms),
        crest_factor_db=peak_db - rms_db,
        impact_score=0.55 * full_rms + 0.30 * low_rms + 0.15 * peak,
    )


def _energy_comparisons(windows: dict[str, _WindowMetrics], *, options: GainPlanOptions) -> dict[str, float]:
    pre_gain_layered_rms_db = _layered_build_rms_db(
        windows["aBuildFinal"],
        windows["bBuildFinal"],
        outgoing_gain=1.0,
    )
    build_low_handoff_db = _linear_to_db(
        max(windows["aBuildFinal"].low_rms_linear, windows["bBuildFinal"].low_rms_linear)
    )
    return {
        "preGainLayeredBuildRmsDb": pre_gain_layered_rms_db,
        "postGainLayeredBuildRmsDb": pre_gain_layered_rms_db,
        "bDropVsPreGainLayeredDb": windows["bDropFirst"].rms_db - pre_gain_layered_rms_db,
        "bDropVsPostGainLayeredDb": windows["bDropFirst"].rms_db - pre_gain_layered_rms_db,
        "buildLowHandoffRmsDb": build_low_handoff_db,
        "bDropLowVsBuildLowDb": windows["bDropFirst"].low_rms_db - build_low_handoff_db,
        "targetHeadroomDb": options.target_headroom_db,
    }


def _recommended_incoming_drop_gain(
    windows: dict[str, _WindowMetrics],
    *,
    options: GainPlanOptions,
) -> tuple[float, float, list[str]]:
    target_drop_db = _target_incoming_drop_db(windows, options=options)
    rms_delta_db = target_drop_db - windows["bDropFirst"].rms_db
    reference_peak_db = _target_reference_peak_db(windows)
    incoming_peak_db = max(windows["bDropImpact"].peak_db, windows["bDropFirst"].peak_db)
    peak_delta_db = reference_peak_db - incoming_peak_db - options.drop_peak_match_tolerance_db
    rms_gain_db = _positive_gain_after_tolerance(
        rms_delta_db,
        tolerance_db=options.target_drop_loudness_tolerance_db,
        max_gain_db=options.max_incoming_boost_db,
    )
    peak_gain_db = _positive_gain_after_tolerance(
        peak_delta_db,
        tolerance_db=0.0,
        max_gain_db=min(options.max_drop_peak_match_boost_db, options.max_incoming_boost_db),
    )
    gain_db = max(rms_gain_db, peak_gain_db)
    reasons: list[str] = []

    if rms_gain_db > 0.05:
        reasons.append("incoming_drop_boost_for_loudness_match")
        if rms_gain_db < rms_delta_db - options.target_drop_loudness_tolerance_db - 0.05:
            reasons.append("incoming_drop_boost_limited")
    if peak_gain_db > 0.05:
        reasons.append("incoming_drop_boost_for_peak_match")
        if peak_gain_db < peak_delta_db - 0.05:
            reasons.append("incoming_drop_peak_boost_limited")
    if gain_db > 0.05:
        return _db_to_linear(gain_db), gain_db, reasons

    if abs(rms_delta_db) <= options.target_drop_loudness_tolerance_db and peak_delta_db <= 0.0:
        return 1.0, 0.0, ["incoming_drop_loudness_and_peak_within_tolerance"]
    if rms_delta_db < -options.target_drop_loudness_tolerance_db and options.max_incoming_trim_db > 0.0:
        gain_db = -min(abs(rms_delta_db) - options.target_drop_loudness_tolerance_db, options.max_incoming_trim_db)
        if gain_db < -0.05:
            reasons.append("incoming_drop_trim_for_loudness_match")
            if abs(gain_db) < abs(rms_delta_db) - options.target_drop_loudness_tolerance_db - 0.05:
                reasons.append("incoming_drop_trim_limited")
    else:
        gain_db = 0.0
        reasons.append("incoming_drop_not_trimmed_drop_energy_is_reference")
    return _db_to_linear(gain_db), gain_db, reasons


def _positive_gain_after_tolerance(delta_db: float, *, tolerance_db: float, max_gain_db: float) -> float:
    if delta_db <= tolerance_db:
        return 0.0
    return min(delta_db - tolerance_db, max_gain_db)


def _target_incoming_drop_db(windows: dict[str, _WindowMetrics], *, options: GainPlanOptions) -> float:
    return max(
        windows["aDropFirst"].rms_db,
        windows["aReferenceDrop"].rms_db,
        windows["bBuildFinal"].rms_db + options.target_headroom_db,
    )


def _target_reference_peak_db(windows: dict[str, _WindowMetrics]) -> float:
    return max(windows["aDropImpact"].peak_db, windows["aDropFirst"].peak_db, windows["aReferenceDrop"].peak_db)


def _recommended_outgoing_gain(
    windows: dict[str, _WindowMetrics],
    *,
    incoming_gain: float,
    options: GainPlanOptions,
) -> tuple[float, float, list[str]]:
    a_non_low = windows["aBuildFinal"].non_low_rms_linear
    b_build = windows["bBuildFinal"].rms_linear * incoming_gain
    b_drop_target = windows["bDropFirst"].rms_linear * incoming_gain / _db_to_linear(options.target_headroom_db)
    reasons: list[str] = []
    if a_non_low <= _EPSILON:
        return 1.0, 0.0, ["outgoing_non_low_build_energy_too_low_for_overlap_trim"]

    available = b_drop_target * b_drop_target - b_build * b_build
    if available <= 0.0:
        trim_db = -options.max_overlap_gain_reduction_db if options.max_overlap_gain_reduction_db > 0.0 else 0.0
        reasons.append("incoming_build_already_exceeds_target_headroom")
    else:
        desired_gain = math.sqrt(available) / a_non_low
        trim_db = min(0.0, _linear_to_db(desired_gain))
        trim_db = max(-options.max_overlap_gain_reduction_db, trim_db)
        if trim_db < -0.05:
            reasons.append("outgoing_overlap_trim_recommended")

    gain = _db_to_linear(trim_db)
    return gain, trim_db, reasons


def _compatibility_verdict(
    windows: dict[str, _WindowMetrics],
    comparisons: dict[str, float],
    *,
    options: GainPlanOptions,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    post_delta = comparisons["bDropVsPostGainLayeredDb"]
    low_delta = comparisons["bDropLowVsBuildLowDb"]
    if post_delta < options.drop_energy_floor_db:
        reasons.append("drop_energy_below_layered_build")
    if post_delta < options.drop_energy_floor_db * 2.0:
        reasons.append("drop_energy_collapse")
    if low_delta < -4.0:
        reasons.append("drop_low_band_deficit")
    if low_delta < -8.0:
        reasons.append("severe_drop_low_band_deficit")
    if windows["bDropFirst"].impact_score < windows["bBuildFinal"].impact_score * 0.85:
        reasons.append("drop_impact_below_incoming_build")

    if "drop_energy_collapse" in reasons or "severe_drop_low_band_deficit" in reasons:
        return "reject_energy_drop", reasons
    if "drop_energy_below_layered_build" in reasons or "drop_low_band_deficit" in reasons:
        return "risky_energy_drop", reasons
    if post_delta >= -1.0 and low_delta >= -2.0:
        return "strong", ["drop_energy_matches_or_exceeds_layered_build"]
    return "usable", ["drop_energy_within_acceptable_range"]


def _apply_outgoing_gain(
    plan: dict[str, Any],
    transition: dict[str, Any],
    outgoing_placement: dict[str, Any],
    incoming_placement: dict[str, Any],
    *,
    outgoing_gain: float,
) -> list[dict[str, object]]:
    commands = _list_field(plan, "commands")
    outgoing_deck = _required_int(outgoing_placement, "deck")
    incoming_deck = _required_int(incoming_placement, "deck")
    incoming_full_time = _incoming_full_volume_time(commands, incoming_deck, transition)
    outgoing_command = _volume_command(commands, outgoing_deck)
    keyframes = _keyframes(outgoing_command)
    trim_time = incoming_full_time
    if outgoing_gain < 0.999:
        _upsert_keyframe(keyframes, trim_time, outgoing_gain, interpolation="hold")
    keyframes.sort(key=lambda keyframe: float(keyframe.get("at", 0.0)))
    return [
        {
            "at": _round(float(keyframe.get("at", 0.0))),
            "value": _round(float(keyframe.get("value", 0.0))),
            "interpolation": str(keyframe.get("interpolation", "linear")),
        }
        for keyframe in keyframes
    ]


def _apply_incoming_gain(
    plan: dict[str, Any],
    incoming_placement: dict[str, Any],
    *,
    incoming_gain: float,
) -> list[dict[str, object]]:
    incoming_deck = _required_int(incoming_placement, "deck")
    command = _volume_command(_list_field(plan, "commands"), incoming_deck)
    keyframes = _keyframes(command)
    if not math.isclose(incoming_gain, 1.0, rel_tol=0.0, abs_tol=0.000001):
        for keyframe in keyframes:
            value = _number(keyframe, "value", 0.0)
            keyframe["value"] = value * incoming_gain
    keyframes.sort(key=lambda keyframe: float(keyframe.get("at", 0.0)))
    return [
        {
            "at": _round(float(keyframe.get("at", 0.0))),
            "value": _round(float(keyframe.get("value", 0.0))),
            "interpolation": str(keyframe.get("interpolation", "linear")),
        }
        for keyframe in keyframes
    ]


def _incoming_full_volume_time(commands: list[Any], incoming_deck: int, transition: dict[str, Any]) -> float:
    command = _volume_command(commands, incoming_deck)
    keyframes = _keyframes(command)
    candidates = [
        _number(keyframe, "at")
        for keyframe in keyframes
        if _number(keyframe, "value", 0.0) >= 0.999
    ]
    if candidates:
        return min(candidates)
    start = _number(transition, "timelineStartSeconds", 0.0)
    end = _number(transition, "timelineEndSeconds", start)
    return start + (end - start) / 2.0


def _volume_command(commands: list[Any], deck: int) -> dict[str, Any]:
    for command in commands:
        if not isinstance(command, dict):
            continue
        if command.get("type") == "automate" and command.get("deck") == deck and command.get("control") == "volume":
            return command
    raise MixPlanEnergyError("missing_volume_automation", f"Missing volume automation for deck {deck}")


def _keyframes(command: dict[str, Any]) -> list[dict[str, Any]]:
    keyframes = command.get("keyframes")
    if not isinstance(keyframes, list):
        raise MixPlanEnergyError("invalid_keyframes", "Volume automation command has no keyframe array")
    for keyframe in keyframes:
        if not isinstance(keyframe, dict):
            raise MixPlanEnergyError("invalid_keyframes", "Automation keyframes must be objects")
    return keyframes


def _upsert_keyframe(keyframes: list[dict[str, Any]], at: float, value: float, *, interpolation: str) -> None:
    for keyframe in keyframes:
        if abs(_number(keyframe, "at", 0.0) - at) <= 0.000001:
            keyframe["value"] = value
            keyframe["interpolation"] = interpolation
            return
    keyframes.append({"at": at, "value": value, "interpolation": interpolation})


def _append_gain_annotation(
    plan: dict[str, Any],
    transition: dict[str, Any],
    placement: dict[str, Any],
    *,
    verdict: str,
    trim_db: float,
    incoming_gain_db: float,
    b_drop_delta_db: float,
) -> None:
    annotations = plan.setdefault("annotations", [])
    if not isinstance(annotations, list):
        return
    annotations.append(
        {
            "at": _number(transition, "timelineStartSeconds", 0.0),
            "placementId": placement.get("placementId"),
            "transitionId": transition.get("transitionId"),
            "message": (
                "Drop-switch energy gain post-pass: "
                f"verdict={verdict}, outgoing overlap trim={trim_db:.2f}dB, "
                f"incoming drop gain={incoming_gain_db:.2f}dB, "
                f"B drop vs planned layered build={b_drop_delta_db:.2f}dB"
            ),
        }
    )


def _report_payload(
    *,
    input_mix_plan: Path,
    output_mix_plan: Path,
    report_path: Path,
    context: _PlanContext,
    windows: dict[str, _WindowMetrics],
    comparisons: dict[str, float],
    verdict: str,
    reasons: tuple[str, ...],
    outgoing_gain: float,
    outgoing_trim_db: float,
    incoming_gain: float,
    incoming_gain_db: float,
    outgoing_keyframes: list[dict[str, object]],
    incoming_keyframes: list[dict[str, object]],
    options: GainPlanOptions,
) -> dict[str, object]:
    return {
        "ok": True,
        "artifact": "mixplan-drop-switch-energy-report",
        "inputMixPlan": str(input_mix_plan),
        "outputMixPlan": str(output_mix_plan),
        "reportPath": str(report_path),
        "transitionId": _required_string(context.transition, "transitionId"),
        "fromPlacementId": _required_string(context.transition, "fromPlacementId"),
        "toPlacementId": _required_string(context.transition, "toPlacementId"),
        "verdict": verdict,
        "reasons": list(reasons),
        "recommendedOutgoingTrimDb": _round(outgoing_trim_db),
        "postGainOutgoingGain": _round(outgoing_gain),
        "recommendedIncomingDropGainDb": _round(incoming_gain_db),
        "postGainIncomingDropGain": _round(incoming_gain),
        "settings": {
            "sampleRate": options.sample_rate,
            "targetHeadroomDb": options.target_headroom_db,
            "maxOverlapGainReductionDb": options.max_overlap_gain_reduction_db,
            "dropEnergyFloorDb": options.drop_energy_floor_db,
            "windowMeasures": options.window_measures,
            "lowCutoffHz": options.low_cutoff_hz,
            "highCutoffHz": options.high_cutoff_hz,
            "targetDropLoudnessToleranceDb": options.target_drop_loudness_tolerance_db,
            "maxIncomingBoostDb": options.max_incoming_boost_db,
            "maxIncomingTrimDb": options.max_incoming_trim_db,
            "dropPeakMatchToleranceDb": options.drop_peak_match_tolerance_db,
            "maxDropPeakMatchBoostDb": options.max_drop_peak_match_boost_db,
            "dropPeakWindowBeats": options.drop_peak_window_beats,
        },
        "windows": {name: metrics.to_dict() for name, metrics in windows.items()},
        "comparisons": {key: _round(value) for key, value in comparisons.items()},
        "finalVolumeKeyframes": {
            "outgoing": outgoing_keyframes,
            "incoming": incoming_keyframes,
        },
    }


def _layered_build_rms_db(
    a_build: _WindowMetrics,
    b_build: _WindowMetrics,
    *,
    outgoing_gain: float,
    incoming_gain: float = 1.0,
) -> float:
    layered = math.sqrt((a_build.non_low_rms_linear * outgoing_gain) ** 2 + (b_build.rms_linear * incoming_gain) ** 2)
    return _linear_to_db(layered)


def _drop_switch_transition(transitions: list[Any]) -> dict[str, Any]:
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        if transition.get("technique") == "build_to_drop_swap":
            return transition
    raise MixPlanEnergyError("missing_drop_switch_transition", "MixPlan has no build_to_drop_swap transition")


def _anchor_seconds(anchors: dict[str, Any], name: str) -> float:
    anchor = anchors.get(name)
    if not isinstance(anchor, dict):
        raise MixPlanEnergyError("missing_source_anchor", f"Missing source anchor: {name}")
    return _number(anchor, "sourceSeconds")


def _load_plan_audio(
    track_id: str,
    assets: dict[str, dict[str, Any]],
    *,
    mix_plan_path: Path,
    options: GainPlanOptions,
) -> LoadedAudio:
    asset = assets.get(track_id)
    if asset is None:
        raise MixPlanEnergyError("missing_asset", f"MixPlan has no asset entry for trackId: {track_id}")
    source_uri = _required_string(asset, "sourceUri")
    source_path = _resolve_source_path(source_uri, mix_plan_path=mix_plan_path, asset_root=options.asset_root)
    try:
        return _load_audio(source_path, sample_rate=options.sample_rate)
    except ValueError as exc:
        raise MixPlanEnergyError("audio_load_failed", str(exc)) from exc


def _asset_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for asset in _list_field(plan, "assets"):
        if not isinstance(asset, dict):
            raise MixPlanEnergyError("invalid_asset", "MixPlan assets must be objects")
        result[_required_string(asset, "trackId")] = asset
    return result


def _placement_map(placements: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for placement in placements:
        if not isinstance(placement, dict):
            raise MixPlanEnergyError("invalid_placement", "MixPlan placements must be objects")
        result[_required_string(placement, "placementId")] = placement
    return result


def _list_field(plan: dict[str, Any], field: str) -> list[Any]:
    value = plan.get(field, [])
    if not isinstance(value, list):
        raise MixPlanEnergyError(f"invalid_{field}", f"MixPlan {field} must be an array")
    return value


def _required_string(value: dict[str, Any], field: str) -> str:
    field_value = value.get(field)
    if not isinstance(field_value, str) or not field_value:
        raise MixPlanEnergyError(f"missing_{field}", f"Expected non-empty string field: {field}")
    return field_value


def _required_int(value: dict[str, Any], field: str) -> int:
    field_value = value.get(field)
    if not isinstance(field_value, int):
        raise MixPlanEnergyError(f"missing_{field}", f"Expected integer field: {field}")
    return field_value


def _number(value: dict[str, Any], field: str, default: float | None = None) -> float:
    field_value = value.get(field, default)
    if not isinstance(field_value, int | float):
        raise MixPlanEnergyError(f"missing_{field}", f"Expected numeric field: {field}")
    return float(field_value)


def _rms(samples: tuple[float, ...] | list[float]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(float(sample) * float(sample) for sample in samples) / len(samples))


def _linear_to_db(value: float) -> float:
    return 20.0 * math.log10(max(abs(value), _EPSILON))


def _db_to_linear(value: float) -> float:
    return 10.0 ** (value / 20.0)


def _round(value: float) -> float:
    if not math.isfinite(value):
        return value
    return round(float(value), 6)
