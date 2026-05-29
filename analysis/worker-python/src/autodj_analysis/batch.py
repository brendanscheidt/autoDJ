"""Batch analysis workflow and artifact construction helpers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
import time
from typing import Any, Callable

from . import __version__
from .audio_io import AudioLoadError, DecodedAudio
from .backends.base import (
    AnalysisContext,
    BackendExecutionError,
    CandidateProvenance,
    FeatureBundle,
    KeyCandidateResult,
    KeyDetectorBackend,
    SectionBackend,
    SectionCandidateResult,
)
from .backends.current_signal import CURRENT_SIGNAL_BACKEND
from .backends.dubstep_phrase_hybrid import DUBSTEP_PHRASE_HYBRID_BACKEND, DubstepPhraseHybridBackend
from .backends.keyfinder_key import KEYFINDER_KEY_BACKEND, KeyFinderKeyBackend
from .backends.madmom_key import MADMOM_KEY_BACKEND, MadmomKeyBackend
from .backends.selected_key import SELECTED_KEY_BACKEND, SelectedKeyBackend
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
from .canonical_audio import canonical_audio_paths
from .features import EnergyFeatures, FeatureExtractionError, build_energy_analysis
from .manifest import RepositoryManifest, RepositoryTrack, load_repository_manifest
from .probe import AudioProbe, ProbeError, ProbeRunner, probe_audio
from .structure import (
    StructureExtractionError,
    StructureFeatures,
    build_cue_points,
    build_sections,
)
from .tempo import TempoExtractionError, TempoFeatures, build_beat_grid, build_tempo_analysis
from .waveform import WaveformError, write_waveform_artifact


ANALYZER_PRODUCER = "autodj_analysis.signal"
ANALYZER_VERSION = __version__
SELECTED_SECTION_BACKEND = DUBSTEP_PHRASE_HYBRID_BACKEND
DEFAULT_PARAMETERS_HASH = "sha256:signal-v3-waveform-energy-tempo-key-dubstep-phrase-hybrid-v1"
DEFAULT_KEY_ANALYSIS_EXCERPT_SECONDS = 60.0
FFPROBE_ONLY_WARNING = (
    "Only FFprobe container/stream metadata was analyzed; BPM, key, beat grid, "
    "sections, energy, vocals, stems, and cue points are low-confidence placeholders."
)
PARTIAL_SIGNAL_WARNING = (
    "Signal analysis populated waveform, energy, tempo, beat grid, key, sections, "
    "and cue candidates where evidence was available; vocals, stems, and downbeats "
    "remain low-confidence or empty placeholders."
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
    key_result: KeyCandidateResult | None = None
    section_result: SectionCandidateResult | None = None
    debug_waveform_artifact: dict[str, Any] | None = None


SignalAnalyzer = Callable[[RepositoryTrack, ArtifactIdentity, str], SignalAnalysisResult]
SectionBackendFactory = Callable[[], SectionBackend]


@dataclass(frozen=True)
class BatchTrackResult:
    track_id: str
    status: str
    artifact_path: Path | None = None
    waveform_path: Path | None = None
    reason: str | None = None
    message: str | None = None
    error: dict[str, str] | None = None
    processing_seconds: float | None = None

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
        if self.processing_seconds is not None:
            payload["processingSeconds"] = self.processing_seconds
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
    processing_seconds: float = 0.0
    workers: int = 1
    section_backend: str = SELECTED_SECTION_BACKEND
    key_backend: str = SELECTED_KEY_BACKEND
    debug_waveform_points: int | None = None

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
            "processingSeconds": self.processing_seconds,
            "workers": self.workers,
            "sectionBackend": self.section_backend,
            "keyBackend": self.key_backend,
            "debugWaveformPoints": self.debug_waveform_points,
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
    section_backend: str = SELECTED_SECTION_BACKEND,
    key_backend: str = SELECTED_KEY_BACKEND,
    section_backend_factory: SectionBackendFactory | None = None,
    canonical_audio_root: str | Path | None = None,
    workers: int = 1,
    debug_waveform_points: int | None = None,
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
        section_backend=section_backend,
        key_backend=key_backend,
        section_backend_factory=section_backend_factory,
        canonical_audio_root=canonical_audio_root,
        workers=workers,
        debug_waveform_points=debug_waveform_points,
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
    section_backend: str = SELECTED_SECTION_BACKEND,
    key_backend: str = SELECTED_KEY_BACKEND,
    section_backend_factory: SectionBackendFactory | None = None,
    canonical_audio_root: str | Path | None = None,
    workers: int = 1,
    debug_waveform_points: int | None = None,
) -> BatchAnalysisResult:
    """Analyze every track from a parsed repository manifest.

    Per-track probe/cache failures are converted into failed track results so
    later tracks can still be processed. Manifest-level load/parse failures are
    intentionally left to ``analyze_repository_manifest`` callers.
    """

    cache_root_path = Path(cache_root)
    started_at = time.perf_counter()
    canonical_audio_root_path = Path(canonical_audio_root) if canonical_audio_root is not None else None
    effective_parameters_hash = _effective_parameters_hash(
        parameters_hash,
        section_backend=section_backend,
        key_backend=key_backend,
        canonical_audio_root=canonical_audio_root_path,
    )
    tracks = _analyze_manifest_tracks(
        manifest.tracks,
        cache_root_path,
        ffprobe_path=ffprobe_path,
        force=force,
        parameters_hash=effective_parameters_hash,
        probe_runner=probe_runner,
        signal_analyzer=signal_analyzer,
        section_backend=section_backend,
        key_backend=key_backend,
        section_backend_factory=section_backend_factory,
        canonical_audio_root=canonical_audio_root_path,
        workers=workers,
        debug_waveform_points=debug_waveform_points,
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
        processing_seconds=_elapsed(started_at),
        workers=max(1, int(workers)),
        section_backend=section_backend,
        key_backend=key_backend,
        debug_waveform_points=debug_waveform_points,
    )


def _analyze_manifest_tracks(
    tracks: tuple[RepositoryTrack, ...],
    cache_root: Path,
    *,
    ffprobe_path: str | Path,
    force: bool,
    parameters_hash: str,
    probe_runner: ProbeRunner | None,
    signal_analyzer: SignalAnalyzer | None,
    section_backend: str,
    key_backend: str,
    section_backend_factory: SectionBackendFactory | None,
    canonical_audio_root: Path | None,
    workers: int,
    debug_waveform_points: int | None,
) -> tuple[BatchTrackResult, ...]:
    worker_count = max(1, int(workers))
    if worker_count == 1 or len(tracks) <= 1:
        return tuple(
            _analyze_manifest_track(
                track,
                cache_root,
                ffprobe_path=ffprobe_path,
                force=force,
                parameters_hash=parameters_hash,
                probe_runner=probe_runner,
                signal_analyzer=signal_analyzer,
                section_backend=section_backend,
                key_backend=key_backend,
                section_backend_factory=section_backend_factory,
                canonical_audio_root=canonical_audio_root,
                debug_waveform_points=debug_waveform_points,
            )
            for track in tracks
        )

    ordered_results: list[BatchTrackResult | None] = [None] * len(tracks)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                _analyze_manifest_track,
                track,
                cache_root,
                ffprobe_path=ffprobe_path,
                force=force,
                parameters_hash=parameters_hash,
                probe_runner=probe_runner,
                signal_analyzer=signal_analyzer,
                section_backend=section_backend,
                key_backend=key_backend,
                section_backend_factory=section_backend_factory,
                canonical_audio_root=canonical_audio_root,
                debug_waveform_points=debug_waveform_points,
            ): index
            for index, track in enumerate(tracks)
        }
        for future in as_completed(futures):
            ordered_results[futures[future]] = future.result()

    return tuple(result for result in ordered_results if result is not None)


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


def _effective_parameters_hash(
    parameters_hash: str,
    *,
    section_backend: str,
    key_backend: str,
    canonical_audio_root: Path | None,
) -> str:
    hash_parts = [parameters_hash]
    if section_backend != SELECTED_SECTION_BACKEND:
        hash_parts.append(f"section-backend-{section_backend}")
    if key_backend != SELECTED_KEY_BACKEND:
        hash_parts.append(f"key-backend-{key_backend}")
    if canonical_audio_root is not None:
        hash_parts.append("canonical-pcm-v1")
    return "+".join(hash_parts)


def _analyze_manifest_track(
    track: RepositoryTrack,
    cache_root: Path,
    *,
    ffprobe_path: str | Path,
    force: bool,
    parameters_hash: str,
    probe_runner: ProbeRunner | None,
    signal_analyzer: SignalAnalyzer | None,
    section_backend: str,
    key_backend: str,
    section_backend_factory: SectionBackendFactory | None,
    canonical_audio_root: Path | None,
    debug_waveform_points: int | None,
) -> BatchTrackResult:
    started_at = time.perf_counter()
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
        debug_waveform_path = artifact_path.parent / "debug-waveform.json"
        if (
            freshness.is_fresh
            and debug_waveform_points is not None
            and debug_waveform_points > 0
            and not debug_waveform_path.exists()
        ):
            freshness = replace(
                freshness,
                is_fresh=False,
                reason="debug_waveform_artifact_missing",
                message="Debug waveform artifact does not exist",
            )

        if freshness.is_fresh:
            return BatchTrackResult(
                track_id=track.track_id,
                status=TRACK_STATUS_SKIPPED,
                artifact_path=artifact_path,
                waveform_path=waveform_artifact_path,
                reason=freshness.reason,
                message=freshness.message,
                processing_seconds=_elapsed(started_at),
            )

        probe = probe_audio(
            track.source_path,
            ffprobe_path=ffprobe_path,
            source_uri=track.source_uri,
            track_id=track.track_id,
            runner=probe_runner,
        )
        analysis_track = _track_for_analysis_audio(track, canonical_audio_root)
        artifact_track = _track_with_analysis_audio_metadata(track, canonical_audio_root)
        created_at_utc = _utc_now_iso()
        if signal_analyzer is None:
            signal_result = analyze_track_signal(
                analysis_track,
                identity,
                created_at_utc,
                section_backend=section_backend,
                key_backend=key_backend,
                section_backend_factory=section_backend_factory,
                temp_dir=artifact_path.parent / "section-backend-work",
                ffprobe_start_time_seconds=probe.start_time_seconds,
                debug_waveform_points=debug_waveform_points,
            )
        else:
            signal_result = signal_analyzer(analysis_track, identity, created_at_utc)
        artifact = build_analyzed_track_artifact(
            artifact_track,
            probe,
            parameters_hash=parameters_hash,
            created_at_utc=created_at_utc,
            analyzer_producer=identity.analyzer_producer,
            analyzer_version=identity.analyzer_version,
            energy_features=signal_result.energy_features,
            tempo_features=signal_result.tempo_features,
            structure_features=signal_result.structure_features,
            key_result=signal_result.key_result,
            section_result=signal_result.section_result,
        )
        write_json_atomic(artifact_path, artifact)
        write_waveform_artifact(cache_root, track.track_id, signal_result.waveform_artifact)
        if signal_result.debug_waveform_artifact is not None:
            write_json_atomic(artifact_path.parent / "debug-waveform.json", signal_result.debug_waveform_artifact)

        return BatchTrackResult(
            track_id=track.track_id,
            status=TRACK_STATUS_ANALYZED,
            artifact_path=artifact_path,
            waveform_path=waveform_artifact_path,
            reason=freshness.reason,
            message=freshness.message,
            processing_seconds=_elapsed(started_at),
        )
    except ProbeError as exc:
        return _failed_track_result(
            track,
            artifact_path,
            waveform_artifact_path,
            exc.to_dict(),
            processing_seconds=_elapsed(started_at),
        )
    except (
        AudioLoadError,
        WaveformError,
        FeatureExtractionError,
        TempoExtractionError,
        StructureExtractionError,
    ) as exc:
        return _failed_track_result(
            track,
            artifact_path,
            waveform_artifact_path,
            _analysis_error_to_dict(track, exc),
            processing_seconds=_elapsed(started_at),
        )
    except CacheError as exc:
        return _failed_track_result(
            track,
            artifact_path,
            waveform_artifact_path,
            _cache_error_to_dict(track, exc),
            processing_seconds=_elapsed(started_at),
        )
    except Exception as exc:
        return _failed_track_result(
            track,
            artifact_path,
            waveform_artifact_path,
            _analysis_error_to_dict(track, exc),
            processing_seconds=_elapsed(started_at),
        )


def analyze_track_signal(
    track: RepositoryTrack,
    identity: ArtifactIdentity,
    created_at_utc: str,
    *,
    section_backend: str = SELECTED_SECTION_BACKEND,
    key_backend: str = SELECTED_KEY_BACKEND,
    section_backend_factory: SectionBackendFactory | None = None,
    temp_dir: str | Path | None = None,
    ffprobe_start_time_seconds: float | None = None,
    debug_waveform_points: int | None = None,
) -> SignalAnalysisResult:
    """Decode audio and compute real signal-derived analysis features."""

    from .backends.current_signal import CurrentSignalBackend

    current_backend = CurrentSignalBackend()
    selected_section_backend = section_backend.strip() or SELECTED_SECTION_BACKEND
    audio = current_backend.load_track_audio(track)
    signal_result = current_backend.analyze_decoded_signal(track, identity, created_at_utc, audio)
    key_context = AnalysisContext(
        track_id=track.track_id,
        source_path=track.source_path,
        analysis_audio_path=track.source_path,
        duration_seconds=audio.duration_seconds,
        ffprobe_start_time_seconds=ffprobe_start_time_seconds,
        source_content_hash=identity.source_content_hash,
    )
    debug_waveform_artifact = None
    if debug_waveform_points is not None and debug_waveform_points > 0:
        debug_waveform_artifact = current_backend.build_debug_waveform(
            audio,
            key_context,
            created_at_utc=created_at_utc,
            target_point_count=debug_waveform_points,
        )
    key_context, key_excerpt_warnings = _key_analysis_context(
        track,
        identity,
        audio,
        temp_dir=Path(temp_dir) if temp_dir is not None else None,
        ffprobe_start_time_seconds=ffprobe_start_time_seconds,
    )
    key_result = _select_key_result(
        audio=audio,
        context=key_context,
        key_backend=key_backend,
        extra_warnings=key_excerpt_warnings,
    )
    if selected_section_backend == CURRENT_SIGNAL_BACKEND:
        return replace(
            signal_result,
            key_result=key_result,
            section_result=current_backend.section_result_from_features(signal_result.structure_features),
            debug_waveform_artifact=debug_waveform_artifact,
        )
    work_dir = Path(temp_dir) if temp_dir is not None else None
    analysis_audio_path, audio_warnings = _write_section_analysis_audio(audio, work_dir)
    context = AnalysisContext(
        track_id=track.track_id,
        source_path=track.source_path,
        analysis_audio_path=analysis_audio_path,
        duration_seconds=audio.duration_seconds,
        ffprobe_start_time_seconds=ffprobe_start_time_seconds,
        temp_dir=work_dir,
        source_content_hash=identity.source_content_hash,
    )
    section_result = _select_semantic_section_result(
        section_backend=selected_section_backend,
        section_backend_factory=section_backend_factory,
        current_backend=current_backend,
        audio=audio,
        context=context,
        energy_features=signal_result.energy_features,
        tempo_features=signal_result.tempo_features,
        structure_features=signal_result.structure_features,
        extra_warnings=audio_warnings,
    )
    return replace(
        signal_result,
        key_result=key_result,
        section_result=section_result,
        debug_waveform_artifact=debug_waveform_artifact,
    )


def _track_for_analysis_audio(track: RepositoryTrack, canonical_audio_root: Path | None) -> RepositoryTrack:
    if canonical_audio_root is None:
        return track
    paths = canonical_audio_paths(canonical_audio_root, track.track_id)
    if not paths.audio_path.exists():
        raise AudioLoadError(
            "canonical_audio_missing",
            f"Canonical PCM audio does not exist for track '{track.track_id}': {paths.audio_path}",
            source_uri=track.source_uri,
            track_id=track.track_id,
        )
    return replace(
        track,
        source_path=paths.audio_path,
        provider_metadata=_provider_metadata_with_canonical_audio(track, paths.audio_path, paths.metadata_path),
    )


def _track_with_analysis_audio_metadata(track: RepositoryTrack, canonical_audio_root: Path | None) -> RepositoryTrack:
    if canonical_audio_root is None:
        return track
    paths = canonical_audio_paths(canonical_audio_root, track.track_id)
    return replace(
        track,
        provider_metadata=_provider_metadata_with_canonical_audio(track, paths.audio_path, paths.metadata_path),
    )


def _provider_metadata_with_canonical_audio(
    track: RepositoryTrack,
    canonical_path: Path,
    metadata_path: Path,
) -> dict[str, Any]:
    provider_metadata = dict(track.provider_metadata)
    provider_metadata["autodjAnalysisAudio"] = {
        "timelinePolicy": "shared-canonical-pcm",
        "canonicalPath": str(canonical_path),
        "canonicalMetadataPath": str(metadata_path),
    }
    return provider_metadata


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
    key_result: KeyCandidateResult | None = None,
    section_result: SectionCandidateResult | None = None,
) -> dict[str, Any]:
    """Build an AnalyzedTrack artifact from repository identity and probe data."""

    duration_seconds = _duration_seconds(track, probe)
    source = _source_asset(track, probe, duration_seconds)
    has_signal_features = (
        energy_features is not None
        or tempo_features is not None
        or structure_features is not None
        or key_result is not None
        or section_result is not None
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
    if structure_features is not None and section_result is None:
        warnings.extend(structure_features.warnings)
    if key_result is not None:
        warnings.extend(key_result.provenance.warnings)
        if key_result.status != "ok" and key_result.error is not None:
            warnings.append(key_result.error.message)
    if section_result is not None:
        warnings.extend(section_result.provenance.warnings)
        if section_result.status != "ok" and section_result.error is not None:
            warnings.append(section_result.error.message)

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
        "key": _key_analysis(key_result),
        "beatGrid": _beat_grid(tempo_features),
        "sections": _sections(section_result=section_result, structure_features=structure_features),
        "energy": _energy_analysis(energy_features),
        "vocals": {
            "hasVocals": False,
            "confidence": 0.0,
            "regions": [],
        },
        "cuePoints": _cue_points(section_result=section_result, structure_features=structure_features),
        "quality": {
            "overallConfidence": _overall_confidence(
                energy_features=energy_features,
                tempo_features=tempo_features,
                structure_features=structure_features,
                key_result=key_result,
                section_result=section_result,
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


def _key_analysis(key_result: KeyCandidateResult | None) -> dict[str, Any]:
    if key_result is None:
        return {
            "tonic": "unknown",
            "mode": "unknown",
            "confidence": 0.0,
            "candidates": [],
        }
    payload = key_result.to_dict()
    if key_result.ok:
        return payload
    return {
        "tonic": "unknown",
        "mode": "unknown",
        "confidence": 0.0,
        "candidates": [],
        "status": payload["status"],
        "provenance": payload["provenance"],
        "error": payload.get("error"),
    }


def _beat_grid(features: TempoFeatures | None) -> dict[str, Any]:
    if features is not None:
        return build_beat_grid(features)
    return {
        "beats": [],
        "downbeats": [],
        "confidence": 0.0,
    }


def _sections(
    *,
    section_result: SectionCandidateResult | None,
    structure_features: StructureFeatures | None,
) -> list[dict[str, Any]]:
    if section_result is not None:
        return [section.to_dict() for section in section_result.sections]
    if structure_features is not None:
        return build_sections(structure_features)
    return []


def _cue_points(
    *,
    section_result: SectionCandidateResult | None,
    structure_features: StructureFeatures | None,
) -> list[dict[str, Any]]:
    if section_result is not None:
        return [dict(cue) for cue in section_result.cue_points]
    if structure_features is not None:
        return build_cue_points(structure_features)
    return []


def _overall_confidence(
    *,
    energy_features: EnergyFeatures | None,
    tempo_features: TempoFeatures | None,
    structure_features: StructureFeatures | None,
    key_result: KeyCandidateResult | None,
    section_result: SectionCandidateResult | None,
) -> float:
    if (
        energy_features is None
        and tempo_features is None
        and structure_features is None
        and key_result is None
        and section_result is None
    ):
        return 0.1

    confidence_values: list[float] = []
    if energy_features is not None:
        confidence_values.append(0.55 if energy_features.global_energy > 0 else 0.15)
    if tempo_features is not None:
        confidence_values.append(tempo_features.confidence)
        confidence_values.append(tempo_features.beat_grid_confidence)
    if key_result is not None and key_result.status == "ok":
        confidence_values.append(key_result.confidence)
    elif key_result is not None:
        confidence_values.append(0.15)
    if section_result is None and structure_features is not None and structure_features.sections:
        confidence_values.append(max(float(section["confidence"]) for section in structure_features.sections))
    elif section_result is None and structure_features is not None:
        confidence_values.append(0.2)
    if section_result is not None and section_result.status == "ok" and section_result.sections:
        confidence_values.append(max(section.confidence for section in section_result.sections))
    elif section_result is not None:
        confidence_values.append(0.15)

    if not confidence_values:
        return 0.1
    return round(max(0.1, min(sum(confidence_values) / len(confidence_values), 0.8)), 6)


def _select_key_result(
    *,
    audio: DecodedAudio,
    context: AnalysisContext,
    key_backend: str = SELECTED_KEY_BACKEND,
    key_backend_factory: Callable[[], KeyDetectorBackend] | None = None,
    extra_warnings: tuple[str, ...] = (),
) -> KeyCandidateResult:
    selected_name = key_backend.strip() or SELECTED_KEY_BACKEND
    try:
        backend = key_backend_factory() if key_backend_factory is not None else _default_key_backend(selected_name)
        if not isinstance(backend, KeyDetectorBackend):
            raise TypeError(f"selected key backend '{selected_name}' does not implement KeyDetectorBackend")
        return _with_key_warnings(backend.analyze_key(audio, context), extra_warnings)
    except Exception as exc:
        return _with_key_warnings(
            KeyCandidateResult(
                status="failed",
                provenance=CandidateProvenance(
                    backend_name=selected_name,
                    backend_version=__version__,
                ),
                error=BackendExecutionError(
                    code="selected_key_failed",
                    message=str(exc) or exc.__class__.__name__,
                    backend_name=selected_name,
                    details={"exceptionType": exc.__class__.__name__},
                ),
            ),
            extra_warnings,
        )


def _default_key_backend(key_backend: str) -> KeyDetectorBackend:
    if key_backend == SELECTED_KEY_BACKEND:
        return SelectedKeyBackend()
    if key_backend == KEYFINDER_KEY_BACKEND:
        return KeyFinderKeyBackend()
    if key_backend == MADMOM_KEY_BACKEND:
        return MadmomKeyBackend()
    raise ValueError(
        "unsupported key backend "
        f"'{key_backend}'; expected '{SELECTED_KEY_BACKEND}', '{KEYFINDER_KEY_BACKEND}', or '{MADMOM_KEY_BACKEND}'"
    )


def _key_analysis_context(
    track: RepositoryTrack,
    identity: ArtifactIdentity,
    audio: DecodedAudio,
    *,
    temp_dir: Path | None,
    ffprobe_start_time_seconds: float | None,
) -> tuple[AnalysisContext, tuple[str, ...]]:
    base_context = AnalysisContext(
        track_id=track.track_id,
        source_path=track.source_path,
        analysis_audio_path=track.source_path,
        duration_seconds=audio.duration_seconds,
        ffprobe_start_time_seconds=ffprobe_start_time_seconds,
        temp_dir=temp_dir,
        source_content_hash=identity.source_content_hash,
    )
    if temp_dir is None or audio.duration_seconds <= DEFAULT_KEY_ANALYSIS_EXCERPT_SECONDS:
        return base_context, ()

    sample_count = int(len(audio.samples))
    max_samples = int(round(DEFAULT_KEY_ANALYSIS_EXCERPT_SECONDS * audio.sample_rate))
    if sample_count <= max_samples:
        return base_context, ()

    start_sample = max(0, (sample_count - max_samples) // 2)
    end_sample = min(sample_count, start_sample + max_samples)
    excerpt_path = temp_dir / "key-analysis-excerpt.wav"
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        from .dependencies import require_optional_dependency

        soundfile = require_optional_dependency("soundfile", module_name="soundfile", install_extra="analysis")
        soundfile.write(str(excerpt_path), audio.samples[start_sample:end_sample], audio.sample_rate)
    except Exception as exc:
        return base_context, (
            "Could not write bounded key-analysis excerpt; using full source audio for key detection: "
            f"{exc}",
        )

    excerpt_seconds = (end_sample - start_sample) / audio.sample_rate
    return (
        AnalysisContext(
            track_id=track.track_id,
            source_path=track.source_path,
            analysis_audio_path=excerpt_path,
            duration_seconds=excerpt_seconds,
            ffprobe_start_time_seconds=ffprobe_start_time_seconds,
            temp_dir=temp_dir,
            source_content_hash=identity.source_content_hash,
        ),
        (
            f"Key detection used a bounded {excerpt_seconds:.1f}s middle excerpt "
            "to keep batch analysis latency predictable.",
        ),
    )


def _with_key_warnings(
    key_result: KeyCandidateResult,
    warnings: tuple[str, ...],
) -> KeyCandidateResult:
    if not warnings:
        return key_result
    provenance = replace(
        key_result.provenance,
        warnings=tuple((*key_result.provenance.warnings, *warnings)),
    )
    return replace(key_result, provenance=provenance)


def _select_semantic_section_result(
    *,
    section_backend: str,
    section_backend_factory: SectionBackendFactory | None,
    current_backend: Any,
    audio: DecodedAudio,
    context: AnalysisContext,
    energy_features: EnergyFeatures,
    tempo_features: TempoFeatures,
    structure_features: StructureFeatures,
    extra_warnings: tuple[str, ...] = (),
) -> SectionCandidateResult:
    fallback = current_backend.section_result_from_features(structure_features)
    fallback_backend = fallback.provenance.backend_name
    selected_name = section_backend.strip() or SELECTED_SECTION_BACKEND

    if selected_name == fallback_backend:
        return _with_section_warnings(fallback, extra_warnings)

    beat_grid = current_backend.beat_grid_result_from_features(tempo_features)
    features = FeatureBundle(energy=energy_features, extras={"tempoFeatures": tempo_features})
    try:
        backend = section_backend_factory() if section_backend_factory is not None else _default_section_backend(selected_name)
    except Exception as exc:
        return _with_section_warnings(
            fallback,
            (
                *extra_warnings,
                f"Selected semantic section backend '{selected_name}' could not be constructed; "
                f"falling back to '{fallback_backend}' rough sections: {exc}",
            ),
        )

    try:
        result = backend.analyze_sections(audio, features, beat_grid, context)
    except Exception as exc:
        return _with_section_warnings(
            fallback,
            (
                *extra_warnings,
                f"Selected semantic section backend '{selected_name}' raised {type(exc).__name__}; "
                f"falling back to '{fallback_backend}' rough sections: {exc}",
            ),
        )

    if result.status == "ok" and result.sections:
        return _with_section_warnings(result, extra_warnings)

    reason = f"status={result.status}, sections={len(result.sections)}"
    if result.error is not None:
        reason = f"{reason}, error={result.error.message}"
    return _with_section_warnings(
        fallback,
        (
            *extra_warnings,
            f"Selected semantic section backend '{selected_name}' did not produce usable sections "
            f"({reason}); falling back to '{fallback_backend}' rough sections.",
        ),
    )


def _default_section_backend(section_backend: str) -> SectionBackend:
    if section_backend == DUBSTEP_PHRASE_HYBRID_BACKEND:
        return DubstepPhraseHybridBackend()
    if section_backend == CURRENT_SIGNAL_BACKEND:
        from .backends.current_signal import CurrentSignalBackend

        return CurrentSignalBackend()
    raise ValueError(
        "unsupported section backend "
        f"'{section_backend}'; expected '{DUBSTEP_PHRASE_HYBRID_BACKEND}' or '{CURRENT_SIGNAL_BACKEND}'"
    )


def _with_section_warnings(
    section_result: SectionCandidateResult,
    warnings: tuple[str, ...],
) -> SectionCandidateResult:
    if not warnings:
        return section_result
    provenance = replace(
        section_result.provenance,
        warnings=tuple((*section_result.provenance.warnings, *warnings)),
    )
    return replace(section_result, provenance=provenance)


def _write_section_analysis_audio(
    audio: DecodedAudio,
    temp_dir: Path | None,
) -> tuple[Path, tuple[str, ...]]:
    if temp_dir is None:
        return audio.source_path, (
            "Semantic section backend used the source audio file because no analysis work directory was provided.",
        )

    analysis_audio_path = temp_dir / "analysis.wav"
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        from .dependencies import require_optional_dependency

        soundfile = require_optional_dependency("soundfile", module_name="soundfile", install_extra="analysis")
        soundfile.write(str(analysis_audio_path), audio.samples, audio.sample_rate)
        return analysis_audio_path, ()
    except Exception as exc:
        return audio.source_path, (
            "Could not write normalized analysis WAV for semantic section backend; "
            f"using source audio file instead: {exc}",
        )


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
    *,
    processing_seconds: float | None = None,
) -> BatchTrackResult:
    return BatchTrackResult(
        track_id=track.track_id,
        status=TRACK_STATUS_FAILED,
        artifact_path=artifact_path,
        waveform_path=waveform_artifact_path,
        reason=error["code"],
        message=error["message"],
        error=error,
        processing_seconds=processing_seconds,
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


def _elapsed(started_at: float) -> float:
    return round(max(0.0, time.perf_counter() - started_at), 6)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
