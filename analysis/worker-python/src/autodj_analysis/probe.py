"""FFprobe subprocess adapter for local audio metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping, Sequence


ProbeRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class ProbeError(ValueError):
    """Expected local audio probe failure."""

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


@dataclass(frozen=True)
class AudioProbe:
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    codec_name: str | None
    codec_long_name: str | None
    bit_rate: int | None
    format_name: str | None
    format_long_name: str | None
    tags: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def probe_audio(
    audio_path: str | Path,
    *,
    ffprobe_path: str | Path = "ffprobe",
    source_uri: str | None = None,
    track_id: str | None = None,
    timeout_seconds: float = 30.0,
    runner: ProbeRunner | None = None,
) -> AudioProbe:
    """Probe local audio metadata with ffprobe."""

    path = Path(audio_path)
    error_source_uri = source_uri or path.as_posix()
    if not path.exists():
        raise ProbeError(
            "source_missing",
            f"Audio source does not exist: {path}",
            source_uri=error_source_uri,
            track_id=track_id,
        )

    command = [
        str(ffprobe_path),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    try:
        completed = _run_ffprobe(command, runner, timeout_seconds)
    except FileNotFoundError as exc:
        raise ProbeError(
            "ffprobe_missing",
            f"ffprobe executable was not found: {ffprobe_path}",
            source_uri=error_source_uri,
            track_id=track_id,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(
            "ffprobe_failed",
            f"ffprobe timed out after {timeout_seconds:g} seconds",
            source_uri=error_source_uri,
            track_id=track_id,
        ) from exc
    except OSError as exc:
        raise ProbeError(
            "ffprobe_failed",
            f"Could not execute ffprobe: {exc}",
            source_uri=error_source_uri,
            track_id=track_id,
        ) from exc

    if completed.returncode != 0:
        details = _first_non_empty(completed.stderr, completed.stdout) or f"exit code {completed.returncode}"
        raise ProbeError(
            "ffprobe_failed",
            f"ffprobe failed: {_shorten(details)}",
            source_uri=error_source_uri,
            track_id=track_id,
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(
            "ffprobe_invalid_json",
            f"ffprobe emitted invalid JSON: {exc.msg}",
            source_uri=error_source_uri,
            track_id=track_id,
        ) from exc

    if not isinstance(payload, dict):
        raise ProbeError(
            "ffprobe_invalid_json",
            "ffprobe JSON root must be an object",
            source_uri=error_source_uri,
            track_id=track_id,
        )

    try:
        return parse_ffprobe_output(payload, source_uri=error_source_uri, track_id=track_id)
    except ProbeError:
        raise


def parse_ffprobe_output(
    payload: Mapping[str, Any],
    *,
    source_uri: str | None = None,
    track_id: str | None = None,
) -> AudioProbe:
    """Normalize ffprobe JSON into an AudioProbe."""

    stream = _select_primary_audio_stream(payload, source_uri=source_uri, track_id=track_id)
    format_payload = payload.get("format")
    if not isinstance(format_payload, Mapping):
        format_payload = {}

    return AudioProbe(
        duration_seconds=_first_float(stream.get("duration"), format_payload.get("duration")),
        sample_rate=_optional_int(stream.get("sample_rate")),
        channels=_optional_int(stream.get("channels")),
        codec_name=_optional_string(stream.get("codec_name")),
        codec_long_name=_optional_string(stream.get("codec_long_name")),
        bit_rate=_first_int(stream.get("bit_rate"), format_payload.get("bit_rate")),
        format_name=_optional_string(format_payload.get("format_name")),
        format_long_name=_optional_string(format_payload.get("format_long_name")),
        tags=_merge_tags(format_payload.get("tags"), stream.get("tags")),
        raw=dict(payload),
    )


def _run_ffprobe(
    command: Sequence[str],
    runner: ProbeRunner | None,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    if runner is not None:
        return runner(command)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )


def _select_primary_audio_stream(
    payload: Mapping[str, Any],
    *,
    source_uri: str | None,
    track_id: str | None,
) -> Mapping[str, Any]:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        streams = []

    audio_streams = [
        stream
        for stream in streams
        if isinstance(stream, Mapping) and stream.get("codec_type") == "audio"
    ]
    if not audio_streams:
        raise ProbeError(
            "ffprobe_no_audio_stream",
            "ffprobe did not report an audio stream",
            source_uri=source_uri,
            track_id=track_id,
        )

    return min(audio_streams, key=_audio_stream_sort_key)


def _audio_stream_sort_key(stream: Mapping[str, Any]) -> tuple[int, int]:
    disposition = stream.get("disposition")
    default_value = 0
    if isinstance(disposition, Mapping):
        default_value = _optional_int(disposition.get("default")) or 0
    index = _optional_int(stream.get("index"))
    return (0 if default_value == 1 else 1, index if index is not None else 999_999)


def _merge_tags(*sources: Any) -> dict[str, str]:
    tags: dict[str, str] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key, value in source.items():
            if isinstance(key, str) and value is not None:
                tags[key] = str(value)
    return tags


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _optional_float(value)
        if parsed is not None:
            return parsed
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _optional_int(value)
        if parsed is not None:
            return parsed
    return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "N/A":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "N/A":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value != "":
        return value
    return None


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value.strip()
    return None


def _shorten(value: str, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."
