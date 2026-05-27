"""Shared backend contracts and serializable candidate result shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, runtime_checkable

from ..audio_io import DecodedAudio
from ..dependencies import OptionalDependencyUnavailable


JsonValue = Any
CandidateStatus = Literal["ok", "unavailable", "failed", "deferred"]
SectionLabel = Literal["intro", "verse", "build", "drop", "break", "outro", "unknown"]


@dataclass(frozen=True)
class BackendExecutionError:
    """Structured backend failure or unavailable status."""

    code: str
    message: str
    backend_name: str | None = None
    dependency: str | None = None
    details: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_optional_dependency(
        cls,
        backend_name: str,
        error: OptionalDependencyUnavailable,
    ) -> "BackendExecutionError":
        details = error.to_dict()
        return cls(
            code=details["code"],
            message=details["message"],
            backend_name=backend_name,
            dependency=details["dependency"],
            details=details,
        )

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("code must not be empty")
        if not self.message:
            raise ValueError("message must not be empty")
        object.__setattr__(self, "details", dict(self.details))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        _set_if_present(payload, "backendName", self.backend_name)
        _set_if_present(payload, "dependency", self.dependency)
        if self.details:
            payload["details"] = dict(self.details)
        return payload


@dataclass(frozen=True)
class CandidateProvenance:
    """Backend and model provenance shared by all candidate results."""

    backend_name: str
    backend_version: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    dependency_versions: Mapping[str, str] = field(default_factory=dict)
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    processing_seconds: float = 0.0
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.backend_name:
            raise ValueError("backend_name must not be empty")
        if self.processing_seconds < 0:
            raise ValueError("processing_seconds must be greater than or equal to zero")
        object.__setattr__(self, "dependency_versions", dict(self.dependency_versions))
        object.__setattr__(self, "parameters", dict(self.parameters))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "backendName": self.backend_name,
            "dependencyVersions": dict(self.dependency_versions),
            "parameters": dict(self.parameters),
            "processingSeconds": self.processing_seconds,
            "warnings": list(self.warnings),
        }
        _set_if_present(payload, "backendVersion", self.backend_version)
        _set_if_present(payload, "modelName", self.model_name)
        _set_if_present(payload, "modelVersion", self.model_version)
        return payload


@dataclass(frozen=True)
class AnalysisContext:
    """Shared per-track context passed to all candidate backends."""

    track_id: str
    source_path: Path
    analysis_audio_path: Path
    duration_seconds: float
    ffprobe_start_time_seconds: float | None = None
    temp_dir: Path | None = None
    source_content_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.track_id:
            raise ValueError("track_id must not be empty")
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must be greater than or equal to zero")
        if self.ffprobe_start_time_seconds is not None and self.ffprobe_start_time_seconds < 0:
            raise ValueError("ffprobe_start_time_seconds must be greater than or equal to zero")
        object.__setattr__(self, "source_path", Path(self.source_path))
        object.__setattr__(self, "analysis_audio_path", Path(self.analysis_audio_path))
        if self.temp_dir is not None:
            object.__setattr__(self, "temp_dir", Path(self.temp_dir))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "trackId": self.track_id,
            "sourcePath": str(self.source_path),
            "analysisAudioPath": str(self.analysis_audio_path),
            "durationSeconds": self.duration_seconds,
        }
        _set_if_present(payload, "ffprobeStartTimeSeconds", self.ffprobe_start_time_seconds)
        _set_if_present(payload, "tempDir", str(self.temp_dir) if self.temp_dir is not None else None)
        _set_if_present(payload, "sourceContentHash", self.source_content_hash)
        return payload


@dataclass(frozen=True)
class FeatureBundle:
    """Optional shared signal features available to section backends."""

    energy: Any | None = None
    waveform: Any | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extras", dict(self.extras))


@dataclass(frozen=True)
class TempoCandidate:
    bpm: float
    confidence: float
    backend: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_number("bpm", self.bpm)
        _validate_confidence(self.confidence)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "bpm": self.bpm,
            "confidence": self.confidence,
        }
        _set_if_present(payload, "backend", self.backend)
        return payload


@dataclass(frozen=True)
class KeyCandidate:
    tonic: str
    mode: str
    confidence: float
    camelot: str | None = None
    backend: str | None = None

    def __post_init__(self) -> None:
        if not self.tonic:
            raise ValueError("tonic must not be empty")
        if not self.mode:
            raise ValueError("mode must not be empty")
        _validate_confidence(self.confidence)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tonic": self.tonic,
            "mode": self.mode,
            "confidence": self.confidence,
        }
        _set_if_present(payload, "camelot", self.camelot)
        _set_if_present(payload, "backend", self.backend)
        return payload


@dataclass(frozen=True)
class BeatMarker:
    index: int
    time_seconds: float
    beat_in_bar: int | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("index must be greater than or equal to zero")
        if self.time_seconds < 0:
            raise ValueError("time_seconds must be greater than or equal to zero")
        if self.beat_in_bar is not None and self.beat_in_bar <= 0:
            raise ValueError("beat_in_bar must be greater than zero")
        if self.confidence is not None:
            _validate_confidence(self.confidence)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "index": self.index,
            "timeSeconds": self.time_seconds,
        }
        _set_if_present(payload, "beatInBar", self.beat_in_bar)
        _set_if_present(payload, "confidence", self.confidence)
        return payload


@dataclass(frozen=True)
class SectionCandidate:
    id: str
    type: SectionLabel
    start_seconds: float
    end_seconds: float
    confidence: float
    source_label: str | None = None
    start_beat_index: int | None = None
    end_beat_index: int | None = None
    mapping_notes: tuple[str, ...] = ()
    provider_metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must not be empty")
        if self.start_seconds < 0:
            raise ValueError("start_seconds must be greater than or equal to zero")
        if self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must be greater than or equal to start_seconds")
        if self.start_beat_index is not None and self.start_beat_index < 0:
            raise ValueError("start_beat_index must be greater than or equal to zero")
        if self.end_beat_index is not None and self.end_beat_index < 0:
            raise ValueError("end_beat_index must be greater than or equal to zero")
        _validate_confidence(self.confidence)
        object.__setattr__(self, "mapping_notes", tuple(self.mapping_notes))
        object.__setattr__(self, "provider_metadata", dict(self.provider_metadata))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "startSeconds": self.start_seconds,
            "endSeconds": self.end_seconds,
            "confidence": self.confidence,
        }
        _set_if_present(payload, "sourceLabel", self.source_label)
        _set_if_present(payload, "startBeatIndex", self.start_beat_index)
        _set_if_present(payload, "endBeatIndex", self.end_beat_index)
        if self.mapping_notes:
            payload["mappingNotes"] = list(self.mapping_notes)
        if self.provider_metadata:
            payload["providerMetadata"] = dict(self.provider_metadata)
        return payload


@dataclass(frozen=True)
class TempoCandidateResult:
    status: CandidateStatus
    provenance: CandidateProvenance
    bpm: float | None = None
    normalized_bpm: float | None = None
    confidence: float = 0.0
    tempo_class: str | None = None
    candidates: tuple[TempoCandidate, ...] = ()
    error: BackendExecutionError | None = None

    def __post_init__(self) -> None:
        _validate_status(self.status)
        _validate_confidence(self.confidence)
        if self.status == "ok":
            if self.bpm is None or self.normalized_bpm is None:
                raise ValueError("ok tempo results require bpm and normalized_bpm")
            _validate_positive_number("bpm", self.bpm)
            _validate_positive_number("normalized_bpm", self.normalized_bpm)
        if self.status != "ok" and self.error is None:
            raise ValueError("non-ok tempo results require an error")
        object.__setattr__(self, "candidates", tuple(self.candidates))

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        payload = _candidate_payload(self.status, self.provenance, self.error)
        _set_if_present(payload, "bpm", self.bpm)
        _set_if_present(payload, "normalizedBpm", self.normalized_bpm)
        payload["confidence"] = self.confidence
        _set_if_present(payload, "tempoClass", self.tempo_class)
        payload["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return payload


@dataclass(frozen=True)
class KeyCandidateResult:
    status: CandidateStatus
    provenance: CandidateProvenance
    tonic: str | None = None
    mode: str | None = None
    camelot: str | None = None
    confidence: float = 0.0
    candidates: tuple[KeyCandidate, ...] = ()
    error: BackendExecutionError | None = None

    def __post_init__(self) -> None:
        _validate_status(self.status)
        _validate_confidence(self.confidence)
        if self.status == "ok" and (not self.tonic or not self.mode):
            raise ValueError("ok key results require tonic and mode")
        if self.status != "ok" and self.error is None:
            raise ValueError("non-ok key results require an error")
        object.__setattr__(self, "candidates", tuple(self.candidates))

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        payload = _candidate_payload(self.status, self.provenance, self.error)
        _set_if_present(payload, "tonic", self.tonic)
        _set_if_present(payload, "mode", self.mode)
        _set_if_present(payload, "camelot", self.camelot)
        payload["confidence"] = self.confidence
        payload["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return payload


@dataclass(frozen=True)
class BeatGridCandidateResult:
    status: CandidateStatus
    provenance: CandidateProvenance
    beats: tuple[BeatMarker, ...] = ()
    downbeats: tuple[BeatMarker, ...] = ()
    confidence: float = 0.0
    offset_seconds: float | None = None
    error: BackendExecutionError | None = None

    def __post_init__(self) -> None:
        _validate_status(self.status)
        _validate_confidence(self.confidence)
        if self.status != "ok" and self.error is None:
            raise ValueError("non-ok beatgrid results require an error")
        object.__setattr__(self, "beats", tuple(self.beats))
        object.__setattr__(self, "downbeats", tuple(self.downbeats))

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        payload = _candidate_payload(self.status, self.provenance, self.error)
        payload["beats"] = [beat.to_dict() for beat in self.beats]
        payload["downbeats"] = [downbeat.to_dict() for downbeat in self.downbeats]
        payload["confidence"] = self.confidence
        _set_if_present(payload, "offsetSeconds", self.offset_seconds)
        return payload


@dataclass(frozen=True)
class SectionCandidateResult:
    status: CandidateStatus
    provenance: CandidateProvenance
    sections: tuple[SectionCandidate, ...] = ()
    cue_points: tuple[dict[str, JsonValue], ...] = ()
    error: BackendExecutionError | None = None

    def __post_init__(self) -> None:
        _validate_status(self.status)
        if self.status != "ok" and self.error is None:
            raise ValueError("non-ok section results require an error")
        object.__setattr__(self, "sections", tuple(self.sections))
        object.__setattr__(self, "cue_points", tuple(dict(cue) for cue in self.cue_points))

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        payload = _candidate_payload(self.status, self.provenance, self.error)
        payload["sections"] = [section.to_dict() for section in self.sections]
        payload["cuePoints"] = [dict(cue) for cue in self.cue_points]
        return payload


@runtime_checkable
class TempoBackend(Protocol):
    name: str

    def analyze_tempo(self, audio: DecodedAudio, context: AnalysisContext) -> TempoCandidateResult:
        ...


@runtime_checkable
class KeyDetectorBackend(Protocol):
    name: str

    def analyze_key(self, audio: DecodedAudio, context: AnalysisContext) -> KeyCandidateResult:
        ...


@runtime_checkable
class BeatGridBackend(Protocol):
    name: str

    def analyze_beat_grid(
        self,
        audio: DecodedAudio,
        tempo: TempoCandidateResult,
        context: AnalysisContext,
    ) -> BeatGridCandidateResult:
        ...


@runtime_checkable
class SectionBackend(Protocol):
    name: str

    def analyze_sections(
        self,
        audio: DecodedAudio,
        features: FeatureBundle,
        beat_grid: BeatGridCandidateResult,
        context: AnalysisContext,
    ) -> SectionCandidateResult:
        ...


def _candidate_payload(
    status: CandidateStatus,
    provenance: CandidateProvenance,
    error: BackendExecutionError | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "provenance": provenance.to_dict(),
    }
    if error is not None:
        payload["error"] = error.to_dict()
    return payload


def _validate_status(status: CandidateStatus) -> None:
    if status not in {"ok", "unavailable", "failed", "deferred"}:
        raise ValueError(f"unsupported candidate status: {status}")


def _validate_positive_number(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def _validate_confidence(confidence: float) -> None:
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0.0 and 1.0")


def _set_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        target[key] = value
