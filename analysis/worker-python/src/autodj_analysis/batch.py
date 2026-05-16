"""Batch analysis workflow and artifact construction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .cache import (
    ArtifactIdentity,
    CacheError,
    SCHEMA_VERSION,
    analyzed_track_path,
    check_artifact_freshness,
    load_analyzed_artifact,
    write_json_atomic,
)
from .manifest import RepositoryManifest, RepositoryTrack, load_repository_manifest
from .probe import AudioProbe, ProbeError, ProbeRunner, probe_audio


ANALYZER_PRODUCER = "autodj_analysis.ffprobe"
ANALYZER_VERSION = __version__
DEFAULT_PARAMETERS_HASH = "sha256:ffprobe-v1-placeholders-v1"
FFPROBE_ONLY_WARNING = (
    "Only FFprobe container/stream metadata was analyzed; BPM, key, beat grid, "
    "sections, energy, vocals, stems, and cue points are low-confidence placeholders."
)
TRACK_STATUS_ANALYZED = "analyzed"
TRACK_STATUS_SKIPPED = "skipped"
TRACK_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class BatchTrackResult:
    track_id: str
    status: str
    artifact_path: Path | None = None
    reason: str | None = None
    message: str | None = None
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "trackId": self.track_id,
            "status": self.status,
        }
        if self.artifact_path is not None:
            payload["artifactPath"] = str(self.artifact_path)
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.message is not None:
            payload["message"] = self.message
        if self.error is not None:
            payload["error"] = dict(self.error)
        return payload


@dataclass(frozen=True)
class BatchAnalysisResult:
    manifest_path: Path | None
    cache_root: Path
    total_tracks: int
    analyzed: int
    skipped: int
    failed: int
    tracks: tuple[BatchTrackResult, ...]
    errors: tuple[dict[str, str], ...]

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "manifestPath": str(self.manifest_path) if self.manifest_path is not None else None,
            "cacheRoot": str(self.cache_root),
            "total": self.total_tracks,
            "totalTracks": self.total_tracks,
            "analyzed": self.analyzed,
            "skipped": self.skipped,
            "failed": self.failed,
            "tracks": [track.to_dict() for track in self.tracks],
            "errors": [dict(error) for error in self.errors],
        }


def analyze_repository_manifest(
    manifest_path: str | Path,
    cache_root: str | Path,
    *,
    ffprobe_path: str | Path = "ffprobe",
    force: bool = False,
    parameters_hash: str = DEFAULT_PARAMETERS_HASH,
    probe_runner: ProbeRunner | None = None,
) -> BatchAnalysisResult:
    """Load a repository manifest and analyze each track into the cache root."""

    manifest = load_repository_manifest(manifest_path)
    return analyze_manifest(
        manifest,
        cache_root,
        ffprobe_path=ffprobe_path,
        force=force,
        parameters_hash=parameters_hash,
        probe_runner=probe_runner,
    )


def analyze_manifest(
    manifest: RepositoryManifest,
    cache_root: str | Path,
    *,
    ffprobe_path: str | Path = "ffprobe",
    force: bool = False,
    parameters_hash: str = DEFAULT_PARAMETERS_HASH,
    probe_runner: ProbeRunner | None = None,
) -> BatchAnalysisResult:
    """Analyze every track from a parsed repository manifest.

    Per-track probe/cache failures are converted into failed track results so
    later tracks can still be processed. Manifest-level load/parse failures are
    intentionally left to ``analyze_repository_manifest`` callers.
    """

    cache_root_path = Path(cache_root)
    tracks = tuple(
        _analyze_manifest_track(
            track,
            cache_root_path,
            ffprobe_path=ffprobe_path,
            force=force,
            parameters_hash=parameters_hash,
            probe_runner=probe_runner,
        )
        for track in manifest.tracks
    )
    errors = tuple(track.error for track in tracks if track.error is not None)

    return BatchAnalysisResult(
        manifest_path=manifest.manifest_path,
        cache_root=cache_root_path,
        total_tracks=len(tracks),
        analyzed=sum(track.status == TRACK_STATUS_ANALYZED for track in tracks),
        skipped=sum(track.status == TRACK_STATUS_SKIPPED for track in tracks),
        failed=sum(track.status == TRACK_STATUS_FAILED for track in tracks),
        tracks=tracks,
        errors=errors,
    )


def artifact_identity_for_track(
    track: RepositoryTrack,
    *,
    parameters_hash: str = DEFAULT_PARAMETERS_HASH,
    analyzer_producer: str = ANALYZER_PRODUCER,
    analyzer_version: str = ANALYZER_VERSION,
) -> ArtifactIdentity:
    """Build the cache freshness identity for a manifest track."""

    return ArtifactIdentity(
        track_id=track.track_id,
        analyzer_producer=analyzer_producer,
        analyzer_version=analyzer_version,
        source_content_hash=track.content_hash,
        parameters_hash=parameters_hash,
    )


def _analyze_manifest_track(
    track: RepositoryTrack,
    cache_root: Path,
    *,
    ffprobe_path: str | Path,
    force: bool,
    parameters_hash: str,
    probe_runner: ProbeRunner | None,
) -> BatchTrackResult:
    artifact_path: Path | None = None
    try:
        artifact_path = analyzed_track_path(cache_root, track.track_id)
        identity = artifact_identity_for_track(track, parameters_hash=parameters_hash)
        loaded = load_analyzed_artifact(artifact_path)
        freshness = check_artifact_freshness(loaded, identity, force=force)

        if freshness.is_fresh:
            return BatchTrackResult(
                track_id=track.track_id,
                status=TRACK_STATUS_SKIPPED,
                artifact_path=artifact_path,
                reason=freshness.reason,
                message=freshness.message,
            )

        probe = probe_audio(
            track.source_path,
            ffprobe_path=ffprobe_path,
            source_uri=track.source_uri,
            track_id=track.track_id,
            runner=probe_runner,
        )
        artifact = build_analyzed_track_artifact(track, probe, parameters_hash=parameters_hash)
        write_json_atomic(artifact_path, artifact)

        return BatchTrackResult(
            track_id=track.track_id,
            status=TRACK_STATUS_ANALYZED,
            artifact_path=artifact_path,
            reason=freshness.reason,
            message=freshness.message,
        )
    except ProbeError as exc:
        return _failed_track_result(track, artifact_path, exc.to_dict())
    except CacheError as exc:
        return _failed_track_result(track, artifact_path, _cache_error_to_dict(track, exc))


def build_analyzed_track_artifact(
    track: RepositoryTrack,
    probe: AudioProbe,
    *,
    parameters_hash: str = DEFAULT_PARAMETERS_HASH,
    created_at_utc: str | None = None,
    analyzer_producer: str = ANALYZER_PRODUCER,
    analyzer_version: str = ANALYZER_VERSION,
) -> dict[str, Any]:
    """Build an AnalyzedTrack artifact from repository identity and probe data."""

    duration_seconds = _duration_seconds(track, probe)
    source = _source_asset(track, probe, duration_seconds)
    warnings = [FFPROBE_ONLY_WARNING]
    if probe.duration_seconds is None and track.duration_seconds is None:
        warnings.append("Duration was unavailable from both manifest and FFprobe; using 0.0 seconds.")
    if probe.sample_rate is None:
        warnings.append("Sample rate was unavailable from FFprobe.")
    if probe.channels is None:
        warnings.append("Channel count was unavailable from FFprobe.")

    analyzer = {
        "producer": analyzer_producer,
        "producerVersion": analyzer_version,
        "createdAtUtc": created_at_utc or _utc_now_iso(),
        "parametersHash": parameters_hash,
    }
    _set_if_present(analyzer, "sourceContentHash", track.content_hash)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "trackId": track.track_id,
        "source": source,
        "analyzer": analyzer,
        "durationSeconds": duration_seconds,
        "tempo": {
            "bpm": 140.0,
            "normalizedBpm": 140.0,
            "confidence": 0.0,
            "tempoClass": "straight",
            "candidates": [],
        },
        "key": {
            "tonic": "unknown",
            "mode": "unknown",
            "confidence": 0.0,
            "candidates": [],
        },
        "beatGrid": {
            "beats": [],
            "downbeats": [],
            "confidence": 0.0,
        },
        "sections": [],
        "energy": {
            "globalEnergy": 0.0,
            "curve": [],
            "bassEnergyCurve": [],
            "onsetDensityCurve": [],
        },
        "vocals": {
            "hasVocals": False,
            "confidence": 0.0,
            "regions": [],
        },
        "cuePoints": [],
        "quality": {
            "overallConfidence": 0.1,
            "warnings": warnings,
        },
    }


def _source_asset(track: RepositoryTrack, probe: AudioProbe, duration_seconds: float) -> dict[str, Any]:
    source: dict[str, Any] = {
        "trackId": track.track_id,
        "repositoryId": track.repository_id,
        "sourceUri": track.source_uri,
        "durationSeconds": duration_seconds,
        "providerMetadata": _provider_metadata(track, probe),
    }

    _set_if_present(source, "contentHash", track.content_hash)
    _set_if_present(source, "title", _title(track, probe))
    _set_if_present(source, "artist", track.artist or _tag_value(probe.tags, "artist", "album_artist"))
    _set_if_present(source, "album", track.album or _tag_value(probe.tags, "album"))
    _set_if_present(source, "sampleRate", probe.sample_rate)
    _set_if_present(source, "channels", probe.channels)
    _set_if_present(source, "formatHint", track.format_hint)

    return source


def _provider_metadata(track: RepositoryTrack, probe: AudioProbe) -> dict[str, Any]:
    metadata = dict(track.provider_metadata)
    ffprobe_metadata: dict[str, Any] = {}

    _set_if_present(ffprobe_metadata, "codecName", probe.codec_name)
    _set_if_present(ffprobe_metadata, "codecLongName", probe.codec_long_name)
    _set_if_present(ffprobe_metadata, "bitRate", probe.bit_rate)
    _set_if_present(ffprobe_metadata, "formatName", probe.format_name)
    _set_if_present(ffprobe_metadata, "formatLongName", probe.format_long_name)
    if probe.tags:
        ffprobe_metadata["tags"] = dict(probe.tags)

    metadata["ffprobe"] = ffprobe_metadata
    return metadata


def _duration_seconds(track: RepositoryTrack, probe: AudioProbe) -> float:
    if probe.duration_seconds is not None:
        return probe.duration_seconds
    if track.duration_seconds is not None:
        return track.duration_seconds
    return 0.0


def _title(track: RepositoryTrack, probe: AudioProbe) -> str:
    return track.title or _tag_value(probe.tags, "title") or Path(track.source_path).stem or track.track_id


def _tag_value(tags: dict[str, str], *names: str) -> str | None:
    lower_names = {name.lower() for name in names}
    for key, value in tags.items():
        if key.lower() in lower_names and value:
            return value
    return None


def _set_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        target[key] = value


def _failed_track_result(
    track: RepositoryTrack,
    artifact_path: Path | None,
    error: dict[str, str],
) -> BatchTrackResult:
    return BatchTrackResult(
        track_id=track.track_id,
        status=TRACK_STATUS_FAILED,
        artifact_path=artifact_path,
        reason=error["code"],
        message=error["message"],
        error=error,
    )


def _cache_error_to_dict(track: RepositoryTrack, error: CacheError) -> dict[str, str]:
    payload = error.to_dict()
    payload["trackId"] = track.track_id
    payload["sourceUri"] = track.source_uri
    return payload


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
