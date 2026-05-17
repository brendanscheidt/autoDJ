"""Waveform overview artifact construction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math
from pathlib import Path
from typing import Any

from .audio_io import DecodedAudio
from .cache import SCHEMA_VERSION, waveform_path, write_json_atomic


DEFAULT_WAVEFORM_POINT_COUNT = 1024
WAVEFORM_MODE_PEAK_RMS = "peak-rms"


class WaveformError(ValueError):
    """Expected waveform construction failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class WaveformOverview:
    points: tuple[dict[str, float], ...]
    peak: float
    rms: float
    sample_rate: int
    duration_seconds: float


def compute_waveform_overview(
    decoded_audio: DecodedAudio,
    *,
    target_point_count: int = DEFAULT_WAVEFORM_POINT_COUNT,
    mode: str = WAVEFORM_MODE_PEAK_RMS,
) -> WaveformOverview:
    """Compute stable peak/RMS waveform points from decoded mono audio."""

    if target_point_count <= 0:
        raise WaveformError(
            "waveform_invalid_parameters",
            "target_point_count must be greater than zero",
        )
    if mode != WAVEFORM_MODE_PEAK_RMS:
        raise WaveformError(
            "waveform_invalid_parameters",
            f"Unsupported waveform mode: {mode!r}",
        )
    if decoded_audio.sample_rate <= 0:
        raise WaveformError(
            "waveform_invalid_audio",
            "Decoded audio sample_rate must be greater than zero",
        )

    sample_count = _sample_count(decoded_audio.samples)
    if sample_count == 0:
        raise WaveformError("waveform_empty_audio", "Decoded audio contains no samples")

    point_count = min(target_point_count, sample_count)
    summary = _sample_window_stats(decoded_audio.samples, 0, sample_count)
    points: list[dict[str, float]] = []

    for point_index in range(point_count):
        start = math.floor(point_index * sample_count / point_count)
        end = math.floor((point_index + 1) * sample_count / point_count)
        if end <= start:
            end = start + 1

        stats = _sample_window_stats(decoded_audio.samples, start, end)
        points.append(
            {
                "timeSeconds": _round_float(start / decoded_audio.sample_rate),
                "min": _round_float(stats["min"]),
                "max": _round_float(stats["max"]),
                "rms": _round_float(stats["rms"]),
            }
        )

    return WaveformOverview(
        points=tuple(points),
        peak=_round_float(max(abs(summary["min"]), abs(summary["max"]))),
        rms=_round_float(summary["rms"]),
        sample_rate=decoded_audio.sample_rate,
        duration_seconds=_round_float(decoded_audio.duration_seconds),
    )


def build_waveform_artifact(
    track_id: str,
    decoded_audio: DecodedAudio,
    *,
    analyzer_producer: str,
    analyzer_version: str,
    source_content_hash: str,
    parameters_hash: str,
    created_at_utc: str | None = None,
    target_point_count: int = DEFAULT_WAVEFORM_POINT_COUNT,
    mode: str = WAVEFORM_MODE_PEAK_RMS,
) -> dict[str, Any]:
    """Build the plain cached waveform artifact for a decoded track."""

    if not source_content_hash:
        raise WaveformError(
            "waveform_source_content_hash_missing",
            "Waveform artifacts require a source content hash",
        )
    if not parameters_hash:
        raise WaveformError(
            "waveform_parameters_hash_missing",
            "Waveform artifacts require an analyzer parameters hash",
        )

    overview = compute_waveform_overview(
        decoded_audio,
        target_point_count=target_point_count,
        mode=mode,
    )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "trackId": track_id,
        "analyzer": {
            "producer": analyzer_producer,
            "producerVersion": analyzer_version,
            "createdAtUtc": created_at_utc or _utc_now_iso(),
            "sourceContentHash": source_content_hash,
            "parametersHash": parameters_hash,
        },
        "durationSeconds": overview.duration_seconds,
        "sampleRate": overview.sample_rate,
        "parameters": {
            "targetPointCount": target_point_count,
            "mode": mode,
        },
        "summary": {
            "peak": overview.peak,
            "rms": overview.rms,
        },
        "points": [dict(point) for point in overview.points],
    }


def write_waveform_artifact(
    cache_root: str | Path,
    track_id: str,
    artifact: dict[str, Any],
) -> Path:
    """Write `<cache-root>/tracks/<track-id>/waveform.json` atomically."""

    return write_json_atomic(waveform_path(cache_root, track_id), artifact)


def _sample_count(samples: Any) -> int:
    try:
        return int(len(samples))
    except TypeError as exc:
        raise WaveformError(
            "waveform_invalid_audio",
            "Decoded audio samples must be a sized sequence",
        ) from exc


def _sample_window_stats(samples: Any, start: int, end: int) -> dict[str, float]:
    try:
        window = samples[start:end]
        minimum = float(window.min())
        maximum = float(window.max())
        mean_square = float((window * window).mean())
        return {
            "min": minimum,
            "max": maximum,
            "rms": math.sqrt(mean_square),
        }
    except (AttributeError, TypeError, ValueError):
        pass

    minimum = math.inf
    maximum = -math.inf
    square_sum = 0.0
    count = 0

    for sample_index in range(start, end):
        value = float(samples[sample_index])
        minimum = min(minimum, value)
        maximum = max(maximum, value)
        square_sum += value * value
        count += 1

    if count == 0:
        raise WaveformError("waveform_empty_audio", "Decoded audio contains no samples")

    return {
        "min": minimum,
        "max": maximum,
        "rms": math.sqrt(square_sum / count),
    }


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
