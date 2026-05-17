"""Tempo normalization and beat-grid feature extraction."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .audio_io import DecodedAudio
from .dependencies import OptionalDependencyUnavailable, require_optional_dependency


DEFAULT_TEMPO_HOP_LENGTH = 512
DEFAULT_TEMPO_START_BPM = 140.0
DEFAULT_MIN_TEMPO_BPM = 50.0
DEFAULT_MAX_TEMPO_BPM = 220.0
FALLBACK_DUBSTEP_BPM = 140.0
NEAR_SILENCE_PEAK = 1e-4
ELECTRONIC_GRID_QUANTIZATION_BPM = 0.5
ELECTRONIC_GRID_ANCHOR_STEP_SECONDS = 0.005
ELECTRONIC_GRID_REFINEMENT_HOP_LENGTH = 256
ELECTRONIC_GRID_FINE_REFINEMENT_HOP_LENGTH = 128
ELECTRONIC_GRID_REFINEMENT_WINDOW_SECONDS = 0.035
ELECTRONIC_GRID_REFINEMENT_STEP_SECONDS = 0.001
ELECTRONIC_GRID_ONSET_TOLERANCE_SECONDS = 0.060
ELECTRONIC_GRID_REFINEMENT_ONSET_TOLERANCE_SECONDS = 0.050
ELECTRONIC_GRID_STRONG_ONSET_QUANTILE = 0.55
ELECTRONIC_GRID_ZERO_WRAP_TOLERANCE_SECONDS = 0.060
MIN_ELECTRONIC_GRID_SCORE = 0.070


class TempoExtractionError(ValueError):
    """Expected tempo extraction failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        dependency: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.dependency = dependency

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.dependency is not None:
            payload["dependency"] = self.dependency
        return payload


@dataclass(frozen=True)
class NormalizedTempo:
    bpm: float
    normalized_bpm: float
    tempo_class: str
    confidence_multiplier: float
    warning: str | None = None


@dataclass(frozen=True)
class TempoFeatures:
    bpm: float
    normalized_bpm: float
    confidence: float
    tempo_class: str
    candidates: tuple[dict[str, float | str], ...]
    beats: tuple[dict[str, float | int], ...]
    downbeats: tuple[dict[str, float | int], ...]
    beat_grid_confidence: float
    warnings: tuple[str, ...]
    backend: str
    hop_length: int


@dataclass(frozen=True)
class _TempoCandidate:
    name: str
    bpm: float
    confidence: float
    beat_times: tuple[float, ...] = ()


def normalize_dubstep_bpm(bpm: float) -> NormalizedTempo:
    """Normalize raw BPM into the dubstep 70/140 reasoning space."""

    if bpm <= 0:
        raise TempoExtractionError("tempo_invalid_bpm", "bpm must be greater than zero")

    if 65.0 <= bpm < 95.0:
        return NormalizedTempo(
            bpm=_round_float(bpm),
            normalized_bpm=_round_float(bpm * 2.0),
            tempo_class="halftime",
            confidence_multiplier=1.0,
        )
    if 130.0 <= bpm <= 190.0:
        return NormalizedTempo(
            bpm=_round_float(bpm),
            normalized_bpm=_round_float(bpm),
            tempo_class="straight",
            confidence_multiplier=1.0,
        )
    if 95.0 <= bpm < 130.0:
        return NormalizedTempo(
            bpm=_round_float(bpm),
            normalized_bpm=_round_float(bpm),
            tempo_class="straight",
            confidence_multiplier=0.85,
            warning="Tempo is outside the preferred dubstep 70/140 range; normalization confidence is reduced.",
        )

    normalized = _closest_dubstep_related_bpm(bpm)
    return NormalizedTempo(
        bpm=_round_float(bpm),
        normalized_bpm=_round_float(normalized),
        tempo_class=_tempo_class_for_adjustment(bpm, normalized),
        confidence_multiplier=0.55,
        warning=(
            f"Tempo {bpm:.3f} BPM is outside the dubstep normalization bands; "
            f"using related value {normalized:.3f} BPM with low confidence."
        ),
    )


def compute_tempo_features(
    decoded_audio: DecodedAudio,
    *,
    hop_length: int = DEFAULT_TEMPO_HOP_LENGTH,
    start_bpm: float = DEFAULT_TEMPO_START_BPM,
    min_tempo_bpm: float = DEFAULT_MIN_TEMPO_BPM,
    max_tempo_bpm: float = DEFAULT_MAX_TEMPO_BPM,
) -> TempoFeatures:
    """Estimate BPM and a stable beat grid from decoded mono audio."""

    _validate_tempo_parameters(
        decoded_audio,
        hop_length=hop_length,
        start_bpm=start_bpm,
        min_tempo_bpm=min_tempo_bpm,
        max_tempo_bpm=max_tempo_bpm,
    )
    numpy = _require_tempo_dependency("numpy", module_name="numpy")
    librosa = _require_tempo_dependency("librosa", module_name="librosa")

    samples = numpy.asarray(decoded_audio.samples, dtype=numpy.float32).reshape(-1)
    if samples.size == 0:
        raise TempoExtractionError("tempo_empty_audio", "Decoded audio contains no samples")

    peak = float(numpy.max(numpy.abs(samples))) if samples.size else 0.0
    if peak <= NEAR_SILENCE_PEAK:
        return _weak_tempo_features(
            hop_length=hop_length,
            warning="Tempo and beat grid are low confidence because the decoded audio is near silence.",
        )

    onset_envelope = librosa.onset.onset_strength(
        y=samples,
        sr=decoded_audio.sample_rate,
        hop_length=hop_length,
    )
    onset_envelope = numpy.asarray(onset_envelope, dtype=numpy.float32)
    if onset_envelope.size == 0 or float(onset_envelope.max()) <= NEAR_SILENCE_PEAK:
        return _weak_tempo_features(
            hop_length=hop_length,
            warning="Tempo and beat grid are low confidence because onset strength is weak.",
        )

    start_transient = _has_start_transient(samples, numpy=numpy, sample_rate=decoded_audio.sample_rate)
    candidates = tuple(
        candidate
        for candidate in (
            _quantized_electronic_grid_candidate(
                librosa,
                numpy=numpy,
                onset_envelope=onset_envelope,
                sample_rate=decoded_audio.sample_rate,
                hop_length=hop_length,
                duration_seconds=decoded_audio.duration_seconds,
                min_tempo_bpm=min_tempo_bpm,
                max_tempo_bpm=max_tempo_bpm,
                samples=samples,
            ),
            _sample_transient_candidate(
                numpy,
                samples=samples,
                sample_rate=decoded_audio.sample_rate,
                min_tempo_bpm=min_tempo_bpm,
                max_tempo_bpm=max_tempo_bpm,
            ),
            _librosa_beat_candidate(
                librosa,
                onset_envelope=onset_envelope,
                sample_rate=decoded_audio.sample_rate,
                hop_length=hop_length,
                start_bpm=start_bpm,
            ),
            _onset_interval_candidate(
                librosa,
                numpy=numpy,
                onset_envelope=onset_envelope,
                sample_rate=decoded_audio.sample_rate,
                hop_length=hop_length,
                min_tempo_bpm=min_tempo_bpm,
                max_tempo_bpm=max_tempo_bpm,
                start_transient=start_transient,
            ),
        )
        if candidate is not None
    )
    if not candidates:
        return _weak_tempo_features(
            hop_length=hop_length,
            warning="Tempo and beat grid are low confidence because no plausible tempo candidates were found.",
        )

    best = max(candidates, key=lambda candidate: candidate.confidence)
    normalized = normalize_dubstep_bpm(best.bpm)
    warnings: list[str] = []
    if normalized.warning is not None:
        warnings.append(normalized.warning)
    warnings.append("Downbeats were not emitted because phrase/downbeat evidence is not yet defensible.")

    confidence = _round_float(_clamp(best.confidence * normalized.confidence_multiplier))
    beat_grid_confidence = _round_float(_clamp(_beat_grid_confidence(best.beat_times, best.confidence)))
    beats = _build_beat_markers(
        best,
        samples=samples,
        numpy=numpy,
        sample_rate=decoded_audio.sample_rate,
        duration_seconds=decoded_audio.duration_seconds,
        confidence=beat_grid_confidence,
        start_transient=start_transient,
        grid_bpm=normalized.normalized_bpm,
    )

    if len(beats) < 4:
        beat_grid_confidence = min(beat_grid_confidence, 0.3)
        warnings.append("Beat grid is low confidence because too few beat markers were detected.")

    return TempoFeatures(
        bpm=normalized.bpm,
        normalized_bpm=normalized.normalized_bpm,
        confidence=confidence,
        tempo_class=normalized.tempo_class,
        candidates=tuple(_candidate_to_dict(candidate) for candidate in candidates),
        beats=tuple(beats),
        downbeats=(),
        beat_grid_confidence=beat_grid_confidence,
        warnings=tuple(warnings),
        backend=best.name,
        hop_length=hop_length,
    )


def build_tempo_analysis(features: TempoFeatures) -> dict[str, Any]:
    """Convert tempo features to the AnalyzedTrack tempo shape."""

    return {
        "bpm": features.bpm,
        "normalizedBpm": features.normalized_bpm,
        "confidence": features.confidence,
        "tempoClass": features.tempo_class,
        "candidates": [dict(candidate) for candidate in features.candidates],
    }


def build_beat_grid(features: TempoFeatures) -> dict[str, Any]:
    """Convert tempo features to the AnalyzedTrack beatGrid shape."""

    return {
        "beats": [dict(beat) for beat in features.beats],
        "downbeats": [dict(downbeat) for downbeat in features.downbeats],
        "confidence": features.beat_grid_confidence,
    }


def _validate_tempo_parameters(
    decoded_audio: DecodedAudio,
    *,
    hop_length: int,
    start_bpm: float,
    min_tempo_bpm: float,
    max_tempo_bpm: float,
) -> None:
    if decoded_audio.sample_rate <= 0:
        raise TempoExtractionError(
            "tempo_invalid_audio",
            "Decoded audio sample_rate must be greater than zero",
        )
    if hop_length <= 0:
        raise TempoExtractionError("tempo_invalid_parameters", "hop_length must be greater than zero")
    if start_bpm <= 0:
        raise TempoExtractionError("tempo_invalid_parameters", "start_bpm must be greater than zero")
    if min_tempo_bpm <= 0 or max_tempo_bpm <= min_tempo_bpm:
        raise TempoExtractionError(
            "tempo_invalid_parameters",
            "Tempo range must be positive and max_tempo_bpm must exceed min_tempo_bpm",
        )


def _librosa_beat_candidate(
    librosa: Any,
    *,
    onset_envelope: Any,
    sample_rate: int,
    hop_length: int,
    start_bpm: float,
) -> _TempoCandidate | None:
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_envelope,
        sr=sample_rate,
        hop_length=hop_length,
        start_bpm=start_bpm,
        trim=False,
    )
    bpm = _scalar_float(tempo)
    if bpm <= 0:
        return None

    beat_times = tuple(
        _round_float(float(time_seconds))
        for time_seconds in librosa.frames_to_time(beat_frames, sr=sample_rate, hop_length=hop_length)
    )
    confidence = _sequence_confidence(beat_times)
    return _TempoCandidate(
        name="librosa.beat_track",
        bpm=_round_float(bpm),
        confidence=min(confidence, 0.82),
        beat_times=beat_times,
    )


def _onset_interval_candidate(
    librosa: Any,
    *,
    numpy: Any,
    onset_envelope: Any,
    sample_rate: int,
    hop_length: int,
    min_tempo_bpm: float,
    max_tempo_bpm: float,
    start_transient: bool,
) -> _TempoCandidate | None:
    onset_times = tuple(
        _round_float(float(time_seconds))
        for time_seconds in librosa.onset.onset_detect(
            onset_envelope=onset_envelope,
            sr=sample_rate,
            hop_length=hop_length,
            units="time",
            backtrack=False,
        )
    )
    if start_transient and (not onset_times or onset_times[0] > 0.1):
        onset_times = (0.0, *onset_times)
    if len(onset_times) < 4:
        return None

    intervals = [
        later - earlier
        for earlier, later in zip(onset_times, onset_times[1:])
        if later > earlier
    ]
    min_interval = 60.0 / max_tempo_bpm
    max_interval = 60.0 / min_tempo_bpm
    plausible_intervals = [interval for interval in intervals if min_interval <= interval <= max_interval]
    if len(plausible_intervals) < 3:
        return None

    median_interval = float(numpy.median(numpy.asarray(plausible_intervals, dtype=numpy.float32)))
    if median_interval <= 0:
        return None

    bpm = 60.0 / median_interval
    confidence = _sequence_confidence(onset_times)
    return _TempoCandidate(
        name="librosa.onset_interval",
        bpm=_round_float(bpm),
        confidence=min(confidence, 0.68),
        beat_times=onset_times,
    )


def _quantized_electronic_grid_candidate(
    librosa: Any,
    *,
    numpy: Any,
    onset_envelope: Any,
    sample_rate: int,
    hop_length: int,
    duration_seconds: float,
    min_tempo_bpm: float,
    max_tempo_bpm: float,
    samples: Any,
) -> _TempoCandidate | None:
    """Score whole/half-BPM beat grids against onset strength for electronic music."""

    if duration_seconds <= 0:
        return None

    envelope = numpy.asarray(onset_envelope, dtype=numpy.float32)
    if envelope.size < 4:
        return None
    envelope_min = float(envelope.min())
    envelope_peak = float(envelope.max() - envelope_min)
    if envelope_peak <= NEAR_SILENCE_PEAK:
        return None
    normalized = (envelope - envelope_min) / envelope_peak
    local_strength = _local_maximum_3(normalized, numpy=numpy)

    onset_times = numpy.asarray(
        librosa.onset.onset_detect(
            onset_envelope=envelope,
            sr=sample_rate,
            hop_length=hop_length,
            units="time",
            backtrack=False,
        ),
        dtype=numpy.float32,
    )
    if onset_times.size < 4:
        return None

    best: tuple[float, float, float, float, tuple[float, ...]] | None = None
    for bpm in _electronic_bpm_values(min_tempo_bpm, max_tempo_bpm):
        period_seconds = 60.0 / bpm
        if period_seconds <= 0:
            continue

        anchor = 0.0
        while anchor < period_seconds:
            beat_times = numpy.arange(anchor, duration_seconds + 1e-9, period_seconds, dtype=numpy.float32)
            if beat_times.size >= 4:
                score = _grid_score(
                    beat_times,
                    local_strength,
                    onset_times,
                    numpy=numpy,
                    sample_rate=sample_rate,
                    hop_length=hop_length,
                )
                selection_score = score * _electronic_tempo_preference(bpm)
                if best is None or selection_score > best[0]:
                    best = (
                        selection_score,
                        score,
                        bpm,
                        anchor,
                        tuple(_round_float(float(time)) for time in beat_times),
                    )
            anchor += ELECTRONIC_GRID_ANCHOR_STEP_SECONDS

    if best is None or best[1] < MIN_ELECTRONIC_GRID_SCORE:
        return None

    _selection_score, score, bpm, anchor, _beat_times_tuple = best
    refined_anchor = _refine_electronic_grid_anchor(
        librosa,
        numpy=numpy,
        samples=samples,
        sample_rate=sample_rate,
        bpm=bpm,
        anchor=anchor,
        duration_seconds=duration_seconds,
    )
    period_seconds = 60.0 / bpm
    beat_times_tuple = tuple(
        _round_float(float(time))
        for time in numpy.arange(refined_anchor, duration_seconds + 1e-9, period_seconds, dtype=numpy.float32)
    )
    confidence = _round_float(_clamp(0.35 + 3.0 * score, ceiling=0.93))
    return _TempoCandidate(
        name="electronic_quantized_grid",
        bpm=_round_float(bpm),
        confidence=confidence,
        beat_times=beat_times_tuple,
    )


def _sample_transient_candidate(
    numpy: Any,
    *,
    samples: Any,
    sample_rate: int,
    min_tempo_bpm: float,
    max_tempo_bpm: float,
) -> _TempoCandidate | None:
    absolute_samples = numpy.abs(samples)
    peak = float(absolute_samples.max()) if absolute_samples.size else 0.0
    if peak <= NEAR_SILENCE_PEAK:
        return None

    threshold = peak * 0.5
    min_gap_samples = max(1, round(sample_rate * (60.0 / max_tempo_bpm) * 0.75))
    event_times: list[float] = []
    sample_index = 0
    while sample_index < absolute_samples.size:
        if float(absolute_samples[sample_index]) >= threshold:
            event_times.append(_round_float(sample_index / sample_rate))
            sample_index += min_gap_samples
        else:
            sample_index += 1

    if len(event_times) < 4:
        return None

    intervals = [
        later - earlier
        for earlier, later in zip(event_times, event_times[1:])
        if later > earlier
    ]
    min_interval = 60.0 / max_tempo_bpm
    max_interval = 60.0 / min_tempo_bpm
    plausible_intervals = [interval for interval in intervals if min_interval <= interval <= max_interval]
    if len(plausible_intervals) < 3:
        return None

    median_interval = float(numpy.median(numpy.asarray(plausible_intervals, dtype=numpy.float32)))
    if median_interval <= 0:
        return None

    return _TempoCandidate(
        name="sample_transient_interval",
        bpm=_round_float(60.0 / median_interval),
        confidence=min(_sequence_confidence(tuple(event_times)), 0.72),
        beat_times=tuple(event_times),
    )


def _electronic_bpm_values(min_tempo_bpm: float, max_tempo_bpm: float) -> tuple[float, ...]:
    ranges = ((65.0, 95.0), (130.0, 190.0))
    values: list[float] = []
    for lower, upper in ranges:
        start = max(lower, min_tempo_bpm)
        end = min(upper, max_tempo_bpm)
        if start > end:
            continue
        value = math.ceil(start / ELECTRONIC_GRID_QUANTIZATION_BPM) * ELECTRONIC_GRID_QUANTIZATION_BPM
        while value <= end + 1e-9:
            values.append(_round_float(value))
            value += ELECTRONIC_GRID_QUANTIZATION_BPM
    return tuple(values)


def _electronic_tempo_preference(bpm: float) -> float:
    if 130.0 <= bpm <= 190.0:
        return 1.12
    return 1.0


def _refine_electronic_grid_anchor(
    librosa: Any,
    *,
    numpy: Any,
    samples: Any,
    sample_rate: int,
    bpm: float,
    anchor: float,
    duration_seconds: float,
) -> float:
    period_seconds = 60.0 / bpm
    if period_seconds <= 0 or duration_seconds <= 0:
        return _round_float(anchor)

    candidates = [
        _refined_anchor_candidate(
            librosa,
            numpy=numpy,
            samples=samples,
            sample_rate=sample_rate,
            bpm=bpm,
            anchor=anchor,
            duration_seconds=duration_seconds,
            hop_length=ELECTRONIC_GRID_FINE_REFINEMENT_HOP_LENGTH,
            strong_onsets=False,
            score_mode="grid",
        ),
        _refined_anchor_candidate(
            librosa,
            numpy=numpy,
            samples=samples,
            sample_rate=sample_rate,
            bpm=bpm,
            anchor=anchor,
            duration_seconds=duration_seconds,
            hop_length=ELECTRONIC_GRID_REFINEMENT_HOP_LENGTH,
            strong_onsets=True,
            score_mode="grid",
        ),
        _refined_anchor_candidate(
            librosa,
            numpy=numpy,
            samples=samples,
            sample_rate=sample_rate,
            bpm=bpm,
            anchor=anchor,
            duration_seconds=duration_seconds,
            hop_length=ELECTRONIC_GRID_REFINEMENT_HOP_LENGTH,
            strong_onsets=True,
            score_mode="phase",
        ),
    ]
    valid_candidates = [candidate for candidate in candidates if candidate is not None]
    if not valid_candidates:
        return _round_float(anchor)

    offsets = [
        _signed_anchor_offset(candidate, anchor, period_seconds)
        for candidate in valid_candidates
    ]
    return _round_float(_wrap_anchor(anchor + float(numpy.median(numpy.asarray(offsets))), period_seconds))


def _refined_anchor_candidate(
    librosa: Any,
    *,
    numpy: Any,
    samples: Any,
    sample_rate: int,
    bpm: float,
    anchor: float,
    duration_seconds: float,
    hop_length: int,
    strong_onsets: bool,
    score_mode: str,
) -> float | None:
    period_seconds = 60.0 / bpm
    try:
        onset_envelope = librosa.onset.onset_strength(
            y=samples,
            sr=sample_rate,
            hop_length=hop_length,
        )
    except Exception:
        return None

    envelope = numpy.asarray(onset_envelope, dtype=numpy.float32)
    if envelope.size < 4:
        return None
    envelope_min = float(envelope.min())
    envelope_peak = float(envelope.max() - envelope_min)
    if envelope_peak <= NEAR_SILENCE_PEAK:
        return None

    normalized = (envelope - envelope_min) / envelope_peak
    local_strength = _local_maximum_3(normalized, numpy=numpy)
    onset_frames = numpy.asarray(
        librosa.onset.onset_detect(
            onset_envelope=envelope,
            sr=sample_rate,
            hop_length=hop_length,
            units="frames",
            backtrack=False,
        ),
        dtype=numpy.int64,
    )
    if strong_onsets:
        onset_times = _strong_onset_times(
            onset_frames,
            normalized,
            librosa=librosa,
            numpy=numpy,
            sample_rate=sample_rate,
            hop_length=hop_length,
        )
    else:
        onset_times = numpy.asarray(
            librosa.frames_to_time(onset_frames, sr=sample_rate, hop_length=hop_length),
            dtype=numpy.float32,
        )
    if onset_times.size < 4:
        return None

    best_score = -1.0
    best_anchor = anchor
    offsets = numpy.arange(
        -ELECTRONIC_GRID_REFINEMENT_WINDOW_SECONDS,
        ELECTRONIC_GRID_REFINEMENT_WINDOW_SECONDS + ELECTRONIC_GRID_REFINEMENT_STEP_SECONDS / 2.0,
        ELECTRONIC_GRID_REFINEMENT_STEP_SECONDS,
        dtype=numpy.float32,
    )
    seen: set[float] = set()
    for offset in offsets:
        candidate_anchor = _wrap_anchor(float(anchor + offset), period_seconds)
        rounded_anchor = round(candidate_anchor, 6)
        if rounded_anchor in seen:
            continue
        seen.add(rounded_anchor)
        beat_times = numpy.arange(candidate_anchor, duration_seconds + 1e-9, period_seconds, dtype=numpy.float32)
        if beat_times.size < 4:
            continue
        score_fn = _refinement_grid_score if score_mode == "phase" else _grid_score
        score = score_fn(
            beat_times,
            local_strength,
            onset_times,
            numpy=numpy,
            sample_rate=sample_rate,
            hop_length=hop_length,
        )
        if score > best_score:
            best_score = score
            best_anchor = candidate_anchor

    return _round_float(best_anchor)


def _signed_anchor_offset(anchor: float, origin: float, period_seconds: float) -> float:
    offset = anchor - origin
    while offset <= -period_seconds / 2.0:
        offset += period_seconds
    while offset > period_seconds / 2.0:
        offset -= period_seconds
    return offset


def _wrap_anchor(anchor: float, period_seconds: float) -> float:
    while anchor < 0:
        anchor += period_seconds
    while anchor >= period_seconds:
        anchor -= period_seconds
    return anchor


def _strong_onset_times(
    onset_frames: Any,
    normalized_envelope: Any,
    *,
    librosa: Any,
    numpy: Any,
    sample_rate: int,
    hop_length: int,
) -> Any:
    if onset_frames.size == 0:
        return numpy.asarray((), dtype=numpy.float32)

    clipped_frames = numpy.clip(onset_frames, 0, normalized_envelope.size - 1)
    strengths = normalized_envelope[clipped_frames]
    if strengths.size >= 8:
        threshold = float(numpy.quantile(strengths, ELECTRONIC_GRID_STRONG_ONSET_QUANTILE))
        strong_mask = strengths >= threshold
        if int(strong_mask.sum()) >= 4:
            onset_frames = onset_frames[strong_mask]

    return numpy.asarray(
        librosa.frames_to_time(onset_frames, sr=sample_rate, hop_length=hop_length),
        dtype=numpy.float32,
    )


def _local_maximum_3(values: Any, *, numpy: Any) -> Any:
    if values.size < 3:
        return values
    padded = numpy.pad(values, (1, 1), mode="edge")
    return numpy.maximum.reduce((padded[:-2], padded[1:-1], padded[2:]))


def _grid_score(
    beat_times: Any,
    local_strength: Any,
    onset_times: Any,
    *,
    numpy: Any,
    sample_rate: int,
    hop_length: int,
) -> float:
    frame_indices = numpy.clip(
        numpy.rint(beat_times * sample_rate / hop_length).astype(numpy.int64),
        0,
        local_strength.size - 1,
    )
    strengths = local_strength[frame_indices]
    envelope_score = float(numpy.mean(strengths)) if strengths.size else 0.0
    upper_score = float(numpy.percentile(strengths, 75)) if strengths.size else 0.0
    distance_score = _onset_distance_score(beat_times, onset_times, numpy=numpy)
    density_score = min(float(beat_times.size) / 12.0, 1.0)
    score = 0.65 * envelope_score + 0.15 * upper_score + 0.20 * distance_score
    return _clamp(score * (0.85 + 0.15 * density_score))


def _refinement_grid_score(
    beat_times: Any,
    local_strength: Any,
    onset_times: Any,
    *,
    numpy: Any,
    sample_rate: int,
    hop_length: int,
) -> float:
    frame_indices = numpy.clip(
        numpy.rint(beat_times * sample_rate / hop_length).astype(numpy.int64),
        0,
        local_strength.size - 1,
    )
    strengths = local_strength[frame_indices]
    envelope_score = float(numpy.mean(strengths)) if strengths.size else 0.0
    distance_score = _onset_distance_score(
        beat_times,
        onset_times,
        numpy=numpy,
        tolerance_seconds=ELECTRONIC_GRID_REFINEMENT_ONSET_TOLERANCE_SECONDS,
    )
    return _clamp(0.50 * envelope_score + 0.50 * distance_score)


def _onset_distance_score(
    beat_times: Any,
    onset_times: Any,
    *,
    numpy: Any,
    tolerance_seconds: float = ELECTRONIC_GRID_ONSET_TOLERANCE_SECONDS,
) -> float:
    if onset_times.size == 0 or beat_times.size == 0:
        return 0.0

    positions = numpy.searchsorted(onset_times, beat_times)
    right = numpy.where(positions < onset_times.size, onset_times[numpy.clip(positions, 0, onset_times.size - 1)], numpy.inf)
    left_indices = numpy.clip(positions - 1, 0, onset_times.size - 1)
    left = numpy.where(positions > 0, onset_times[left_indices], numpy.inf)
    distances = numpy.minimum(numpy.abs(right - beat_times), numpy.abs(beat_times - left))
    scores = numpy.maximum(0.0, 1.0 - distances / tolerance_seconds)
    return float(numpy.mean(scores)) if scores.size else 0.0


def _build_beat_markers(
    candidate: _TempoCandidate,
    *,
    samples: Any,
    numpy: Any,
    sample_rate: int,
    duration_seconds: float,
    confidence: float,
    start_transient: bool,
    grid_bpm: float | None = None,
) -> tuple[dict[str, float | int], ...]:
    marker_bpm = grid_bpm or candidate.bpm
    period_seconds = 60.0 / marker_bpm
    if period_seconds <= 0:
        return ()

    anchor = _beat_anchor_seconds(
        candidate,
        samples=samples,
        numpy=numpy,
        sample_rate=sample_rate,
        start_transient=start_transient,
    )
    zero_wrap_tolerance = (
        ELECTRONIC_GRID_ONSET_TOLERANCE_SECONDS
        if start_transient
        else ELECTRONIC_GRID_ZERO_WRAP_TOLERANCE_SECONDS
    )
    while anchor - period_seconds >= 0:
        anchor -= period_seconds
    if anchor > period_seconds - zero_wrap_tolerance:
        anchor -= period_seconds
    if anchor < 0:
        anchor = 0.0 if abs(anchor) <= zero_wrap_tolerance else anchor + period_seconds

    beat_count = max(0, int(math.floor((duration_seconds - anchor + 1e-9) / period_seconds)) + 1)
    return tuple(
        {
            "index": index,
            "timeSeconds": _round_float(anchor + index * period_seconds),
            "confidence": confidence,
        }
        for index in range(beat_count)
        if anchor + index * period_seconds <= duration_seconds + 1e-6
    )


def _beat_anchor_seconds(
    candidate: _TempoCandidate,
    *,
    samples: Any,
    numpy: Any,
    sample_rate: int,
    start_transient: bool,
) -> float:
    if candidate.beat_times:
        return candidate.beat_times[0]
    if start_transient:
        return 0.0

    peak_index = int(numpy.argmax(numpy.abs(samples)))
    return peak_index / float(sample_rate)


def _has_start_transient(samples: Any, *, numpy: Any, sample_rate: int) -> bool:
    peak = float(numpy.max(numpy.abs(samples))) if samples.size else 0.0
    if peak <= NEAR_SILENCE_PEAK:
        return False
    window = samples[: max(1, round(sample_rate * 0.05))]
    return float(numpy.max(numpy.abs(window))) >= peak * 0.5


def _sequence_confidence(times: tuple[float, ...]) -> float:
    if len(times) < 4:
        return 0.2

    intervals = [later - earlier for earlier, later in zip(times, times[1:]) if later > earlier]
    if len(intervals) < 3:
        return 0.2

    median_interval = _median(intervals)
    if median_interval <= 0:
        return 0.2
    median_error = _median([abs(interval - median_interval) for interval in intervals])
    regularity = 1.0 - min(median_error / (median_interval * 0.2), 1.0)
    count_score = min(len(times) / 8.0, 1.0)
    return _round_float(_clamp(0.25 + 0.55 * regularity + 0.20 * count_score))


def _beat_grid_confidence(beat_times: tuple[float, ...], tempo_confidence: float) -> float:
    if len(beat_times) < 4:
        return min(tempo_confidence, 0.3)
    return min(tempo_confidence, _sequence_confidence(beat_times))


def _weak_tempo_features(*, hop_length: int, warning: str) -> TempoFeatures:
    return TempoFeatures(
        bpm=FALLBACK_DUBSTEP_BPM,
        normalized_bpm=FALLBACK_DUBSTEP_BPM,
        confidence=0.0,
        tempo_class="straight",
        candidates=(),
        beats=(),
        downbeats=(),
        beat_grid_confidence=0.0,
        warnings=(
            warning,
            "Downbeats were not emitted because phrase/downbeat evidence is not yet defensible.",
        ),
        backend="fallback",
        hop_length=hop_length,
    )


def _candidate_to_dict(candidate: _TempoCandidate) -> dict[str, float | str]:
    return {
        "bpm": candidate.bpm,
        "confidence": candidate.confidence,
        "backend": candidate.name,
    }


def _closest_dubstep_related_bpm(bpm: float) -> float:
    candidates = [bpm, bpm * 2.0, bpm / 2.0, bpm * 4.0, bpm / 4.0]
    plausible = [candidate for candidate in candidates if 65.0 <= candidate <= 190.0]
    if not plausible:
        return FALLBACK_DUBSTEP_BPM
    return min(plausible, key=lambda candidate: abs(candidate - FALLBACK_DUBSTEP_BPM))


def _tempo_class_for_adjustment(bpm: float, normalized_bpm: float) -> str:
    if normalized_bpm > bpm * 1.5:
        return "halftime"
    if normalized_bpm < bpm * 0.75:
        return "doubletime"
    return "straight"


def _require_tempo_dependency(dependency: str, *, module_name: str) -> Any:
    try:
        return require_optional_dependency(
            dependency,
            module_name=module_name,
            install_extra="analysis",
        )
    except OptionalDependencyUnavailable as exc:
        details = exc.to_dict()
        raise TempoExtractionError(
            "tempo_dependency_missing",
            details["message"],
            dependency=details["dependency"],
        ) from None


def _scalar_float(value: Any) -> float:
    if hasattr(value, "item"):
        return float(value.item())
    try:
        return float(value[0])
    except (TypeError, IndexError):
        return float(value)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _clamp(value: float, *, ceiling: float = 1.0) -> float:
    return min(ceiling, max(0.0, value))


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded
