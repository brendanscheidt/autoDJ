"""Signal feature extraction helpers for analyzed-track artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .audio_io import DecodedAudio
from .dependencies import OptionalDependencyUnavailable, require_optional_dependency


DEFAULT_FEATURE_FRAME_LENGTH = 2048
DEFAULT_FEATURE_HOP_LENGTH = 512
DEFAULT_FEATURE_CURVE_POINT_COUNT = 512
DEFAULT_BASS_CUTOFF_HZ = 180.0
DEFAULT_ONSET_DENSITY_WINDOW_SECONDS = 0.5
NEAR_SILENCE_RMS = 1e-4


class FeatureExtractionError(ValueError):
    """Expected feature extraction failure."""

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
class EnergyFeatures:
    global_energy: float
    curve: tuple[dict[str, float], ...]
    bass_energy_curve: tuple[dict[str, float], ...]
    onset_density_curve: tuple[dict[str, float], ...]
    warnings: tuple[str, ...]
    frame_length: int
    hop_length: int
    curve_point_count: int
    bass_cutoff_hz: float


def compute_energy_features(
    decoded_audio: DecodedAudio,
    *,
    frame_length: int = DEFAULT_FEATURE_FRAME_LENGTH,
    hop_length: int = DEFAULT_FEATURE_HOP_LENGTH,
    curve_point_count: int = DEFAULT_FEATURE_CURVE_POINT_COUNT,
    bass_cutoff_hz: float = DEFAULT_BASS_CUTOFF_HZ,
    onset_density_window_seconds: float = DEFAULT_ONSET_DENSITY_WINDOW_SECONDS,
) -> EnergyFeatures:
    """Compute normalized RMS, bass-energy, and onset-density curves."""

    _validate_feature_parameters(
        decoded_audio,
        frame_length=frame_length,
        hop_length=hop_length,
        curve_point_count=curve_point_count,
        bass_cutoff_hz=bass_cutoff_hz,
        onset_density_window_seconds=onset_density_window_seconds,
    )

    numpy = _require_feature_dependency("numpy", module_name="numpy")
    samples = numpy.asarray(decoded_audio.samples, dtype=numpy.float32).reshape(-1)
    if samples.size == 0:
        raise FeatureExtractionError("feature_empty_audio", "Decoded audio contains no samples")

    warnings: list[str] = []
    rms_values, frame_times = _frame_rms(
        samples,
        numpy=numpy,
        sample_rate=decoded_audio.sample_rate,
        frame_length=frame_length,
        hop_length=hop_length,
    )
    peak_rms = float(rms_values.max()) if rms_values.size else 0.0
    global_energy = _round_float(_clamp(float(rms_values.mean()) if rms_values.size else 0.0))
    energy_curve = _curve_from_values(
        _normalize_values(rms_values, numpy=numpy, peak=peak_rms),
        frame_times,
        numpy=numpy,
        max_points=curve_point_count,
    )

    bass_curve = _bass_energy_curve(
        samples,
        numpy=numpy,
        sample_rate=decoded_audio.sample_rate,
        frame_length=frame_length,
        hop_length=hop_length,
        curve_point_count=curve_point_count,
        bass_cutoff_hz=bass_cutoff_hz,
        warnings=warnings,
    )
    onset_curve = _onset_density_curve(
        samples,
        numpy=numpy,
        sample_rate=decoded_audio.sample_rate,
        hop_length=hop_length,
        curve_point_count=curve_point_count,
        onset_density_window_seconds=onset_density_window_seconds,
        warnings=warnings,
    )

    if peak_rms <= NEAR_SILENCE_RMS:
        warnings.append(
            "Energy estimate is near silence; energy, bass, and onset curves are low confidence."
        )
    if len(rms_values) > curve_point_count:
        warnings.append(
            f"Energy curves were downsampled from {len(rms_values)} frames to "
            f"{curve_point_count} points; estimates are coarse."
        )
    if len(rms_values) < 4:
        warnings.append("Energy estimate is coarse because the decoded audio is very short.")

    return EnergyFeatures(
        global_energy=global_energy,
        curve=tuple(energy_curve),
        bass_energy_curve=tuple(bass_curve),
        onset_density_curve=tuple(onset_curve),
        warnings=tuple(warnings),
        frame_length=frame_length,
        hop_length=hop_length,
        curve_point_count=curve_point_count,
        bass_cutoff_hz=float(bass_cutoff_hz),
    )


def build_energy_analysis(features: EnergyFeatures) -> dict[str, Any]:
    """Convert extracted energy features to the AnalyzedTrack energy shape."""

    return {
        "globalEnergy": features.global_energy,
        "curve": [dict(point) for point in features.curve],
        "bassEnergyCurve": [dict(point) for point in features.bass_energy_curve],
        "onsetDensityCurve": [dict(point) for point in features.onset_density_curve],
    }


def _validate_feature_parameters(
    decoded_audio: DecodedAudio,
    *,
    frame_length: int,
    hop_length: int,
    curve_point_count: int,
    bass_cutoff_hz: float,
    onset_density_window_seconds: float,
) -> None:
    if decoded_audio.sample_rate <= 0:
        raise FeatureExtractionError(
            "feature_invalid_audio",
            "Decoded audio sample_rate must be greater than zero",
        )
    if frame_length <= 0:
        raise FeatureExtractionError(
            "feature_invalid_parameters",
            "frame_length must be greater than zero",
        )
    if hop_length <= 0:
        raise FeatureExtractionError(
            "feature_invalid_parameters",
            "hop_length must be greater than zero",
        )
    if curve_point_count <= 0:
        raise FeatureExtractionError(
            "feature_invalid_parameters",
            "curve_point_count must be greater than zero",
        )
    if bass_cutoff_hz <= 0 or bass_cutoff_hz >= decoded_audio.sample_rate / 2:
        raise FeatureExtractionError(
            "feature_invalid_parameters",
            "bass_cutoff_hz must be greater than zero and below the Nyquist frequency",
        )
    if onset_density_window_seconds <= 0:
        raise FeatureExtractionError(
            "feature_invalid_parameters",
            "onset_density_window_seconds must be greater than zero",
        )


def _frame_rms(
    samples: Any,
    *,
    numpy: Any,
    sample_rate: int,
    frame_length: int,
    hop_length: int,
) -> tuple[Any, Any]:
    starts = numpy.arange(0, samples.size, hop_length, dtype=numpy.int64)
    values = numpy.empty(starts.size, dtype=numpy.float32)

    for index, start in enumerate(starts):
        frame = samples[int(start) : min(int(start) + frame_length, samples.size)]
        values[index] = math.sqrt(float(numpy.mean(frame * frame))) if frame.size else 0.0

    times = starts.astype(numpy.float32) / float(sample_rate)
    return values, times


def _bass_energy_curve(
    samples: Any,
    *,
    numpy: Any,
    sample_rate: int,
    frame_length: int,
    hop_length: int,
    curve_point_count: int,
    bass_cutoff_hz: float,
    warnings: list[str],
) -> tuple[dict[str, float], ...]:
    scipy_signal = _optional_feature_dependency("scipy", module_name="scipy.signal")
    if scipy_signal is None:
        warnings.append("Bass energy curve unavailable because SciPy signal processing is not installed.")
        return ()

    try:
        sos = scipy_signal.butter(
            4,
            bass_cutoff_hz / (sample_rate / 2.0),
            btype="lowpass",
            output="sos",
        )
        if samples.size > 128:
            bass_samples = scipy_signal.sosfiltfilt(sos, samples).astype(numpy.float32, copy=False)
        else:
            bass_samples = scipy_signal.sosfilt(sos, samples).astype(numpy.float32, copy=False)
    except ValueError as exc:
        warnings.append(f"Bass energy curve unavailable because low-pass filtering failed: {exc}.")
        return ()

    rms_values, times = _frame_rms(
        bass_samples,
        numpy=numpy,
        sample_rate=sample_rate,
        frame_length=frame_length,
        hop_length=hop_length,
    )
    peak = float(rms_values.max()) if rms_values.size else 0.0
    return tuple(
        _curve_from_values(
            _normalize_values(rms_values, numpy=numpy, peak=peak),
            times,
            numpy=numpy,
            max_points=curve_point_count,
        )
    )


def _onset_density_curve(
    samples: Any,
    *,
    numpy: Any,
    sample_rate: int,
    hop_length: int,
    curve_point_count: int,
    onset_density_window_seconds: float,
    warnings: list[str],
) -> tuple[dict[str, float], ...]:
    librosa = _optional_feature_dependency("librosa", module_name="librosa")
    if librosa is None:
        warnings.append("Onset density curve unavailable because librosa is not installed.")
        return ()

    try:
        onset_envelope = librosa.onset.onset_strength(
            y=samples,
            sr=sample_rate,
            hop_length=hop_length,
        )
    except Exception as exc:
        warnings.append(f"Onset density curve unavailable because onset extraction failed: {exc}.")
        return ()

    onset_envelope = numpy.asarray(onset_envelope, dtype=numpy.float32)
    if onset_envelope.size == 0:
        warnings.append("Onset density estimate is unavailable because no onset frames were produced.")
        return ()

    window_frames = max(1, round(onset_density_window_seconds * sample_rate / hop_length))
    onset_density = _moving_average(onset_envelope, numpy=numpy, window_frames=window_frames)
    peak = float(onset_density.max()) if onset_density.size else 0.0
    if peak <= NEAR_SILENCE_RMS:
        warnings.append("Onset density estimate is weak; transient evidence is low confidence.")

    times = numpy.arange(onset_density.size, dtype=numpy.float32) * (hop_length / float(sample_rate))
    return tuple(
        _curve_from_values(
            _normalize_values(onset_density, numpy=numpy, peak=peak),
            times,
            numpy=numpy,
            max_points=curve_point_count,
        )
    )


def _moving_average(values: Any, *, numpy: Any, window_frames: int) -> Any:
    if window_frames <= 1:
        return values
    kernel = numpy.ones(window_frames, dtype=numpy.float32) / float(window_frames)
    return numpy.convolve(values, kernel, mode="same").astype(numpy.float32, copy=False)


def _normalize_values(values: Any, *, numpy: Any, peak: float) -> Any:
    if peak <= NEAR_SILENCE_RMS:
        return numpy.zeros_like(values, dtype=numpy.float32)
    return numpy.clip(values / peak, 0.0, 1.0).astype(numpy.float32, copy=False)


def _curve_from_values(
    values: Any,
    times: Any,
    *,
    numpy: Any,
    max_points: int,
) -> tuple[dict[str, float], ...]:
    value_count = int(values.size)
    if value_count == 0:
        return ()

    point_count = min(max_points, value_count)
    points: list[dict[str, float]] = []
    for point_index in range(point_count):
        start = math.floor(point_index * value_count / point_count)
        end = math.floor((point_index + 1) * value_count / point_count)
        if end <= start:
            end = start + 1
        points.append(
            {
                "timeSeconds": _round_float(float(times[start])),
                "value": _round_float(_clamp(float(numpy.mean(values[start:end])))),
            }
        )
    return tuple(points)


def _require_feature_dependency(dependency: str, *, module_name: str) -> Any:
    try:
        return require_optional_dependency(
            dependency,
            module_name=module_name,
            install_extra="analysis",
        )
    except OptionalDependencyUnavailable as exc:
        details = exc.to_dict()
        raise FeatureExtractionError(
            "feature_dependency_missing",
            details["message"],
            dependency=details["dependency"],
        ) from None


def _optional_feature_dependency(dependency: str, *, module_name: str) -> Any | None:
    try:
        return require_optional_dependency(
            dependency,
            module_name=module_name,
            install_extra="analysis",
        )
    except OptionalDependencyUnavailable:
        return None


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded
