"""Batch analysis workflow and artifact construction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .audio_io import AudioLoadError, load_audio
from .cache import (
    ArtifactIdentity,
    CacheError,
    SCHEMA_VERSION,
    analyzed_track_path,
    check_analysis_artifact_freshness,
    load_analyzed_artifact,
    load_waveform_artifact,
    waveform_path,
    write_json_atomic,
)
from .features import EnergyFeatures, FeatureExtractionError, build_energy_analysis, compute_energy_features
from .manifest import RepositoryManifest, RepositoryTrack, load_repository_manifest
from .probe import AudioProbe, ProbeError, ProbeRunner, probe_audio
from .structure import (
    StructureExtractionError,
    StructureFeatures,
    build_cue_points,
    build_sections,
    compute_structure_features,
)
from .tempo import TempoExtractionError, TempoFeatures, build_beat_grid, build_tempo_analysis, compute_tempo_features
from .waveform import WaveformError, build_waveform_artifact, write_waveform_artifact


ANALYZER_PRODUCER = "autodj_analysis.signal"
ANALYZER_VERSION = __version__
DEFAULT_PARAMETERS_HASH = "sha256:signal-v1-waveform-energy-tempo-structure-v1"
FFPROBE_ONLY_WARNING = (
    "Only FFprobe container/stream metadata was analyzed; BPM, key, beat grid, "
    "sections, energy, vocals, stems, and cue points are low-confidence placeholders."
)
PARTIAL_SIGNAL_WARNING = (
    "Signal analysis populated waveform, energy, tempo, beat grid, sections, "
    "and cue candidates where evidence was available; key, vocals, stems, and "
    "downbeats remain low-confidence or empty placeholders."
)
TRACK_STATUS_ANALYZED = "analyzed"
TRACK_STATUS_SKIPPED = "skipped"
TRACK_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class SignalAnalysisResult:
    waveform_artifact: dict[str, Any]
    energy_features: EnergyFeatures
    tempo_features: TempoFeatures
    structure_features: StructureFeatures


SignalAnalyzer = Callable[[RepositoryTrack, ArtifactIdentity, str], SignalAnalysisResult]


@dataclass(frozen=True)
class BatchTrackResult:
    track_id: str
    status: str
    artifact_path: Path | None = None
    waveform_path: Path | None = None
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
        if self.waveform_path is not None:
            payload["waveformPath"] = str(self.waveform_path)
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
    signal_analyzer: SignalAnalyzer | None = None,
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
        signal_analyzer=signal_analyzer,
    )


def analyze_manifest(
    manifest: RepositoryManifest,
    cache_root: str | Path,
    *,
    ffprobe_path: str | Path = "ffprobe",
    force: bool = False,
    parameters_hash: str = DEFAULT_PARAMETERS_HASH,
    probe_runner: ProbeRunner | None = None,
    signal_analyzer: SignalAnalyzer | None = None,
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
            signal_analyzer=signal_analyzer,
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
    signal_analyzer: SignalAnalyzer | None,
) -> BatchTrackResult:
    artifact_path: Path | None = None
    waveform_artifact_path: Path | None = None
    try:
        artifact_path = analyzed_track_path(cache_root, track.track_id)
        waveform_artifact_path = waveform_path(cache_root, track.track_id)
        identity = artifact_identity_for_track(track, parameters_hash=parameters_hash)
        loaded_analyzed = load_analyzed_artifact(artifact_path)
        loaded_waveform = load_waveform_artifact(waveform_artifact_path)
        freshness = check_analysis_artifact_freshness(
            loaded_analyzed,
            loaded_waveform,
            identity,
            force=force,
        )

        if freshness.is_fresh:
            return BatchTrackResult(
                track_id=track.track_id,
                status=TRACK_STATUS_SKIPPED,
                artifact_path=artifact_path,
                waveform_path=waveform_artifact_path,
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
        created_at_utc = _utc_now_iso()
        signal_result = (signal_analyzer or analyze_track_signal)(track, identity, created_at_utc)
        artifact = build_analyzed_track_artifact(
            track,
            probe,
            parameters_hash=parameters_hash,
            created_at_utc=created_at_utc,
            analyzer_producer=identity.analyzer_producer,
            analyzer_version=identity.analyzer_version,
            energy_features=signal_result.energy_features,
            tempo_features=signal_result.tempo_features,
            structure_features=signal_result.structure_features,
        )
        write_json_atomic(artifact_path, artifact)
        write_waveform_artifact(cache_root, track.track_id, signal_result.waveform_artifact)

        return BatchTrackResult(
            track_id=track.track_id,
            status=TRACK_STATUS_ANALYZED,
            artifact_path=artifact_path,
            waveform_path=waveform_artifact_path,
            reason=freshness.reason,
            message=freshness.message,
        )
    except ProbeError as exc:
        return _failed_track_result(track, artifact_path, waveform_artifact_path, exc.to_dict())
    except (
        AudioLoadError,
        WaveformError,
        FeatureExtractionError,
        TempoExtractionError,
        StructureExtractionError,
    ) as exc:
        return _failed_track_result(track, artifact_path, waveform_artifact_path, _analysis_error_to_dict(track, exc))
    except CacheError as exc:
        return _failed_track_result(track, artifact_path, waveform_artifact_path, _cache_error_to_dict(track, exc))
    except Exception as exc:
        return _failed_track_result(track, artifact_path, waveform_artifact_path, _analysis_error_to_dict(track, exc))


def analyze_track_signal(
    track: RepositoryTrack,
    identity: ArtifactIdentity,
    created_at_utc: str,
) -> SignalAnalysisResult:
    """Decode audio and compute real signal-derived analysis features."""

    decoded_audio = load_audio(
        track.source_path,
        source_uri=track.source_uri,
        track_id=track.track_id,
    )
    waveform_artifact = build_waveform_artifact(
        track.track_id,
        decoded_audio,
        analyzer_producer=identity.analyzer_producer,
        analyzer_version=identity.analyzer_version,
        source_content_hash=identity.source_content_hash or "",
        parameters_hash=identity.parameters_hash or "",
        created_at_utc=created_at_utc,
    )
    energy_features = compute_energy_features(decoded_audio)
    tempo_features = compute_tempo_features(decoded_audio)
    structure_features = compute_structure_features(
        energy_features,
        tempo_features=tempo_features,
        duration_seconds=decoded_audio.duration_seconds,
    )
    return SignalAnalysisResult(
        waveform_artifact=waveform_artifact,
        energy_features=energy_features,
        tempo_features=tempo_features,
        structure_features=structure_features,
    )


def build_analyzed_track_artifact(
    track: RepositoryTrack,
    probe: AudioProbe,
    *,
    parameters_hash: str = DEFAULT_PARAMETERS_HASH,
    created_at_utc: str | None = None,
    analyzer_producer: str = ANALYZER_PRODUCER,
    analyzer_version: str = ANALYZER_VERSION,
    energy_features: EnergyFeatures | None = None,
    tempo_features: TempoFeatures | None = None,
    structure_features: StructureFeatures | None = None,
) -> dict[str, Any]:
    """Build an AnalyzedTrack artifact from repository identity and probe data."""

    duration_seconds = _duration_seconds(track, probe)
    source = _source_asset(track, probe, duration_seconds)
    has_signal_features = (
        energy_features is not None
        or tempo_features is not None
        or structure_features is not None
    )
    warnings = [PARTIAL_SIGNAL_WARNING if has_signal_features else FFPROBE_ONLY_WARNING]
    if probe.duration_seconds is None and track.duration_seconds is None:
        warnings.append("Duration was unavailable from both manifest and FFprobe; using 0.0 seconds.")
    if probe.sample_rate is None:
        warnings.append("Sample rate was unavailable from FFprobe.")
    if probe.channels is None:
        warnings.append("Channel count was unavailable from FFprobe.")
    if energy_features is not None:
        warnings.extend(energy_features.warnings)
    if tempo_features is not None:
        warnings.extend(tempo_features.warnings)
    if structure_features is not None:
        warnings.extend(structure_features.warnings)

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
        "tempo": _tempo_analysis(tempo_features),
        "key": {
            "tonic": "unknown",
            "mode": "unknown",
            "confidence": 0.0,
            "candidates": [],
        },
        "beatGrid": _beat_grid(tempo_features),
        "sections": _sections(structure_features),
        "energy": _energy_analysis(energy_features),
        "vocals": {
            "hasVocals": False,
            "confidence": 0.0,
            "regions": [],
        },
        "cuePoints": _cue_points(structure_features),
        "quality": {
            "overallConfidence": _overall_confidence(
                energy_features=energy_features,
                tempo_features=tempo_features,
                structure_features=structure_features,
            ),
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
    _set_if_present(ffprobe_metadata, "startTimeSeconds", probe.start_time_seconds)
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


def _energy_analysis(features: EnergyFeatures | None) -> dict[str, Any]:
    if features is not None:
        return build_energy_analysis(features)
    return {
        "globalEnergy": 0.0,
        "curve": [],
        "bassEnergyCurve": [],
        "onsetDensityCurve": [],
    }


def _tempo_analysis(features: TempoFeatures | None) -> dict[str, Any]:
    if features is not None:
        return build_tempo_analysis(features)
    return {
        "bpm": 140.0,
        "normalizedBpm": 140.0,
        "confidence": 0.0,
        "tempoClass": "straight",
        "candidates": [],
    }


def _beat_grid(features: TempoFeatures | None) -> dict[str, Any]:
    if features is not None:
        return build_beat_grid(features)
    return {
        "beats": [],
        "downbeats": [],
        "confidence": 0.0,
    }


def _sections(features: StructureFeatures | None) -> list[dict[str, Any]]:
    if features is not None:
        return build_sections(features)
    return []


def _cue_points(features: StructureFeatures | None) -> list[dict[str, Any]]:
    if features is not None:
        return build_cue_points(features)
    return []


def _overall_confidence(
    *,
    energy_features: EnergyFeatures | None,
    tempo_features: TempoFeatures | None,
    structure_features: StructureFeatures | None,
) -> float:
    if energy_features is None and tempo_features is None and structure_features is None:
        return 0.1

    confidence_values: list[float] = []
    if energy_features is not None:
        confidence_values.append(0.55 if energy_features.global_energy > 0 else 0.15)
    if tempo_features is not None:
        confidence_values.append(tempo_features.confidence)
        confidence_values.append(tempo_features.beat_grid_confidence)
    if structure_features is not None and structure_features.sections:
        confidence_values.append(max(float(section["confidence"]) for section in structure_features.sections))
    elif structure_features is not None:
        confidence_values.append(0.2)

    if not confidence_values:
        return 0.1
    return round(max(0.1, min(sum(confidence_values) / len(confidence_values), 0.8)), 6)


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
    waveform_artifact_path: Path | None,
    error: dict[str, str],
) -> BatchTrackResult:
    return BatchTrackResult(
        track_id=track.track_id,
        status=TRACK_STATUS_FAILED,
        artifact_path=artifact_path,
        waveform_path=waveform_artifact_path,
        reason=error["code"],
        message=error["message"],
        error=error,
    )


def _cache_error_to_dict(track: RepositoryTrack, error: CacheError) -> dict[str, str]:
    payload = error.to_dict()
    payload["trackId"] = track.track_id
    payload["sourceUri"] = track.source_uri
    return payload


def _analysis_error_to_dict(track: RepositoryTrack, error: Any) -> dict[str, str]:
    if hasattr(error, "to_dict"):
        payload = error.to_dict()
    else:
        payload = {"code": "analysis_error", "message": str(error)}
    payload.setdefault("code", "analysis_error")
    payload.setdefault("message", str(error))
    payload["trackId"] = track.track_id
    payload["sourceUri"] = track.source_uri
    return payload


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
