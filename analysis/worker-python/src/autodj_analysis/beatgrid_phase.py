"""Beatgrid phase refinement from high-confidence drop-wall anchors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import copy
import json
import math
from pathlib import Path
from typing import Any
import wave

from .audio_io import DecodedAudio, load_audio
from .cache import write_json_atomic
from .drop_wall import DropWallOptions, detect_drop_wall


BEATGRID_PHASE_REFINER_NAME = "autodj-beatgrid-phase-refiner"
BEATGRID_PHASE_REFINER_VERSION = "drop-wall-phase-v1"


class BeatgridPhaseError(ValueError):
    """Expected beatgrid phase refinement failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class PhaseAnchorInput:
    label: str
    time_seconds: float


@dataclass(frozen=True)
class BeatgridPhaseOptions:
    sample_rate: int = 44_100
    search_window_seconds: float = 0.45
    preferred_window_seconds: float = 0.120
    preferred_score_ratio: float = 0.60
    min_wall_score: float = 0.45
    max_wall_offset_seconds: float = 0.120
    consensus_tolerance_seconds: float = 0.015
    min_consensus_anchors: int = 1
    beats_per_bar: int = 4
    smoke_pre_beats: int = 8
    smoke_post_beats: int = 8


def refine_beatgrid_phase_file(
    analyzed_track_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
    *,
    report_path: str | Path | None = None,
    smoke_dir: str | Path | None = None,
    anchors: tuple[PhaseAnchorInput, ...] = (),
    options: BeatgridPhaseOptions | None = None,
) -> Path:
    """Refine an analyzed-track beatgrid phase using drop-wall anchors."""

    analyzed_path = Path(analyzed_track_path)
    artifact = json.loads(analyzed_path.read_text(encoding="utf-8"))
    audio = load_audio(audio_path, target_sample_rate=(options or BeatgridPhaseOptions()).sample_rate)
    refined, report = refine_beatgrid_phase(
        artifact,
        audio,
        anchors=anchors,
        options=options,
    )
    output = write_json_atomic(output_path, refined)
    if report_path is not None:
        write_json_atomic(report_path, report)
    if smoke_dir is not None:
        write_phase_smoke_wavs(smoke_dir, audio, refined, report, options=options)
    return output


def refine_beatgrid_phase(
    artifact: dict[str, Any],
    audio: DecodedAudio,
    *,
    anchors: tuple[PhaseAnchorInput, ...] = (),
    options: BeatgridPhaseOptions | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a phase-shifted analyzed-track artifact and an explainable report."""

    options = options or BeatgridPhaseOptions()
    _validate_options(options)
    beats = _beat_entries(artifact)
    if not beats:
        raise BeatgridPhaseError("missing_beatgrid", "Analyzed track has no beatGrid.beats entries")

    anchor_inputs = anchors or _anchors_from_artifact(artifact)
    if not anchor_inputs:
        raise BeatgridPhaseError(
            "missing_drop_anchors",
            "No drop anchors were provided and no drop cue points were found in the analyzed track",
        )

    anchor_reports = []
    drop_options = DropWallOptions(
        sample_rate=options.sample_rate,
        search_window_seconds=options.search_window_seconds,
        preferred_window_seconds=options.preferred_window_seconds,
        preferred_score_ratio=options.preferred_score_ratio,
    )
    for anchor in anchor_inputs:
        nearest_index, nearest_time = _nearest_beat(beats, anchor.time_seconds)
        wall_artifact = detect_drop_wall(
            audio,
            approximate_time_seconds=anchor.time_seconds,
            track_id=str(artifact.get("trackId", audio.source_path.stem)),
            options=drop_options,
        )
        selected = wall_artifact["selectedWall"]
        risk_profile = wall_artifact.get("riskProfile") if isinstance(wall_artifact.get("riskProfile"), dict) else {}
        wall_time = float(selected["timeSeconds"])
        wall_score = float(selected["score"])
        wall_offset = wall_time - anchor.time_seconds
        correction = wall_time - nearest_time
        accepted = (
            wall_score >= options.min_wall_score
            and abs(wall_offset) <= options.max_wall_offset_seconds
        )
        reasons = []
        if wall_score < options.min_wall_score:
            reasons.append("wall_score_below_threshold")
        if abs(wall_offset) > options.max_wall_offset_seconds:
            reasons.append("wall_too_far_from_anchor")
        anchor_reports.append(
            {
                "label": anchor.label,
                "anchorTimeSeconds": _round(anchor.time_seconds),
                "nearestBeatIndex": nearest_index,
                "nearestBeatTimeSeconds": _round(nearest_time),
                "selectedWallTimeSeconds": _round(wall_time),
                "selectedWallOffsetMilliseconds": _round(wall_offset * 1000.0, 3),
                "phaseCorrectionMilliseconds": _round(correction * 1000.0, 3),
                "selectedWallScore": _round(wall_score, 6),
                "accepted": accepted,
                "reasons": reasons,
                "riskProfile": risk_profile,
                "selectedWallFeatures": selected.get("features", {}),
                "topCandidates": wall_artifact.get("candidates", [])[:5],
            }
        )

    accepted = [anchor for anchor in anchor_reports if bool(anchor["accepted"])]
    warnings: list[str] = []
    applied = False
    phase_shift_seconds = 0.0
    consensus = []
    if not accepted:
        warnings.append("No drop-wall anchors passed score/proximity acceptance thresholds.")
    else:
        corrections = [float(anchor["phaseCorrectionMilliseconds"]) / 1000.0 for anchor in accepted]
        median = _median(corrections)
        consensus = [
            anchor
            for anchor in accepted
            if abs(float(anchor["phaseCorrectionMilliseconds"]) / 1000.0 - median)
            <= options.consensus_tolerance_seconds
        ]
        required = min(options.min_consensus_anchors, len(accepted))
        if len(consensus) >= required:
            phase_shift_seconds = _median(
                [float(anchor["phaseCorrectionMilliseconds"]) / 1000.0 for anchor in consensus]
            )
            applied = True
        else:
            warnings.append(
                "Accepted drop-wall anchors disagreed beyond the consensus tolerance; beatgrid was left unchanged."
            )

    transition_recommendations = _phase_transition_recommendations(
        applied=applied,
        consensus_anchors=consensus,
        evaluated_anchors=anchor_reports,
    )
    refined = copy.deepcopy(artifact)
    if applied:
        _shift_beatgrid(refined, phase_shift_seconds)
        _refresh_semantic_beat_indices(refined)
    _attach_refinement_metadata(
        refined,
        phase_shift_seconds=phase_shift_seconds,
        applied=applied,
        report_anchors=anchor_reports,
        transition_recommendations=transition_recommendations,
    )

    report = {
        "artifact": "beatgrid-phase-refinement-report",
        "refiner": {
            "name": BEATGRID_PHASE_REFINER_NAME,
            "version": BEATGRID_PHASE_REFINER_VERSION,
            "createdAtUtc": _utc_now_iso(),
        },
        "trackId": artifact.get("trackId"),
        "source": {
            "audioPath": str(audio.source_path),
            "sampleRate": audio.sample_rate,
            "durationSeconds": audio.duration_seconds,
        },
        "options": {
            "searchWindowSeconds": options.search_window_seconds,
            "preferredWindowSeconds": options.preferred_window_seconds,
            "preferredScoreRatio": options.preferred_score_ratio,
            "minWallScore": options.min_wall_score,
            "maxWallOffsetSeconds": options.max_wall_offset_seconds,
            "consensusToleranceSeconds": options.consensus_tolerance_seconds,
            "minConsensusAnchors": options.min_consensus_anchors,
            "beatsPerBar": options.beats_per_bar,
        },
        "applied": applied,
        "phaseShiftSeconds": _round(phase_shift_seconds),
        "phaseShiftMilliseconds": _round(phase_shift_seconds * 1000.0, 3),
        "acceptedAnchorCount": len(accepted),
        "consensusAnchorCount": len(consensus),
        "transitionRecommendations": transition_recommendations,
        "anchors": anchor_reports,
        "warnings": warnings,
    }
    return refined, report


def write_phase_smoke_wavs(
    smoke_dir: str | Path,
    audio: DecodedAudio,
    refined_artifact: dict[str, Any],
    report: dict[str, Any],
    *,
    options: BeatgridPhaseOptions | None = None,
) -> list[Path]:
    """Write metronome smoke clips around refined drop-wall anchors."""

    options = options or BeatgridPhaseOptions()
    numpy = _require_numpy()
    samples = numpy.asarray(audio.samples, dtype=numpy.float32).reshape(-1)
    beats = _beat_entries(refined_artifact)
    if not beats:
        return []
    output_dir = Path(smoke_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, anchor in enumerate(report.get("anchors", []), start=1):
        if not bool(anchor.get("accepted")):
            continue
        center = float(anchor["selectedWallTimeSeconds"])
        nearest_index, _ = _nearest_beat(beats, center)
        start_index = max(0, nearest_index - options.smoke_pre_beats)
        end_index = min(len(beats) - 1, nearest_index + options.smoke_post_beats)
        start_time = max(0.0, beats[start_index][1] - 0.20)
        end_time = min(audio.duration_seconds, beats[end_index][1] + 0.35)
        clip = _clip(samples, audio.sample_rate, start_time, end_time, numpy=numpy)
        stereo = numpy.repeat((clip * 0.35)[:, None], 2, axis=1)
        for beat_index in range(start_index, end_index + 1):
            beat_time = beats[beat_index][1]
            is_bar = beat_index % options.beats_per_bar == 0
            _add_tick(
                stereo,
                audio.sample_rate,
                beat_time - start_time,
                frequency=1200.0 if is_bar else 850.0,
                amplitude=1.0 if is_bar else 0.78,
                duration_seconds=0.045 if is_bar else 0.035,
                numpy=numpy,
            )
        _add_tick(
            stereo,
            audio.sample_rate,
            center - start_time,
            frequency=2350.0,
            amplitude=1.25,
            duration_seconds=0.075,
            numpy=numpy,
        )
        label = _safe_slug(str(anchor.get("label", f"anchor-{index}")))
        output_path = output_dir / f"{index:02d}-{label}-refined-grid-clicks.wav"
        _write_wav(output_path, stereo, audio.sample_rate, numpy=numpy)
        written.append(output_path)
    return written


def parse_phase_anchor(value: str) -> PhaseAnchorInput:
    """Parse a CLI anchor string in either `seconds` or `label=seconds` form."""

    if "=" in value:
        label, raw_seconds = value.split("=", 1)
        label = label.strip() or "anchor"
    else:
        label = "anchor"
        raw_seconds = value
    try:
        seconds = float(raw_seconds)
    except ValueError as error:
        raise BeatgridPhaseError("invalid_anchor", f"Invalid anchor time: {value}") from error
    if seconds < 0.0:
        raise BeatgridPhaseError("invalid_anchor", f"Anchor time must be non-negative: {value}")
    return PhaseAnchorInput(label=label, time_seconds=seconds)


def _beat_entries(artifact: dict[str, Any]) -> list[tuple[int, float]]:
    beat_grid = artifact.get("beatGrid") if isinstance(artifact.get("beatGrid"), dict) else {}
    beats = beat_grid.get("beats") if isinstance(beat_grid.get("beats"), list) else []
    entries = []
    for fallback_index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            continue
        try:
            entries.append((int(beat.get("index", fallback_index)), float(beat["timeSeconds"])))
        except (KeyError, TypeError, ValueError):
            continue
    return entries


def _anchors_from_artifact(artifact: dict[str, Any]) -> tuple[PhaseAnchorInput, ...]:
    anchors: list[PhaseAnchorInput] = []
    seen: set[int] = set()
    cue_points = artifact.get("cuePoints") if isinstance(artifact.get("cuePoints"), list) else []
    for cue in cue_points:
        if not isinstance(cue, dict):
            continue
        name = str(cue.get("name", cue.get("id", ""))).lower()
        cue_type = str(cue.get("type", "")).lower()
        if cue_type != "drop" and "drop" not in name:
            continue
        if "end" in name or cue_type == "mix_out":
            continue
        try:
            time_seconds = float(cue["timeSeconds"])
        except (KeyError, TypeError, ValueError):
            continue
        key = round(time_seconds * 1000.0)
        if key in seen:
            continue
        seen.add(key)
        anchors.append(PhaseAnchorInput(label=str(cue.get("name", cue.get("id", "drop"))), time_seconds=time_seconds))
    return tuple(anchors)


def _nearest_beat(beats: list[tuple[int, float]], time_seconds: float) -> tuple[int, float]:
    return min(beats, key=lambda beat: abs(beat[1] - time_seconds))


def _shift_beatgrid(artifact: dict[str, Any], phase_shift_seconds: float) -> None:
    beat_grid = artifact.get("beatGrid") if isinstance(artifact.get("beatGrid"), dict) else {}
    for key in ("beats", "downbeats"):
        markers = beat_grid.get(key) if isinstance(beat_grid.get(key), list) else []
        for marker in markers:
            if isinstance(marker, dict) and isinstance(marker.get("timeSeconds"), (int, float)):
                marker["timeSeconds"] = _round(max(0.0, float(marker["timeSeconds"]) + phase_shift_seconds))


def _refresh_semantic_beat_indices(artifact: dict[str, Any]) -> None:
    beats = _beat_entries(artifact)
    if not beats:
        return
    cue_points = artifact.get("cuePoints") if isinstance(artifact.get("cuePoints"), list) else []
    for cue in cue_points:
        if isinstance(cue, dict) and isinstance(cue.get("timeSeconds"), (int, float)):
            cue["beatIndex"] = _nearest_beat(beats, float(cue["timeSeconds"]))[0]
    sections = artifact.get("sections") if isinstance(artifact.get("sections"), list) else []
    for section in sections:
        if not isinstance(section, dict):
            continue
        if isinstance(section.get("startSeconds"), (int, float)):
            section["startBeatIndex"] = _nearest_beat(beats, float(section["startSeconds"]))[0]
        if isinstance(section.get("endSeconds"), (int, float)):
            section["endBeatIndex"] = _nearest_beat(beats, float(section["endSeconds"]))[0]


def _attach_refinement_metadata(
    artifact: dict[str, Any],
    *,
    phase_shift_seconds: float,
    applied: bool,
    report_anchors: list[dict[str, Any]],
    transition_recommendations: dict[str, Any],
) -> None:
    beat_grid = artifact.setdefault("beatGrid", {})
    beat_grid["phaseRefinement"] = {
        "name": BEATGRID_PHASE_REFINER_NAME,
        "version": BEATGRID_PHASE_REFINER_VERSION,
        "createdAtUtc": _utc_now_iso(),
        "applied": applied,
        "phaseShiftSeconds": _round(phase_shift_seconds),
        "phaseShiftMilliseconds": _round(phase_shift_seconds * 1000.0, 3),
        "anchorCount": len(report_anchors),
        "transitionRecommendations": transition_recommendations,
    }
    analyzer = artifact.setdefault("analyzer", {})
    analyzer["beatgridPhaseRefinedAtUtc"] = _utc_now_iso()


def _phase_transition_recommendations(
    *,
    applied: bool,
    consensus_anchors: list[dict[str, Any]],
    evaluated_anchors: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered_families = [
        "drop_switch",
        "layered_drop",
        "double_drop",
        "reverb_exit",
        "simple_handoff",
    ]
    if not applied or not consensus_anchors:
        risk_flags = _anchor_risk_flags(evaluated_anchors)
        return {
            "verdict": "reject_precision",
            "allowedTransitionFamilies": ["simple_handoff"],
            "dropSwitchSafe": False,
            "layeredDropSafe": False,
            "precisionSafe": False,
            "riskFlags": sorted(set([*risk_flags, "phase_refinement_not_applied"])),
            "anchorLabels": [str(anchor.get("label", "")) for anchor in evaluated_anchors],
            "reason": "Beatgrid phase refinement was not applied, so precision transitions should be avoided.",
        }

    risk_profiles = [
        anchor.get("riskProfile")
        for anchor in consensus_anchors
        if isinstance(anchor.get("riskProfile"), dict)
    ]
    risk_flags = _anchor_risk_flags(consensus_anchors)
    if len(risk_profiles) != len(consensus_anchors):
        risk_flags.append("missing_anchor_risk_profile")

    allowed_sets = [
        set(str(family) for family in profile.get("allowedTransitionFamilies", []))
        for profile in risk_profiles
    ]
    if allowed_sets:
        allowed = set.intersection(*allowed_sets)
    else:
        allowed = {"simple_handoff"}
    allowed_ordered = [family for family in ordered_families if family in allowed]
    if not allowed_ordered:
        allowed_ordered = ["simple_handoff"]

    all_strong = bool(risk_profiles) and all(profile.get("verdict") == "strong" for profile in risk_profiles)
    all_drop_switch_safe = bool(risk_profiles) and all(bool(profile.get("dropSwitchSafe")) for profile in risk_profiles)
    all_precision_safe = bool(risk_profiles) and all(bool(profile.get("precisionSafe")) for profile in risk_profiles)

    if all_strong and "drop_switch" in allowed:
        verdict = "strong"
        reason = "All consensus drop-wall anchors are strong enough for precision drop transitions."
    elif all_drop_switch_safe and "drop_switch" in allowed:
        verdict = "usable"
        reason = "Consensus drop-wall anchors are usable for drop switches, but not strong enough for layered/double drops."
    elif "reverb_exit" in allowed:
        verdict = "risky_anchor"
        reason = "Consensus drop-wall anchors are too risky for precision drop switches; use safer transition families."
    else:
        verdict = "reject_precision"
        reason = "Consensus drop-wall anchors are not reliable enough for precision transitions."

    return {
        "verdict": verdict,
        "allowedTransitionFamilies": allowed_ordered,
        "dropSwitchSafe": "drop_switch" in allowed_ordered,
        "layeredDropSafe": "layered_drop" in allowed_ordered,
        "precisionSafe": all_precision_safe and "drop_switch" in allowed_ordered,
        "riskFlags": sorted(set(risk_flags)),
        "anchorLabels": [str(anchor.get("label", "")) for anchor in consensus_anchors],
        "reason": reason,
    }


def _anchor_risk_flags(anchors: list[dict[str, Any]]) -> list[str]:
    risk_flags: list[str] = []
    for anchor in anchors:
        risk_profile = anchor.get("riskProfile") if isinstance(anchor.get("riskProfile"), dict) else {}
        for flag in risk_profile.get("riskFlags", []):
            risk_flags.append(str(flag))
    return risk_flags


def _validate_options(options: BeatgridPhaseOptions) -> None:
    if options.sample_rate <= 0:
        raise BeatgridPhaseError("invalid_options", "sample_rate must be greater than zero")
    for name in (
        "search_window_seconds",
        "preferred_window_seconds",
        "max_wall_offset_seconds",
        "consensus_tolerance_seconds",
    ):
        if getattr(options, name) <= 0.0:
            raise BeatgridPhaseError("invalid_options", f"{name} must be greater than zero")
    if options.min_wall_score < 0.0:
        raise BeatgridPhaseError("invalid_options", "min_wall_score must be non-negative")
    if options.min_consensus_anchors <= 0:
        raise BeatgridPhaseError("invalid_options", "min_consensus_anchors must be greater than zero")
    if options.beats_per_bar <= 0:
        raise BeatgridPhaseError("invalid_options", "beats_per_bar must be greater than zero")


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _clip(samples: Any, sample_rate: int, start_time: float, end_time: float, *, numpy: Any) -> Any:
    start = max(0, int(round(start_time * sample_rate)))
    end = min(len(samples), int(round(end_time * sample_rate)))
    if end <= start:
        return numpy.zeros(1, dtype=numpy.float32)
    return samples[start:end].astype(numpy.float32, copy=True)


def _add_tick(
    stereo: Any,
    sample_rate: int,
    time_seconds: float,
    *,
    frequency: float,
    amplitude: float,
    duration_seconds: float,
    numpy: Any,
) -> None:
    start = int(round(time_seconds * sample_rate))
    duration = max(1, int(round(duration_seconds * sample_rate)))
    if start < 0 or start >= len(stereo):
        return
    end = min(len(stereo), start + duration)
    count = end - start
    t = numpy.arange(count, dtype=numpy.float32) / sample_rate
    envelope = numpy.hanning(count * 2)[:count].astype(numpy.float32)
    tick = numpy.sin(2.0 * math.pi * frequency * t) * envelope * amplitude
    stereo[start:end, 0] += tick
    stereo[start:end, 1] += tick


def _write_wav(path: Path, stereo: Any, sample_rate: int, *, numpy: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    peak = float(numpy.max(numpy.abs(stereo))) if stereo.size else 1.0
    if peak > 0.98:
        stereo = stereo * (0.98 / peak)
    pcm = numpy.asarray(numpy.clip(stereo, -1.0, 1.0) * 32767.0, dtype="<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def _safe_slug(value: str) -> str:
    safe = [character.lower() if character.isalnum() else "-" for character in value]
    slug = "".join(safe).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "anchor"


def _require_numpy() -> Any:
    try:
        import numpy
    except ImportError as error:
        raise BeatgridPhaseError("missing_dependency", "numpy is required for smoke WAV generation") from error
    return numpy


def _round(value: float, places: int = 6) -> float:
    return round(float(value), places)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
