"""Incumbent AutoDJ signal-analysis backend adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
import time
from typing import Any, TYPE_CHECKING

from .. import __version__
from ..audio_io import DecodedAudio, load_audio
from ..cache import ArtifactIdentity
from ..debug_waveform import build_debug_waveform_artifact
from ..features import EnergyFeatures, compute_energy_features
from ..manifest import RepositoryTrack
from ..structure import StructureFeatures, compute_structure_features
from ..tempo import TempoFeatures, compute_tempo_features
from ..waveform import build_waveform_artifact
from .base import (
    AnalysisContext,
    BackendExecutionError,
    BeatGridCandidateResult,
    BeatMarker,
    CandidateProvenance,
    FeatureBundle,
    SectionCandidate,
    SectionCandidateResult,
    TempoCandidate,
    TempoCandidateResult,
)
from .registry import BackendRegistry

if TYPE_CHECKING:
    from ..batch import SignalAnalysisResult


CURRENT_SIGNAL_BACKEND = "current-autodj-signal"
CURRENT_SIGNAL_MODEL_NAME = "autodj-signal-heuristics"
CURRENT_SIGNAL_MODEL_VERSION = "signal-v1-waveform-energy-tempo-structure-v1"
_DEPENDENCY_PACKAGES = ("numpy", "scipy", "librosa", "soundfile")


@dataclass(frozen=True)
class CurrentSignalCandidateResults:
    """Contract-level candidate outputs produced from incumbent features."""

    tempo: TempoCandidateResult
    beat_grid: BeatGridCandidateResult
    sections: SectionCandidateResult
    energy_features: EnergyFeatures | None = None


class CurrentSignalBackend:
    """Adapter for the current hand-built waveform, tempo, and section pipeline."""

    name = CURRENT_SIGNAL_BACKEND

    def __init__(
        self,
        *,
        audio_loader: Callable[..., DecodedAudio] = load_audio,
        waveform_builder: Callable[..., dict[str, Any]] = build_waveform_artifact,
        debug_waveform_builder: Callable[..., dict[str, Any]] = build_debug_waveform_artifact,
        energy_extractor: Callable[..., EnergyFeatures] = compute_energy_features,
        tempo_extractor: Callable[..., TempoFeatures] = compute_tempo_features,
        structure_extractor: Callable[..., StructureFeatures] = compute_structure_features,
        backend_version: str = __version__,
    ) -> None:
        self._audio_loader = audio_loader
        self._waveform_builder = waveform_builder
        self._debug_waveform_builder = debug_waveform_builder
        self._energy_extractor = energy_extractor
        self._tempo_extractor = tempo_extractor
        self._structure_extractor = structure_extractor
        self._backend_version = backend_version

    def as_signal_analyzer(self) -> Callable[[RepositoryTrack, ArtifactIdentity, str], "SignalAnalysisResult"]:
        """Return a batch-compatible signal analyzer callable."""

        return self.analyze_signal

    def analyze_signal(
        self,
        track: RepositoryTrack,
        identity: ArtifactIdentity,
        created_at_utc: str,
    ) -> "SignalAnalysisResult":
        """Decode audio and compute incumbent features for legacy artifacts."""

        from ..batch import SignalAnalysisResult

        decoded_audio = self.load_track_audio(track)
        waveform_artifact = self._waveform_builder(
            track.track_id,
            decoded_audio,
            analyzer_producer=identity.analyzer_producer,
            analyzer_version=identity.analyzer_version,
            source_content_hash=identity.source_content_hash or "",
            parameters_hash=identity.parameters_hash or "",
            created_at_utc=created_at_utc,
        )
        energy_features = self._energy_extractor(decoded_audio)
        tempo_features = self._tempo_extractor(decoded_audio)
        structure_features = self._structure_extractor(
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

    def analyze_candidates(
        self,
        audio: DecodedAudio,
        context: AnalysisContext,
    ) -> CurrentSignalCandidateResults:
        """Compute incumbent features and expose them through candidate contracts."""

        energy_features = self._energy_extractor(audio)
        start = time.perf_counter()
        tempo_features = self._tempo_extractor(audio)
        tempo_elapsed = _elapsed(start)
        start = time.perf_counter()
        structure_features = self._structure_extractor(
            energy_features,
            tempo_features=tempo_features,
            duration_seconds=context.duration_seconds,
        )
        section_elapsed = _elapsed(start)

        return CurrentSignalCandidateResults(
            tempo=self.tempo_result_from_features(tempo_features, processing_seconds=tempo_elapsed),
            beat_grid=self.beat_grid_result_from_features(tempo_features, processing_seconds=tempo_elapsed),
            sections=self.section_result_from_features(
                structure_features,
                processing_seconds=section_elapsed,
            ),
            energy_features=energy_features,
        )

    def analyze_tempo(self, audio: DecodedAudio, context: AnalysisContext) -> TempoCandidateResult:
        del context
        start = time.perf_counter()
        try:
            features = self._tempo_extractor(audio)
        except Exception as exc:
            return TempoCandidateResult(
                status=_status_for_error(exc),
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=_backend_error(exc, backend_name=self.name),
            )
        return self.tempo_result_from_features(features, processing_seconds=_elapsed(start))

    def analyze_beat_grid(
        self,
        audio: DecodedAudio,
        tempo: TempoCandidateResult,
        context: AnalysisContext,
    ) -> BeatGridCandidateResult:
        del context
        if not tempo.ok:
            return BeatGridCandidateResult(
                status="failed",
                provenance=self._provenance(parameters={"tempoStatus": tempo.status}),
                error=BackendExecutionError(
                    code="tempo_result_not_ok",
                    message="Beat-grid analysis requires an ok tempo result.",
                    backend_name=self.name,
                ),
            )

        start = time.perf_counter()
        try:
            features = self._tempo_extractor(audio)
        except Exception as exc:
            return BeatGridCandidateResult(
                status=_status_for_error(exc),
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=_backend_error(exc, backend_name=self.name),
            )
        return self.beat_grid_result_from_features(features, processing_seconds=_elapsed(start))

    def analyze_sections(
        self,
        audio: DecodedAudio,
        features: FeatureBundle,
        beat_grid: BeatGridCandidateResult,
        context: AnalysisContext,
    ) -> SectionCandidateResult:
        del beat_grid
        start = time.perf_counter()
        try:
            energy_features = (
                features.energy
                if isinstance(features.energy, EnergyFeatures)
                else self._energy_extractor(audio)
            )
            tempo_features = features.extras.get("tempoFeatures")
            if not isinstance(tempo_features, TempoFeatures):
                tempo_features = None
            structure_features = self._structure_extractor(
                energy_features,
                tempo_features=tempo_features,
                duration_seconds=context.duration_seconds,
            )
        except Exception as exc:
            return SectionCandidateResult(
                status=_status_for_error(exc),
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=_backend_error(exc, backend_name=self.name),
            )
        return self.section_result_from_features(structure_features, processing_seconds=_elapsed(start))

    def load_track_audio(self, track: RepositoryTrack) -> DecodedAudio:
        if _uses_canonical_timeline(track):
            return self._audio_loader(
                track.source_path,
                target_sample_rate=None,
                source_uri=track.source_uri,
                track_id=track.track_id,
            )
        return self._audio_loader(
            track.source_path,
            source_uri=track.source_uri,
            track_id=track.track_id,
        )

    def context_for_track(
        self,
        track: RepositoryTrack,
        identity: ArtifactIdentity,
        audio: DecodedAudio,
        *,
        ffprobe_start_time_seconds: float | None = None,
        temp_dir: str | Path | None = None,
    ) -> AnalysisContext:
        return AnalysisContext(
            track_id=track.track_id,
            source_path=track.source_path,
            analysis_audio_path=audio.source_path,
            duration_seconds=audio.duration_seconds,
            ffprobe_start_time_seconds=ffprobe_start_time_seconds,
            temp_dir=Path(temp_dir) if temp_dir is not None else None,
            source_content_hash=identity.source_content_hash,
        )

    def build_debug_waveform(
        self,
        audio: DecodedAudio,
        context: AnalysisContext,
        *,
        created_at_utc: str | None = None,
        analyzer_producer: str = "autodj_analysis.debug_waveform",
    ) -> dict[str, Any]:
        """Build the existing debug-waveform artifact shape for this backend."""

        return self._debug_waveform_builder(
            context.track_id,
            audio,
            analyzer_producer=analyzer_producer,
            analyzer_version=self._backend_version,
            created_at_utc=created_at_utc,
        )

    def tempo_result_from_features(
        self,
        features: TempoFeatures,
        *,
        processing_seconds: float = 0.0,
    ) -> TempoCandidateResult:
        return TempoCandidateResult(
            status="ok",
            provenance=self._provenance(
                parameters={
                    "tempoBackend": features.backend,
                    "tempoHopLength": features.hop_length,
                    "tempoCandidateCount": len(features.candidates),
                },
                processing_seconds=processing_seconds,
                warnings=features.warnings,
            ),
            bpm=features.bpm,
            normalized_bpm=features.normalized_bpm,
            confidence=features.confidence,
            tempo_class=features.tempo_class,
            candidates=tuple(
                TempoCandidate(
                    bpm=float(candidate["bpm"]),
                    confidence=float(candidate["confidence"]),
                    backend=str(candidate["backend"]) if candidate.get("backend") is not None else None,
                )
                for candidate in features.candidates
            ),
        )

    def beat_grid_result_from_features(
        self,
        features: TempoFeatures,
        *,
        processing_seconds: float = 0.0,
    ) -> BeatGridCandidateResult:
        beats = tuple(_beat_marker(beat) for beat in features.beats)
        downbeats = tuple(_beat_marker(downbeat) for downbeat in features.downbeats)
        return BeatGridCandidateResult(
            status="ok",
            provenance=self._provenance(
                parameters={
                    "tempoBackend": features.backend,
                    "tempoHopLength": features.hop_length,
                    "beatCount": len(beats),
                    "downbeatCount": len(downbeats),
                },
                processing_seconds=processing_seconds,
                warnings=features.warnings,
            ),
            beats=beats,
            downbeats=downbeats,
            confidence=features.beat_grid_confidence,
            offset_seconds=beats[0].time_seconds if beats else None,
        )

    def section_result_from_features(
        self,
        features: StructureFeatures,
        *,
        processing_seconds: float = 0.0,
    ) -> SectionCandidateResult:
        return SectionCandidateResult(
            status="ok",
            provenance=self._provenance(
                parameters={
                    "sectionBackend": features.backend,
                    "highEnergyThreshold": features.high_energy_threshold,
                    "lowEnergyThreshold": features.low_energy_threshold,
                    "sectionCount": len(features.sections),
                    "cuePointCount": len(features.cue_points),
                },
                processing_seconds=processing_seconds,
                warnings=features.warnings,
            ),
            sections=tuple(_section_candidate(section, features.backend) for section in features.sections),
            cue_points=features.cue_points,
        )

    def _provenance(
        self,
        *,
        parameters: Mapping[str, Any] | None = None,
        processing_seconds: float = 0.0,
        warnings: tuple[str, ...] = (),
    ) -> CandidateProvenance:
        return CandidateProvenance(
            backend_name=self.name,
            backend_version=self._backend_version,
            model_name=CURRENT_SIGNAL_MODEL_NAME,
            model_version=CURRENT_SIGNAL_MODEL_VERSION,
            dependency_versions=_dependency_versions(),
            parameters=parameters or {},
            processing_seconds=processing_seconds,
            warnings=warnings,
        )


def current_signal_analyzer() -> Callable[[RepositoryTrack, ArtifactIdentity, str], "SignalAnalysisResult"]:
    """Return the default incumbent batch analyzer."""

    return CurrentSignalBackend().as_signal_analyzer()


def register_current_signal_backends(registry: BackendRegistry) -> None:
    """Register the incumbent backend for all supported contract kinds."""

    registry.register_tempo(CURRENT_SIGNAL_BACKEND, CurrentSignalBackend)
    registry.register_beat_grid(CURRENT_SIGNAL_BACKEND, CurrentSignalBackend)
    registry.register_section(CURRENT_SIGNAL_BACKEND, CurrentSignalBackend)


def _beat_marker(payload: Mapping[str, Any]) -> BeatMarker:
    return BeatMarker(
        index=int(payload["index"]),
        time_seconds=float(payload["timeSeconds"]),
        beat_in_bar=_optional_int(payload.get("beatInBar")),
        confidence=_optional_float(payload.get("confidence")),
    )


def _section_candidate(payload: Mapping[str, Any], backend: str) -> SectionCandidate:
    section_type = str(payload["type"])
    return SectionCandidate(
        id=str(payload["id"]),
        type=section_type,  # type: ignore[arg-type]
        start_seconds=float(payload["startSeconds"]),
        end_seconds=float(payload["endSeconds"]),
        confidence=float(payload["confidence"]),
        source_label=section_type,
        start_beat_index=_optional_int(payload.get("startBeatIndex")),
        end_beat_index=_optional_int(payload.get("endBeatIndex")),
        mapping_notes=("incumbent heuristic label passed through unchanged",),
        provider_metadata={
            "sourceBackend": backend,
            "energyMean": payload.get("energyMean"),
            "energyPeak": payload.get("energyPeak"),
        },
    )


def _backend_error(exc: Exception, *, backend_name: str) -> BackendExecutionError:
    if hasattr(exc, "to_dict"):
        details = dict(exc.to_dict())
    else:
        details = {"code": "backend_error", "message": str(exc)}

    return BackendExecutionError(
        code=str(details.get("code") or "backend_error"),
        message=str(details.get("message") or str(exc)),
        backend_name=backend_name,
        dependency=str(details["dependency"]) if details.get("dependency") is not None else None,
        details={str(key): str(value) for key, value in details.items()},
    )


def _status_for_error(exc: Exception) -> str:
    if getattr(exc, "dependency", None) is not None:
        return "unavailable"
    if hasattr(exc, "to_dict") and dict(exc.to_dict()).get("dependency") is not None:
        return "unavailable"
    return "failed"


def _uses_canonical_timeline(track: RepositoryTrack) -> bool:
    analysis_audio = track.provider_metadata.get("autodjAnalysisAudio")
    return isinstance(analysis_audio, Mapping) and analysis_audio.get("timelinePolicy") == "shared-canonical-pcm"


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in _DEPENDENCY_PACKAGES:
        try:
            versions[package_name] = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            continue
    return versions


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _elapsed(start: float) -> float:
    return round(max(0.0, time.perf_counter() - start), 6)
