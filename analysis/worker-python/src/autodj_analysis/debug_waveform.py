"""High-resolution RGB waveform artifacts for manual analysis debugging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math
from pathlib import Path
from typing import Any

from .audio_io import DecodedAudio
from .cache import SCHEMA_VERSION, write_json_atomic
from .dependencies import OptionalDependencyUnavailable, require_optional_dependency


DEFAULT_DEBUG_WAVEFORM_POINT_COUNT = 32_768
DEFAULT_DEBUG_LOW_CUTOFF_HZ = 180.0
DEFAULT_DEBUG_HIGH_CUTOFF_HZ = 2_000.0
DEBUG_WAVEFORM_MODE_RGB_BANDS = "rgb-band-transient"
NEAR_ZERO = 1e-8


class DebugWaveformError(ValueError):
    """Expected debug waveform construction failure."""

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
class DebugWaveform:
    points: tuple[dict[str, float], ...]
    peak: float
    rms: float
    sample_rate: int
    duration_seconds: float


def compute_debug_waveform(
    decoded_audio: DecodedAudio,
    *,
    target_point_count: int = DEFAULT_DEBUG_WAVEFORM_POINT_COUNT,
    low_cutoff_hz: float = DEFAULT_DEBUG_LOW_CUTOFF_HZ,
    high_cutoff_hz: float = DEFAULT_DEBUG_HIGH_CUTOFF_HZ,
) -> DebugWaveform:
    """Compute high-resolution peak, band-energy, and transient debug points."""

    _validate_debug_waveform_parameters(
        decoded_audio,
        target_point_count=target_point_count,
        low_cutoff_hz=low_cutoff_hz,
        high_cutoff_hz=high_cutoff_hz,
    )
    numpy = _require_debug_dependency("numpy", module_name="numpy")
    scipy_signal = _require_debug_dependency("scipy", module_name="scipy.signal")

    samples = numpy.asarray(decoded_audio.samples, dtype=numpy.float32).reshape(-1)
    if samples.size == 0:
        raise DebugWaveformError("debug_waveform_empty_audio", "Decoded audio contains no samples")

    low_samples, mid_samples, high_samples = _split_frequency_bands(
        samples,
        numpy=numpy,
        scipy_signal=scipy_signal,
        sample_rate=decoded_audio.sample_rate,
        low_cutoff_hz=low_cutoff_hz,
        high_cutoff_hz=high_cutoff_hz,
    )
    point_count = min(target_point_count, int(samples.size))
    raw_points = _window_band_stats(
        samples,
        low_samples,
        mid_samples,
        high_samples,
        numpy=numpy,
        sample_rate=decoded_audio.sample_rate,
        point_count=point_count,
    )

    peak = max((max(abs(point["min"]), abs(point["max"])) for point in raw_points), default=0.0)
    rms_peak = max((point["rms"] for point in raw_points), default=0.0)
    band_peak = max(
        (
            max(point["low"], point["mid"], point["high"])
            for point in raw_points
        ),
        default=0.0,
    )
    transient_values = _transient_values(raw_points)
    transient_peak = max(transient_values, default=0.0)

    normalized_points: list[dict[str, float]] = []
    for index, point in enumerate(raw_points):
        normalized_points.append(
            {
                "timeSeconds": _round_float(point["timeSeconds"]),
                "min": _round_float(point["min"]),
                "max": _round_float(point["max"]),
                "rms": _round_float(_normalize(point["rms"], rms_peak)),
                "low": _round_float(_normalize(point["low"], band_peak)),
                "mid": _round_float(_normalize(point["mid"], band_peak)),
                "high": _round_float(_normalize(point["high"], band_peak)),
                "transient": _round_float(_normalize(transient_values[index], transient_peak)),
            }
        )

    return DebugWaveform(
        points=tuple(normalized_points),
        peak=_round_float(peak),
        rms=_round_float(_full_rms(samples, numpy=numpy)),
        sample_rate=decoded_audio.sample_rate,
        duration_seconds=_round_float(decoded_audio.duration_seconds),
    )


def build_debug_waveform_artifact(
    track_id: str,
    decoded_audio: DecodedAudio,
    *,
    analyzer_producer: str = "autodj_analysis.debug_waveform",
    analyzer_version: str,
    created_at_utc: str | None = None,
    target_point_count: int = DEFAULT_DEBUG_WAVEFORM_POINT_COUNT,
    low_cutoff_hz: float = DEFAULT_DEBUG_LOW_CUTOFF_HZ,
    high_cutoff_hz: float = DEFAULT_DEBUG_HIGH_CUTOFF_HZ,
) -> dict[str, Any]:
    """Build a local debug-only RGB waveform artifact."""

    waveform = compute_debug_waveform(
        decoded_audio,
        target_point_count=target_point_count,
        low_cutoff_hz=low_cutoff_hz,
        high_cutoff_hz=high_cutoff_hz,
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "debug-waveform",
        "trackId": track_id,
        "analyzer": {
            "producer": analyzer_producer,
            "producerVersion": analyzer_version,
            "createdAtUtc": created_at_utc or _utc_now_iso(),
        },
        "durationSeconds": waveform.duration_seconds,
        "sampleRate": waveform.sample_rate,
        "parameters": {
            "targetPointCount": target_point_count,
            "mode": DEBUG_WAVEFORM_MODE_RGB_BANDS,
            "lowCutoffHz": float(low_cutoff_hz),
            "highCutoffHz": float(high_cutoff_hz),
        },
        "summary": {
            "peak": waveform.peak,
            "rms": waveform.rms,
        },
        "points": [dict(point) for point in waveform.points],
    }


def write_debug_waveform_artifact(destination: str | Path, artifact: dict[str, Any]) -> Path:
    """Write a debug waveform artifact to an explicit JSON path."""

    return write_json_atomic(destination, artifact)


def _validate_debug_waveform_parameters(
    decoded_audio: DecodedAudio,
    *,
    target_point_count: int,
    low_cutoff_hz: float,
    high_cutoff_hz: float,
) -> None:
    if decoded_audio.sample_rate <= 0:
        raise DebugWaveformError(
            "debug_waveform_invalid_audio",
            "Decoded audio sample_rate must be greater than zero",
        )
    if target_point_count <= 0:
        raise DebugWaveformError(
            "debug_waveform_invalid_parameters",
            "target_point_count must be greater than zero",
        )
    nyquist = decoded_audio.sample_rate / 2.0
    if low_cutoff_hz <= 0 or low_cutoff_hz >= nyquist:
        raise DebugWaveformError(
            "debug_waveform_invalid_parameters",
            "low_cutoff_hz must be greater than zero and below the Nyquist frequency",
        )
    if high_cutoff_hz <= low_cutoff_hz or high_cutoff_hz >= nyquist:
        raise DebugWaveformError(
            "debug_waveform_invalid_parameters",
            "high_cutoff_hz must be greater than low_cutoff_hz and below the Nyquist frequency",
        )


def _split_frequency_bands(
    samples: Any,
    *,
    numpy: Any,
    scipy_signal: Any,
    sample_rate: int,
    low_cutoff_hz: float,
    high_cutoff_hz: float,
) -> tuple[Any, Any, Any]:
    nyquist = sample_rate / 2.0
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


def _window_band_stats(
    samples: Any,
    low_samples: Any,
    mid_samples: Any,
    high_samples: Any,
    *,
    numpy: Any,
    sample_rate: int,
    point_count: int,
) -> list[dict[str, float]]:
    sample_count = int(samples.size)
    points: list[dict[str, float]] = []

    for point_index in range(point_count):
        start = math.floor(point_index * sample_count / point_count)
        end = math.floor((point_index + 1) * sample_count / point_count)
        if end <= start:
            end = start + 1

        full = samples[start:end]
        low = low_samples[start:end]
        mid = mid_samples[start:end]
        high = high_samples[start:end]
        points.append(
            {
                "timeSeconds": start / float(sample_rate),
                "min": float(full.min()) if full.size else 0.0,
                "max": float(full.max()) if full.size else 0.0,
                "rms": _full_rms(full, numpy=numpy),
                "low": _full_rms(low, numpy=numpy),
                "mid": _full_rms(mid, numpy=numpy),
                "high": _full_rms(high, numpy=numpy),
            }
        )

    return points


def _transient_values(points: list[dict[str, float]]) -> list[float]:
    values: list[float] = []
    previous_energy = 0.0
    for point in points:
        energy = point["rms"] + 0.65 * point["mid"] + 0.85 * point["high"]
        values.append(max(0.0, energy - previous_energy))
        previous_energy = energy
    return values


def _full_rms(values: Any, *, numpy: Any) -> float:
    if values.size == 0:
        return 0.0
    return math.sqrt(float(numpy.mean(values * values)))


def _normalize(value: float, peak: float) -> float:
    if peak <= NEAR_ZERO:
        return 0.0
    return min(1.0, max(0.0, value / peak))


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_debug_dependency(dependency: str, *, module_name: str) -> Any:
    try:
        return require_optional_dependency(
            dependency,
            module_name=module_name,
            install_extra="analysis",
        )
    except OptionalDependencyUnavailable as exc:
        details = exc.to_dict()
        raise DebugWaveformError(
            "debug_waveform_dependency_missing",
            details["message"],
            dependency=details.get("dependency"),
        ) from None
