"""Drop-wall detector for explainable dubstep drop transient debugging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from . import __version__
from .audio_io import DecodedAudio, load_audio
from .cache import SCHEMA_VERSION, write_json_atomic


DROP_WALL_DETECTOR_NAME = "autodj-drop-wall-detector"
DROP_WALL_DETECTOR_VERSION = "envelope-wall-v1"


class DropWallError(ValueError):
    """Expected drop-wall detection failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class DropWallOptions:
    sample_rate: int = 44_100
    search_window_seconds: float = 0.45
    preferred_window_seconds: float = 0.120
    preferred_score_ratio: float = 0.60
    hop_seconds: float = 0.001
    envelope_window_seconds: float = 0.006
    pre_window_seconds: float = 0.080
    post_window_seconds: float = 0.045
    sustain_window_seconds: float = 0.250
    low_cutoff_hz: float = 180.0
    high_cutoff_hz: float = 2_000.0
    max_candidates: int = 12
    svg_width: int = 1400
    svg_height: int = 420


@dataclass(frozen=True)
class DropWallCandidate:
    rank: int
    time_seconds: float
    offset_seconds: float
    score: float
    features: dict[str, float]
    selected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "timeSeconds": _round_float(self.time_seconds, 6),
            "offsetSeconds": _round_float(self.offset_seconds, 6),
            "offsetMilliseconds": _round_float(self.offset_seconds * 1000.0, 3),
            "score": _round_float(self.score, 6),
            "selected": self.selected,
            "features": {key: _round_float(value, 6) for key, value in self.features.items()},
        }


def detect_drop_wall_file(
    audio_path: str | Path,
    output_path: str | Path,
    *,
    approximate_time_seconds: float,
    svg_path: str | Path | None = None,
    track_id: str | None = None,
    options: DropWallOptions | None = None,
) -> Path:
    """Detect the strongest drop wall around an approximate source timestamp."""

    options = options or DropWallOptions()
    if options.sample_rate <= 0:
        raise DropWallError("invalid_options", "sample_rate must be greater than zero")
    audio = load_audio(audio_path, target_sample_rate=options.sample_rate)
    artifact = detect_drop_wall(
        audio,
        approximate_time_seconds=approximate_time_seconds,
        track_id=track_id or Path(audio_path).stem,
        options=options,
    )
    written = write_json_atomic(output_path, artifact)
    if svg_path is not None:
        write_drop_wall_svg(svg_path, artifact)
    return written


def detect_drop_wall(
    audio: DecodedAudio,
    *,
    approximate_time_seconds: float,
    track_id: str,
    options: DropWallOptions | None = None,
) -> dict[str, Any]:
    """Return an explainable drop-wall debug artifact for an approximate drop."""

    options = options or DropWallOptions()
    _validate_options(audio, approximate_time_seconds, options)
    numpy = _require("numpy", "numpy")
    scipy_signal = _require("scipy", "scipy.signal")

    samples = numpy.asarray(audio.samples, dtype=numpy.float32).reshape(-1)
    if samples.size == 0:
        raise DropWallError("empty_audio", "Decoded audio has no samples")

    low, mid, high = _split_bands(
        samples,
        sample_rate=audio.sample_rate,
        low_cutoff_hz=options.low_cutoff_hz,
        high_cutoff_hz=options.high_cutoff_hz,
        numpy=numpy,
        scipy_signal=scipy_signal,
    )
    start_seconds = max(0.0, approximate_time_seconds - options.search_window_seconds)
    end_seconds = min(audio.duration_seconds, approximate_time_seconds + options.search_window_seconds)
    times, envelopes = _window_envelopes(
        samples,
        low,
        mid,
        high,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        sample_rate=audio.sample_rate,
        options=options,
        numpy=numpy,
    )
    if len(times) < 8:
        raise DropWallError("window_too_small", "Drop-wall search window produced too few frames")

    raw_candidates = _raw_candidates(
        times,
        envelopes,
        approximate_time_seconds=approximate_time_seconds,
        options=options,
    )
    if not raw_candidates:
        raise DropWallError("no_candidates", "No drop-wall candidates were produced")
    candidates = _rank_candidates(raw_candidates, max_candidates=options.max_candidates)
    selected = _selected_candidate(candidates, options=options)
    selected = DropWallCandidate(
        rank=1,
        time_seconds=selected.time_seconds,
        offset_seconds=selected.offset_seconds,
        score=selected.score,
        features=selected.features,
        selected=True,
    )
    candidates = _selected_first(candidates, selected)
    risk_profile = _drop_wall_risk_profile(
        selected,
        candidates,
        preferred_window_seconds=options.preferred_window_seconds,
    )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "artifact": "drop-wall-debug",
        "detector": {
            "name": DROP_WALL_DETECTOR_NAME,
            "version": DROP_WALL_DETECTOR_VERSION,
            "producerVersion": __version__,
            "createdAtUtc": _utc_now_iso(),
        },
        "trackId": track_id,
        "source": {
            "audioPath": str(audio.source_path),
            "sampleRate": audio.sample_rate,
            "durationSeconds": audio.duration_seconds,
        },
        "parameters": {
            "approximateTimeSeconds": approximate_time_seconds,
            "searchWindowSeconds": options.search_window_seconds,
            "preferredWindowSeconds": options.preferred_window_seconds,
            "preferredScoreRatio": options.preferred_score_ratio,
            "hopSeconds": options.hop_seconds,
            "envelopeWindowSeconds": options.envelope_window_seconds,
            "preWindowSeconds": options.pre_window_seconds,
            "postWindowSeconds": options.post_window_seconds,
            "sustainWindowSeconds": options.sustain_window_seconds,
            "lowCutoffHz": options.low_cutoff_hz,
            "highCutoffHz": options.high_cutoff_hz,
            "maxCandidates": options.max_candidates,
        },
        "selectedWall": selected.to_dict(),
        "riskProfile": risk_profile,
        "candidates": [candidate.to_dict() for candidate in candidates],
        "envelopes": [
            {
                "timeSeconds": _round_float(time_seconds, 6),
                "full": _round_float(envelopes["full"][index], 6),
                "low": _round_float(envelopes["low"][index], 6),
                "mid": _round_float(envelopes["mid"][index], 6),
                "high": _round_float(envelopes["high"][index], 6),
                "wall": _round_float(envelopes["wall"][index], 6),
            }
            for index, time_seconds in enumerate(times)
        ],
    }


def write_drop_wall_svg(path: str | Path, artifact: dict[str, Any]) -> Path:
    """Write a compact visual SVG for a drop-wall debug artifact."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    svg = drop_wall_svg(artifact)
    output_path.write_text(svg, encoding="utf-8")
    return output_path


def drop_wall_svg(artifact: dict[str, Any]) -> str:
    """Return a self-contained SVG visualization for a drop-wall artifact."""

    width = 1600
    height = 620
    margin_left = 62
    table_left = 1260
    plot_width = table_left - margin_left - 24
    energy_top = 58
    energy_height = 260
    energy_bottom = energy_top + energy_height
    wall_top = 382
    wall_height = 120
    wall_bottom = wall_top + wall_height
    envelopes = artifact.get("envelopes", [])
    if not isinstance(envelopes, list) or not envelopes:
        raise DropWallError("invalid_artifact", "Drop-wall artifact has no envelopes")
    start_time = float(envelopes[0]["timeSeconds"])
    end_time = float(envelopes[-1]["timeSeconds"])
    span = max(1.0e-9, end_time - start_time)
    approx_time = float(artifact["parameters"]["approximateTimeSeconds"])
    selected_time = float(artifact["selectedWall"]["timeSeconds"])
    window_ms = float(artifact["parameters"]["searchWindowSeconds"]) * 1000.0
    preferred_ms = float(artifact["parameters"].get("preferredWindowSeconds", 0.0)) * 1000.0

    def x_for_time(value: float) -> float:
        return margin_left + (value - start_time) / span * plot_width

    def energy_y(value: float) -> float:
        return energy_bottom - max(0.0, min(1.0, value)) * energy_height

    def wall_y(value: float) -> float:
        return wall_bottom - max(0.0, min(1.0, value)) * wall_height

    full_path = _svg_polyline(
        ((x_for_time(float(point["timeSeconds"])), energy_y(float(point["full"]))) for point in envelopes),
        stroke="#ff4778",
        width=2.2,
    )
    low_path = _svg_polyline(
        ((x_for_time(float(point["timeSeconds"])), energy_y(float(point["low"]))) for point in envelopes),
        stroke="#42a5ff",
        width=1.4,
        opacity=0.85,
    )
    mid_path = _svg_polyline(
        ((x_for_time(float(point["timeSeconds"])), energy_y(float(point["mid"]))) for point in envelopes),
        stroke="#b86bff",
        width=1.0,
        opacity=0.55,
    )
    high_path = _svg_polyline(
        ((x_for_time(float(point["timeSeconds"])), energy_y(float(point["high"]))) for point in envelopes),
        stroke="#ff9d42",
        width=1.0,
        opacity=0.50,
    )
    wall_path = _svg_polyline(
        ((x_for_time(float(point["timeSeconds"])), wall_y(float(point["wall"]))) for point in envelopes),
        stroke="#ffd166",
        width=2.0,
        opacity=0.9,
    )
    candidate_lines = []
    for candidate in artifact.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        x = x_for_time(float(candidate["timeSeconds"]))
        selected = bool(candidate.get("selected"))
        color = "#ff3030" if selected else "#f7c948"
        line_width = 3 if selected else 1
        opacity = 1.0 if selected else 0.55
        label = "selected" if selected else f"#{candidate.get('rank')}"
        candidate_lines.append(
            f'<line x1="{x:.3f}" y1="{energy_top}" x2="{x:.3f}" y2="{wall_bottom}" '
            f'stroke="{color}" stroke-width="{line_width}" opacity="{opacity}"/>'
        )
        candidate_lines.append(
            f'<text x="{x + 4:.3f}" y="{energy_top + 15}" fill="{color}" '
            f'font-size="11" font-family="Arial">{_escape_xml(label)}</text>'
        )
    approx_x = x_for_time(approx_time)
    selected_x = x_for_time(selected_time)
    selected_offset_ms = float(artifact["selectedWall"]["offsetMilliseconds"])
    title = (
        f"{artifact.get('trackId', '')} drop-wall debug: selected "
        f"{selected_time:.3f}s ({selected_offset_ms:+.1f} ms)"
    )
    grid_lines = []
    for index in range(10):
        ratio = index / 9.0
        time_value = start_time + span * ratio
        x = x_for_time(time_value)
        rel_ms = (time_value - approx_time) * 1000.0
        grid_lines.append(
            f'<line x1="{x:.3f}" y1="{energy_top}" x2="{x:.3f}" y2="{wall_bottom}" '
            'stroke="#202020" stroke-width="1"/>'
        )
        grid_lines.append(
            f'<text x="{x - 28:.3f}" y="536" fill="#9a9a9a" font-size="11" font-family="Arial">'
            f'{rel_ms:+.0f}ms</text>'
        )
    candidate_table = _candidate_table_svg(artifact, table_left=table_left, start_y=90)
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#050505"/>',
        f'<text x="16" y="22" fill="#f6f6f6" font-size="15" font-family="Arial">{_escape_xml(title)}</text>',
        f'<text x="16" y="42" fill="#a7a7a7" font-size="12" font-family="Arial">Window: +/- {window_ms:.0f}ms around blue line. Preferred candidate window: +/- {preferred_ms:.0f}ms.</text>',
        f'<rect x="{margin_left}" y="{energy_top}" width="{plot_width}" height="{energy_height}" fill="#090909" stroke="#252525"/>',
        f'<rect x="{margin_left}" y="{wall_top}" width="{plot_width}" height="{wall_height}" fill="#090909" stroke="#252525"/>',
        *grid_lines,
        f'<text x="12" y="{energy_top + 18}" fill="#cfcfcf" font-size="12" font-family="Arial">Energy</text>',
        f'<text x="12" y="{wall_top + 18}" fill="#cfcfcf" font-size="12" font-family="Arial">Wall</text>',
        mid_path,
        high_path,
        full_path,
        low_path,
        wall_path,
        f'<line x1="{approx_x:.3f}" y1="{energy_top}" x2="{approx_x:.3f}" y2="{wall_bottom}" stroke="#37a2ff" stroke-width="2" opacity="0.9"/>',
        *candidate_lines,
        f'<line x1="{selected_x:.3f}" y1="{wall_bottom}" x2="{selected_x:.3f}" y2="{wall_bottom + 20}" stroke="#ff3030" stroke-width="3"/>',
        f'<text x="{max(margin_left, approx_x - 82):.3f}" y="560" fill="#37a2ff" font-size="13" font-family="Arial">blue = approximate {approx_time:.3f}s</text>',
        f'<text x="{min(table_left - 255, selected_x + 8):.3f}" y="582" fill="#ff3030" font-size="13" font-family="Arial">red = selected wall {selected_time:.3f}s</text>',
        '<text x="16" y="604" fill="#ff4778" font-size="12" font-family="Arial">full</text>',
        '<text x="58" y="604" fill="#42a5ff" font-size="12" font-family="Arial">low</text>',
        '<text x="96" y="604" fill="#b86bff" font-size="12" font-family="Arial">mid</text>',
        '<text x="136" y="604" fill="#ff9d42" font-size="12" font-family="Arial">high</text>',
        '<text x="180" y="604" fill="#ffd166" font-size="12" font-family="Arial">wall score</text>',
        candidate_table,
        "</svg>",
    ]
    return "\n".join(svg_parts)


def _candidate_table_svg(artifact: dict[str, Any], *, table_left: int, start_y: int) -> str:
    parts = [
        f'<text x="{table_left}" y="58" fill="#f4f4f4" font-size="14" font-family="Arial">Candidates</text>',
        f'<text x="{table_left}" y="78" fill="#9a9a9a" font-size="11" font-family="Arial">rank | offset | score | wall | low jump | sustain</text>',
    ]
    risk_profile = artifact.get("riskProfile") if isinstance(artifact.get("riskProfile"), dict) else {}
    if risk_profile:
        verdict = str(risk_profile.get("verdict", "unknown"))
        flags = ", ".join(str(flag) for flag in risk_profile.get("riskFlags", [])) or "none"
        parts.append(
            f'<text x="{table_left}" y="{start_y - 6}" fill="#f7c948" font-size="11" font-family="Arial">'
            f'{_escape_xml(f"risk: {verdict}; {flags}")}</text>'
        )
    for index, candidate in enumerate(artifact.get("candidates", [])[:10]):
        if not isinstance(candidate, dict):
            continue
        y = start_y + index * 26
        selected = bool(candidate.get("selected"))
        color = "#ff3030" if selected else "#d8d8d8"
        features = candidate.get("features", {}) if isinstance(candidate.get("features"), dict) else {}
        text = (
            f"{candidate.get('rank')}: "
            f"{float(candidate.get('offsetMilliseconds', 0.0)):+.1f}ms | "
            f"{float(candidate.get('score', 0.0)):.3f} | "
            f"{float(features.get('wall', 0.0)):.2f} | "
            f"{float(features.get('lowJump', 0.0)):.2f} | "
            f"{float(features.get('sustainFull', 0.0)):.2f}"
        )
        parts.append(
            f'<text x="{table_left}" y="{y}" fill="{color}" font-size="12" font-family="Consolas, monospace">'
            f'{_escape_xml(text)}</text>'
        )
    return "\n".join(parts)


def _drop_wall_risk_profile(
    selected: DropWallCandidate,
    candidates: tuple[DropWallCandidate, ...],
    *,
    preferred_window_seconds: float,
) -> dict[str, Any]:
    risk_flags: list[str] = []
    score = selected.score
    offset = abs(selected.offset_seconds)
    selected_features = selected.features
    wall_strength = float(selected_features.get("wall", 0.0))
    low_jump = float(selected_features.get("lowJump", 0.0))
    sustain = float(selected_features.get("sustainFull", 0.0))

    if score < 0.70:
        risk_flags.append("low_wall_score")
    elif score < 0.85:
        risk_flags.append("medium_wall_score")
    if offset > 0.070:
        risk_flags.append("far_from_semantic_cue")
    elif offset > 0.040:
        risk_flags.append("outside_precision_window")
    if wall_strength < 0.45:
        risk_flags.append("weak_wall_edge")
    if low_jump < 0.25:
        risk_flags.append("weak_low_band_arrival")
    if sustain < 0.65:
        risk_flags.append("weak_post_wall_sustain")

    selected_time = selected.time_seconds
    close_competitors = [
        candidate
        for candidate in candidates
        if not candidate.selected
        and selected.score - candidate.score <= 0.10
        and abs(candidate.time_seconds - selected_time) >= 0.015
    ]
    if close_competitors:
        risk_flags.append("ambiguous_competing_wall")
    far_stronger = [
        candidate
        for candidate in candidates
        if not candidate.selected
        and candidate.score > selected.score + 0.08
        and abs(candidate.offset_seconds) > preferred_window_seconds
    ]
    if far_stronger:
        risk_flags.append("far_stronger_wall_candidate")

    risky_flags = {
        "low_wall_score",
        "far_from_semantic_cue",
        "weak_wall_edge",
        "weak_post_wall_sustain",
        "ambiguous_competing_wall",
        "far_stronger_wall_candidate",
    }
    precision_blockers = risky_flags.intersection(risk_flags)
    if not precision_blockers and score >= 0.85 and offset <= 0.040:
        verdict = "strong"
        allowed = [
            "drop_switch",
            "layered_drop",
            "double_drop",
            "reverb_exit",
            "simple_handoff",
        ]
    elif "far_from_semantic_cue" not in risk_flags and score >= 0.70:
        verdict = "usable"
        allowed = ["drop_switch", "reverb_exit", "simple_handoff"]
    elif score >= 0.60:
        verdict = "risky_anchor"
        allowed = ["reverb_exit", "simple_handoff"]
    else:
        verdict = "reject_precision"
        allowed = ["simple_handoff"]

    return {
        "verdict": verdict,
        "riskFlags": sorted(set(risk_flags)),
        "allowedTransitionFamilies": allowed,
        "precisionSafe": verdict == "strong",
        "dropSwitchSafe": "drop_switch" in allowed,
        "layeredDropSafe": "layered_drop" in allowed,
        "score": _round_float(score, 6),
        "absOffsetMilliseconds": _round_float(offset * 1000.0, 3),
        "closeCompetitorCount": len(close_competitors),
    }


def _validate_options(audio: DecodedAudio, approximate_time_seconds: float, options: DropWallOptions) -> None:
    if audio.sample_rate <= 0:
        raise DropWallError("invalid_audio", "audio sample_rate must be greater than zero")
    if approximate_time_seconds < 0.0 or approximate_time_seconds > audio.duration_seconds:
        raise DropWallError("invalid_time", "approximate_time_seconds must be inside the audio duration")
    positive_options = {
        "search_window_seconds": options.search_window_seconds,
        "preferred_window_seconds": options.preferred_window_seconds,
        "hop_seconds": options.hop_seconds,
        "envelope_window_seconds": options.envelope_window_seconds,
        "pre_window_seconds": options.pre_window_seconds,
        "post_window_seconds": options.post_window_seconds,
        "sustain_window_seconds": options.sustain_window_seconds,
    }
    for name, value in positive_options.items():
        if value <= 0.0:
            raise DropWallError("invalid_options", f"{name} must be greater than zero")
    if options.low_cutoff_hz <= 0.0 or options.high_cutoff_hz <= options.low_cutoff_hz:
        raise DropWallError("invalid_options", "frequency cutoffs must be positive and ordered")
    if options.max_candidates <= 0:
        raise DropWallError("invalid_options", "max_candidates must be greater than zero")
    if options.preferred_score_ratio <= 0.0:
        raise DropWallError("invalid_options", "preferred_score_ratio must be greater than zero")


def _split_bands(
    samples: Any,
    *,
    sample_rate: int,
    low_cutoff_hz: float,
    high_cutoff_hz: float,
    numpy: Any,
    scipy_signal: Any,
) -> tuple[Any, Any, Any]:
    nyquist = sample_rate / 2.0
    if high_cutoff_hz >= nyquist:
        high_cutoff_hz = nyquist * 0.9
    low_sos = scipy_signal.butter(4, low_cutoff_hz / nyquist, btype="lowpass", output="sos")
    mid_sos = scipy_signal.butter(
        4,
        (low_cutoff_hz / nyquist, high_cutoff_hz / nyquist),
        btype="bandpass",
        output="sos",
    )
    high_sos = scipy_signal.butter(4, high_cutoff_hz / nyquist, btype="highpass", output="sos")
    filter_fn = scipy_signal.sosfiltfilt if samples.size > 256 else scipy_signal.sosfilt
    return (
        numpy.asarray(filter_fn(low_sos, samples), dtype=numpy.float32),
        numpy.asarray(filter_fn(mid_sos, samples), dtype=numpy.float32),
        numpy.asarray(filter_fn(high_sos, samples), dtype=numpy.float32),
    )


def _window_envelopes(
    samples: Any,
    low: Any,
    mid: Any,
    high: Any,
    *,
    start_seconds: float,
    end_seconds: float,
    sample_rate: int,
    options: DropWallOptions,
    numpy: Any,
) -> tuple[list[float], dict[str, list[float]]]:
    start = max(0, int(round(start_seconds * sample_rate)))
    end = min(len(samples), int(round(end_seconds * sample_rate)))
    hop = max(1, int(round(options.hop_seconds * sample_rate)))
    radius = max(1, int(round(options.envelope_window_seconds * sample_rate / 2.0)))
    times: list[float] = []
    full_values: list[float] = []
    low_values: list[float] = []
    mid_values: list[float] = []
    high_values: list[float] = []
    for center in range(start, end, hop):
        left = max(0, center - radius)
        right = min(len(samples), center + radius + 1)
        if right <= left:
            continue
        times.append(center / sample_rate)
        full_values.append(_peak_rms(samples[left:right], numpy=numpy))
        low_values.append(_peak_rms(low[left:right], numpy=numpy))
        mid_values.append(_peak_rms(mid[left:right], numpy=numpy))
        high_values.append(_peak_rms(high[left:right], numpy=numpy))
    full_values = _normalize(full_values)
    low_values = _normalize(low_values)
    mid_values = _normalize(mid_values)
    high_values = _normalize(high_values)
    wall_values = _wall_curve(full_values, low_values)
    return times, {
        "full": full_values,
        "low": low_values,
        "mid": mid_values,
        "high": high_values,
        "wall": wall_values,
    }


def _peak_rms(values: Any, *, numpy: Any) -> float:
    if values.size == 0:
        return 0.0
    peak = float(numpy.max(numpy.abs(values)))
    rms = float(numpy.sqrt(numpy.mean(values * values)))
    return 0.68 * peak + 0.32 * rms


def _raw_candidates(
    times: list[float],
    envelopes: dict[str, list[float]],
    *,
    approximate_time_seconds: float,
    options: DropWallOptions,
) -> list[DropWallCandidate]:
    pre_frames = max(1, round(options.pre_window_seconds / options.hop_seconds))
    post_frames = max(1, round(options.post_window_seconds / options.hop_seconds))
    sustain_frames = max(post_frames + 1, round(options.sustain_window_seconds / options.hop_seconds))
    raw_features: list[dict[str, float]] = []
    for index, time_seconds in enumerate(times):
        if index < pre_frames or index + sustain_frames >= len(times):
            continue
        pre_full = _mean(envelopes["full"][index - pre_frames:index])
        post_full = _mean(envelopes["full"][index:index + post_frames])
        sustain_full = _mean(envelopes["full"][index + post_frames:index + sustain_frames])
        pre_low = _mean(envelopes["low"][index - pre_frames:index])
        post_low = _mean(envelopes["low"][index:index + post_frames])
        sustain_low = _mean(envelopes["low"][index + post_frames:index + sustain_frames])
        wall = envelopes["wall"][index]
        proximity = max(
            0.0,
            1.0 - abs(time_seconds - approximate_time_seconds) / max(options.search_window_seconds, 1.0e-9),
        )
        raw_features.append(
            {
                "timeSeconds": time_seconds,
                "offsetSeconds": time_seconds - approximate_time_seconds,
                "fullJumpRaw": post_full - pre_full,
                "lowJumpRaw": post_low - pre_low,
                "sustainFullRaw": sustain_full,
                "sustainLowRaw": sustain_low,
                "preFullRaw": pre_full,
                "preLowRaw": pre_low,
                "wallRaw": wall,
                "proximity": proximity,
            }
        )
    if not raw_features:
        return []
    normalized_keys = ["fullJumpRaw", "lowJumpRaw", "sustainFullRaw", "sustainLowRaw", "wallRaw"]
    maxima = {key: max(1.0e-9, max(max(0.0, item[key]) for item in raw_features)) for key in normalized_keys}
    candidates = []
    for item in raw_features:
        full_jump = max(0.0, item["fullJumpRaw"]) / maxima["fullJumpRaw"]
        low_jump = max(0.0, item["lowJumpRaw"]) / maxima["lowJumpRaw"]
        sustain_full = max(0.0, item["sustainFullRaw"]) / maxima["sustainFullRaw"]
        sustain_low = max(0.0, item["sustainLowRaw"]) / maxima["sustainLowRaw"]
        wall = max(0.0, item["wallRaw"]) / maxima["wallRaw"]
        pre_quiet = max(0.0, min(1.0, 1.0 - item["preFullRaw"]))
        score = (
            0.28 * full_jump
            + 0.24 * wall
            + 0.18 * low_jump
            + 0.14 * sustain_full
            + 0.09 * sustain_low
            + 0.04 * pre_quiet
            + 0.03 * item["proximity"]
        )
        candidates.append(
            DropWallCandidate(
                rank=0,
                time_seconds=item["timeSeconds"],
                offset_seconds=item["offsetSeconds"],
                score=max(0.0, min(1.0, score)),
                features={
                    "fullJump": full_jump,
                    "lowJump": low_jump,
                    "wall": wall,
                    "sustainFull": sustain_full,
                    "sustainLow": sustain_low,
                    "preQuiet": pre_quiet,
                    "proximity": item["proximity"],
                    "preFullRaw": item["preFullRaw"],
                    "postFullRaw": item["preFullRaw"] + item["fullJumpRaw"],
                    "preLowRaw": item["preLowRaw"],
                    "postLowRaw": item["preLowRaw"] + item["lowJumpRaw"],
                },
            )
        )
    return candidates


def _rank_candidates(candidates: list[DropWallCandidate], *, max_candidates: int) -> tuple[DropWallCandidate, ...]:
    min_gap = 0.010
    ranked: list[DropWallCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (-item.score, abs(item.offset_seconds), item.time_seconds)):
        if any(abs(candidate.time_seconds - existing.time_seconds) < min_gap for existing in ranked):
            continue
        ranked.append(
            DropWallCandidate(
                rank=len(ranked) + 1,
                time_seconds=candidate.time_seconds,
                offset_seconds=candidate.offset_seconds,
                score=candidate.score,
                features=candidate.features,
                selected=False,
            )
        )
        if len(ranked) >= max_candidates:
            break
    return tuple(ranked)


def _selected_candidate(
    ranked_candidates: tuple[DropWallCandidate, ...],
    *,
    options: DropWallOptions,
) -> DropWallCandidate:
    strongest = ranked_candidates[0]
    threshold = strongest.score * options.preferred_score_ratio
    preferred = [
        candidate
        for candidate in ranked_candidates
        if abs(candidate.offset_seconds) <= options.preferred_window_seconds and candidate.score >= threshold
    ]
    if preferred:
        return max(preferred, key=lambda candidate: (candidate.score, -abs(candidate.offset_seconds)))
    return strongest


def _selected_first(
    ranked_candidates: tuple[DropWallCandidate, ...],
    selected: DropWallCandidate,
) -> tuple[DropWallCandidate, ...]:
    reordered: list[DropWallCandidate] = [selected]
    next_rank = 2
    for candidate in ranked_candidates:
        if abs(candidate.time_seconds - selected.time_seconds) < 1.0e-9:
            continue
        reordered.append(
            DropWallCandidate(
                rank=next_rank,
                time_seconds=candidate.time_seconds,
                offset_seconds=candidate.offset_seconds,
                score=candidate.score,
                features=candidate.features,
                selected=False,
            )
        )
        next_rank += 1
    return tuple(reordered)


def _wall_curve(full_values: list[float], low_values: list[float]) -> list[float]:
    if not full_values:
        return []
    wall = [0.0]
    for index in range(1, len(full_values)):
        derivative = max(0.0, full_values[index] - full_values[index - 1])
        low_derivative = max(0.0, low_values[index] - low_values[index - 1])
        wall.append(0.72 * derivative + 0.28 * low_derivative)
    return _normalize(wall)


def _normalize(values: list[float]) -> list[float]:
    peak = max((abs(value) for value in values), default=0.0)
    if peak <= 1.0e-12:
        return [0.0 for _ in values]
    return [max(0.0, min(1.0, value / peak)) for value in values]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _svg_polyline(points: Any, *, stroke: str, width: float, opacity: float = 1.0) -> str:
    value = " ".join(f"{x:.3f},{y:.3f}" for x, y in points)
    return (
        f'<polyline points="{value}" fill="none" stroke="{stroke}" '
        f'stroke-width="{width}" opacity="{opacity}" stroke-linejoin="round"/>'
    )


def _escape_xml(value: Any) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _round_float(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require(dependency: str, module_name: str) -> Any:
    from .dependencies import OptionalDependencyUnavailable, require_optional_dependency

    try:
        return require_optional_dependency(dependency, module_name=module_name, install_extra="analysis")
    except OptionalDependencyUnavailable as exc:
        details = exc.to_dict()
        raise DropWallError(
            "drop_wall_dependency_missing",
            f"Missing optional dependency for drop-wall detection: {details.get('module', module_name)}",
        ) from exc
