"""Canonical PCM cache for timing-sensitive analysis paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Callable, Sequence
import wave

from . import __version__
from .audio_io import SUPPORTED_AUDIO_EXTENSIONS
from .cache import SCHEMA_VERSION, track_cache_dir, write_json_atomic
from .manifest import RepositoryManifest, RepositoryTrack, load_repository_manifest
from .probe import ProbeError, ProbeRunner, probe_audio


CANONICAL_AUDIO_FILENAME = "canonical.wav"
CANONICAL_AUDIO_METADATA_FILENAME = "canonical-audio.json"
CANONICAL_AUDIO_PRODUCER = "autodj_analysis.canonical_audio"
CANONICAL_AUDIO_PARAMETERS_HASH = "sha256:canonical-pcm-v1-ffmpeg-mono-pcm16"
CANONICAL_TIMELINE_POLICY = "shared-canonical-pcm"
CANONICAL_SUPPORTED_SAMPLE_RATES = frozenset({44_100, 48_000})
CANONICAL_FALLBACK_SAMPLE_RATE = 44_100


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class CanonicalAudioOptions:
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    force: bool = False
    target_sample_rate: int | None = None
    fallback_sample_rate: int = CANONICAL_FALLBACK_SAMPLE_RATE


@dataclass(frozen=True)
class CanonicalAudioPaths:
    track_dir: Path
    audio_path: Path
    metadata_path: Path


@dataclass(frozen=True)
class CanonicalAudioResult:
    track_id: str
    source_path: Path
    canonical_path: Path
    metadata_path: Path
    status: str
    source_content_hash: str
    sample_rate: int | None
    channels: int | None
    duration_seconds: float | None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trackId": self.track_id,
            "sourcePath": str(self.source_path),
            "canonicalPath": str(self.canonical_path),
            "metadataPath": str(self.metadata_path),
            "status": self.status,
            "sourceContentHash": self.source_content_hash,
            "sampleRate": self.sample_rate,
            "channels": self.channels,
            "durationSeconds": self.duration_seconds,
            "warnings": list(self.warnings),
        }


class CanonicalAudioError(ValueError):
    """Expected canonical audio creation failure."""

    def __init__(self, code: str, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.path is not None:
            payload["path"] = self.path
        return payload


def canonical_audio_paths(output_root: str | Path, track_id: str) -> CanonicalAudioPaths:
    """Return canonical PCM paths for a track under an output root."""

    track_dir = track_cache_dir(output_root, track_id)
    return CanonicalAudioPaths(
        track_dir=track_dir,
        audio_path=track_dir / CANONICAL_AUDIO_FILENAME,
        metadata_path=track_dir / CANONICAL_AUDIO_METADATA_FILENAME,
    )


def canonicalize_repository_manifest(
    repository_manifest: str | Path,
    output_root: str | Path,
    *,
    options: CanonicalAudioOptions | None = None,
    command_runner: CommandRunner | None = None,
    probe_runner: ProbeRunner | None = None,
) -> dict[str, Any]:
    """Canonicalize every track from a repository manifest."""

    manifest = load_repository_manifest(repository_manifest)
    root = Path(output_root)
    options = options or CanonicalAudioOptions()
    results: list[dict[str, Any]] = []
    ok = True
    for track in manifest.tracks:
        try:
            result = canonicalize_track(
                track,
                root,
                options=options,
                command_runner=command_runner,
                probe_runner=probe_runner,
            )
            results.append(result.to_dict())
        except CanonicalAudioError as exc:
            ok = False
            payload = exc.to_dict()
            payload["trackId"] = track.track_id
            payload["sourceUri"] = track.source_uri
            results.append(
                {
                    "trackId": track.track_id,
                    "sourcePath": str(track.source_path),
                    "status": "failed",
                    "error": payload,
                    "warnings": [],
                }
            )

    summary = {
        "ok": ok,
        "artifact": "canonical-audio-batch",
        "schemaVersion": SCHEMA_VERSION,
        "manifestPath": str(Path(repository_manifest)),
        "outputRoot": str(root),
        "total": len(manifest.tracks),
        "canonicalized": sum(1 for result in results if result.get("status") == "canonicalized"),
        "skipped": sum(1 for result in results if result.get("status") == "skipped"),
        "failed": sum(1 for result in results if result.get("status") == "failed"),
        "tracks": results,
    }
    write_json_atomic(root / "canonical-audio-summary.json", summary)
    return summary


def canonicalize_track(
    track: RepositoryTrack,
    output_root: str | Path,
    *,
    options: CanonicalAudioOptions | None = None,
    command_runner: CommandRunner | None = None,
    probe_runner: ProbeRunner | None = None,
) -> CanonicalAudioResult:
    """Canonicalize one manifest track."""

    return canonicalize_audio_file(
        track.source_path,
        output_root,
        track_id=track.track_id,
        source_uri=track.source_uri,
        repository_id=track.repository_id,
        expected_content_hash=track.content_hash,
        options=options,
        command_runner=command_runner,
        probe_runner=probe_runner,
    )


def canonicalize_audio_file(
    audio_path: str | Path,
    output_root: str | Path,
    *,
    track_id: str,
    source_uri: str | None = None,
    repository_id: str | None = None,
    expected_content_hash: str | None = None,
    options: CanonicalAudioOptions | None = None,
    command_runner: CommandRunner | None = None,
    probe_runner: ProbeRunner | None = None,
) -> CanonicalAudioResult:
    """Decode one source into the canonical mono PCM WAV timeline."""

    options = options or CanonicalAudioOptions()
    runner = command_runner or _run_command
    source = Path(audio_path)
    if not track_id:
        raise CanonicalAudioError("invalid_track_id", "track_id must be non-empty")
    if not source.exists():
        raise CanonicalAudioError("source_missing", f"Audio source does not exist: {source}", path=str(source))
    if source.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        raise CanonicalAudioError(
            "audio_unsupported_format",
            f"Unsupported audio file extension for canonical audio: {source.suffix or '<none>'}",
            path=str(source),
        )
    if options.target_sample_rate is not None and options.target_sample_rate <= 0:
        raise CanonicalAudioError("invalid_options", "target_sample_rate must be positive when provided")
    if options.fallback_sample_rate <= 0:
        raise CanonicalAudioError("invalid_options", "fallback_sample_rate must be positive")

    paths = canonical_audio_paths(output_root, track_id)
    source_hash = _sha256_file(source)
    warnings: list[str] = []
    if expected_content_hash is not None and expected_content_hash != source_hash:
        warnings.append(
            "Manifest content hash differed from the source file hash; canonical artifact uses the actual file hash."
        )

    if not options.force and _metadata_is_fresh(paths.metadata_path, paths.audio_path, source_hash):
        metadata = _read_metadata(paths.metadata_path)
        return CanonicalAudioResult(
            track_id=track_id,
            source_path=source,
            canonical_path=paths.audio_path,
            metadata_path=paths.metadata_path,
            status="skipped",
            source_content_hash=source_hash,
            sample_rate=_optional_int(metadata.get("sampleRate")),
            channels=_optional_int(metadata.get("channels")),
            duration_seconds=_optional_float(metadata.get("durationSeconds")),
            warnings=tuple(warnings),
        )

    probe_payload, probe_warnings = _probe_source(
        source,
        ffprobe_path=options.ffprobe_path,
        source_uri=source_uri,
        track_id=track_id,
        probe_runner=probe_runner,
    )
    warnings.extend(probe_warnings)
    target_rate, rate_warning = _target_sample_rate(probe_payload.get("sampleRate"), options)
    if rate_warning is not None:
        warnings.append(rate_warning)

    paths.track_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_version = _ffmpeg_version(options.ffmpeg_path, runner)
    command = _ffmpeg_command(options.ffmpeg_path, source, paths.audio_path, target_sample_rate=target_rate)
    completed = runner(command)
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        raise CanonicalAudioError(
            "ffmpeg_failed",
            f"ffmpeg failed while creating canonical PCM: {details or 'no details'}",
            path=str(source),
        )
    if not paths.audio_path.exists():
        raise CanonicalAudioError(
            "canonical_audio_missing",
            f"ffmpeg did not create canonical audio: {paths.audio_path}",
            path=str(paths.audio_path),
        )

    wav_info = _wav_info(paths.audio_path)
    metadata = {
        "artifactType": "canonical-audio",
        "schemaVersion": SCHEMA_VERSION,
        "producer": CANONICAL_AUDIO_PRODUCER,
        "producerVersion": __version__,
        "createdAtUtc": _utc_now_iso(),
        "trackId": track_id,
        "repositoryId": repository_id,
        "sourcePath": str(source),
        "sourceUri": source_uri or str(source),
        "sourceContentHash": source_hash,
        "parametersHash": CANONICAL_AUDIO_PARAMETERS_HASH,
        "canonicalPath": str(paths.audio_path),
        "timelinePolicy": CANONICAL_TIMELINE_POLICY,
        "decoder": {
            "name": "ffmpeg",
            "version": ffmpeg_version,
            "command": list(command),
        },
        "ffprobe": probe_payload,
        "sampleRate": wav_info["sampleRate"],
        "channels": wav_info["channels"],
        "durationSeconds": wav_info["durationSeconds"],
        "warnings": warnings,
    }
    if metadata["repositoryId"] is None:
        del metadata["repositoryId"]
    write_json_atomic(paths.metadata_path, metadata)
    return CanonicalAudioResult(
        track_id=track_id,
        source_path=source,
        canonical_path=paths.audio_path,
        metadata_path=paths.metadata_path,
        status="canonicalized",
        source_content_hash=source_hash,
        sample_rate=wav_info["sampleRate"],
        channels=wav_info["channels"],
        duration_seconds=wav_info["durationSeconds"],
        warnings=tuple(warnings),
    )


def _metadata_is_fresh(metadata_path: Path, canonical_path: Path, source_hash: str) -> bool:
    if not metadata_path.exists() or not canonical_path.exists():
        return False
    metadata = _read_metadata(metadata_path)
    return (
        metadata.get("artifactType") == "canonical-audio"
        and metadata.get("sourceContentHash") == source_hash
        and metadata.get("parametersHash") == CANONICAL_AUDIO_PARAMETERS_HASH
        and metadata.get("canonicalPath") == str(canonical_path)
    )


def _read_metadata(metadata_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _probe_source(
    source: Path,
    *,
    ffprobe_path: str,
    source_uri: str | None,
    track_id: str,
    probe_runner: ProbeRunner | None,
) -> tuple[dict[str, Any], list[str]]:
    try:
        probe = probe_audio(
            source,
            ffprobe_path=ffprobe_path,
            source_uri=source_uri or str(source),
            track_id=track_id,
            runner=probe_runner,
        )
    except ProbeError as exc:
        return {}, [f"ffprobe metadata unavailable for canonical audio: {exc.message}"]
    return (
        {
            "codecName": probe.codec_name,
            "codecLongName": probe.codec_long_name,
            "sampleRate": probe.sample_rate,
            "channels": probe.channels,
            "durationSeconds": probe.duration_seconds,
            "startTimeSeconds": probe.start_time_seconds,
            "bitRate": probe.bit_rate,
            "formatName": probe.format_name,
            "formatLongName": probe.format_long_name,
            "tags": dict(probe.tags),
        },
        [],
    )


def _target_sample_rate(source_sample_rate: Any, options: CanonicalAudioOptions) -> tuple[int | None, str | None]:
    if options.target_sample_rate is not None:
        return options.target_sample_rate, None
    if isinstance(source_sample_rate, int) and source_sample_rate in CANONICAL_SUPPORTED_SAMPLE_RATES:
        return source_sample_rate, None
    if isinstance(source_sample_rate, int) and source_sample_rate > 0:
        return (
            options.fallback_sample_rate,
            f"Source sample rate {source_sample_rate} Hz was resampled to canonical fallback "
            f"{options.fallback_sample_rate} Hz.",
        )
    return options.fallback_sample_rate, "Source sample rate was unavailable; using canonical fallback sample rate."


def _ffmpeg_command(ffmpeg_path: str, source: Path, output: Path, *, target_sample_rate: int | None) -> tuple[str, ...]:
    command: list[str] = [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
    ]
    if target_sample_rate is not None:
        command.extend(("-ar", str(target_sample_rate)))
    command.extend(("-c:a", "pcm_s16le", str(output)))
    return tuple(command)


def _ffmpeg_version(ffmpeg_path: str, runner: CommandRunner) -> str | None:
    try:
        completed = runner((ffmpeg_path, "-version"))
    except (OSError, FileNotFoundError):
        return None
    if completed.returncode != 0:
        return None
    first_line = (completed.stdout or "").splitlines()
    return first_line[0].strip() if first_line else None


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise CanonicalAudioError("ffmpeg_missing", f"Executable was not found: {command[0]}") from exc
    except OSError as exc:
        raise CanonicalAudioError("ffmpeg_failed", f"Could not execute {command[0]}: {exc}") from exc


def _wav_info(path: Path) -> dict[str, Any]:
    try:
        with wave.open(str(path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
    except (wave.Error, OSError) as exc:
        raise CanonicalAudioError(
            "canonical_audio_invalid",
            f"Could not inspect canonical WAV: {exc}",
            path=str(path),
        ) from exc
    return {
        "sampleRate": int(sample_rate),
        "channels": int(channels),
        "durationSeconds": frame_count / float(sample_rate) if sample_rate > 0 else 0.0,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) else None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

