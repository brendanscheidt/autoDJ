"""Library-based audio loading boundary for signal analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any

from .dependencies import OptionalDependencyUnavailable, require_optional_dependency


DEFAULT_ANALYSIS_SAMPLE_RATE = 22_050
SUPPORTED_AUDIO_EXTENSIONS = frozenset(
    {
        ".aif",
        ".aiff",
        ".flac",
        ".m4a",
        ".mp3",
        ".ogg",
        ".wav",
    }
)


@dataclass(frozen=True)
class DecodedAudio:
    samples: Any
    sample_rate: int
    duration_seconds: float
    channels: int | None
    source_path: Path


class AudioLoadError(ValueError):
    """Expected audio loading failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        source_uri: str | None = None,
        track_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.source_uri = source_uri
        self.track_id = track_id

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.track_id is not None:
            payload["trackId"] = self.track_id
        if self.source_uri is not None:
            payload["sourceUri"] = self.source_uri
        return payload


def load_audio(
    audio_path: str | Path,
    *,
    target_sample_rate: int | None = DEFAULT_ANALYSIS_SAMPLE_RATE,
    source_uri: str | None = None,
    track_id: str | None = None,
) -> DecodedAudio:
    """Load local audio as mono floating-point PCM for signal analysis."""

    path = Path(audio_path)
    error_source_uri = source_uri or path.as_posix()
    if target_sample_rate is not None and target_sample_rate <= 0:
        raise ValueError("target_sample_rate must be greater than zero or None")
    if not path.exists():
        raise AudioLoadError(
            "source_missing",
            f"Audio source does not exist: {path}",
            source_uri=error_source_uri,
            track_id=track_id,
        )
    if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        raise AudioLoadError(
            "audio_unsupported_format",
            f"Unsupported audio file extension for signal loading: {path.suffix or '<none>'}",
            source_uri=error_source_uri,
            track_id=track_id,
        )

    if target_sample_rate is not None:
        ffmpeg_decoded = _load_audio_with_ffmpeg(
            path,
            target_sample_rate=target_sample_rate,
            source_uri=error_source_uri,
            track_id=track_id,
        )
        if ffmpeg_decoded is not None:
            return ffmpeg_decoded

    soundfile = _require_audio_dependency(
        "soundfile",
        module_name="soundfile",
        source_uri=error_source_uri,
        track_id=track_id,
    )
    numpy = _require_audio_dependency(
        "numpy",
        module_name="numpy",
        source_uri=error_source_uri,
        track_id=track_id,
    )

    try:
        samples, source_sample_rate = soundfile.read(
            str(path),
            always_2d=True,
            dtype="float32",
        )
    except RuntimeError as exc:
        raise AudioLoadError(
            "audio_decode_error",
            f"Could not decode audio source: {exc}",
            source_uri=error_source_uri,
            track_id=track_id,
        ) from exc
    except OSError as exc:
        raise AudioLoadError(
            "audio_decode_error",
            f"Could not read audio source: {exc}",
            source_uri=error_source_uri,
            track_id=track_id,
        ) from exc

    source_sample_rate = int(source_sample_rate)
    channel_count = int(samples.shape[1]) if samples.ndim == 2 else None
    mono_samples = _to_mono_float32(samples, numpy)
    if mono_samples.size == 0:
        raise AudioLoadError(
            "audio_empty",
            "Decoded audio source contains no samples.",
            source_uri=error_source_uri,
            track_id=track_id,
        )

    sample_rate = source_sample_rate
    if target_sample_rate is not None and source_sample_rate != target_sample_rate:
        mono_samples = _resample_mono(
            mono_samples,
            source_sample_rate=source_sample_rate,
            target_sample_rate=target_sample_rate,
            source_uri=error_source_uri,
            track_id=track_id,
        )
        sample_rate = target_sample_rate
        if mono_samples.size == 0:
            raise AudioLoadError(
                "audio_empty",
                "Decoded audio source contains no samples after resampling.",
                source_uri=error_source_uri,
                track_id=track_id,
            )

    return DecodedAudio(
        samples=mono_samples,
        sample_rate=sample_rate,
        duration_seconds=float(mono_samples.shape[0] / sample_rate),
        channels=channel_count,
        source_path=path,
    )


def _load_audio_with_ffmpeg(
    path: Path,
    *,
    target_sample_rate: int,
    source_uri: str,
    track_id: str | None,
) -> DecodedAudio | None:
    numpy = _require_audio_dependency(
        "numpy",
        module_name="numpy",
        source_uri=source_uri,
        track_id=track_id,
    )
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        str(target_sample_rate),
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        return None
    except OSError:
        return None

    if completed.returncode != 0:
        return None
    samples = numpy.frombuffer(completed.stdout, dtype=numpy.float32).copy()
    if samples.size == 0:
        raise AudioLoadError(
            "audio_empty",
            "Decoded audio source contains no samples.",
            source_uri=source_uri,
            track_id=track_id,
        )
    return DecodedAudio(
        samples=samples,
        sample_rate=target_sample_rate,
        duration_seconds=float(samples.shape[0] / target_sample_rate),
        channels=1,
        source_path=path,
    )


def _to_mono_float32(samples: Any, numpy: Any) -> Any:
    array = numpy.asarray(samples, dtype=numpy.float32)
    if array.ndim == 1:
        return array
    if array.ndim == 2:
        return array.mean(axis=1, dtype=numpy.float32)
    return array.reshape(-1).astype(numpy.float32, copy=False)


def _resample_mono(
    samples: Any,
    *,
    source_sample_rate: int,
    target_sample_rate: int,
    source_uri: str,
    track_id: str | None,
) -> Any:
    librosa = _require_audio_dependency(
        "librosa",
        module_name="librosa",
        source_uri=source_uri,
        track_id=track_id,
    )
    numpy = _require_audio_dependency(
        "numpy",
        module_name="numpy",
        source_uri=source_uri,
        track_id=track_id,
    )
    try:
        resampled = librosa.resample(
            samples,
            orig_sr=source_sample_rate,
            target_sr=target_sample_rate,
        )
    except Exception as exc:
        raise AudioLoadError(
            "audio_decode_error",
            f"Could not resample decoded audio source: {exc}",
            source_uri=source_uri,
            track_id=track_id,
        ) from exc
    return numpy.asarray(resampled, dtype=numpy.float32)


def _require_audio_dependency(
    dependency: str,
    *,
    module_name: str,
    source_uri: str,
    track_id: str | None,
) -> Any:
    try:
        return require_optional_dependency(
            dependency,
            module_name=module_name,
            install_extra="analysis",
        )
    except OptionalDependencyUnavailable as exc:
        details = exc.to_dict()
        raise AudioLoadError(
            "audio_dependency_missing",
            details["message"],
            source_uri=source_uri,
            track_id=track_id,
        ) from None
