"""Essentia rhythm backend adapter for tempo and beat-grid candidates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
import time
from typing import Any

from .. import __version__
from ..audio_io import DecodedAudio
from ..dependencies import OptionalDependencyUnavailable, require_optional_dependency
from ..tempo import normalize_dubstep_bpm
from .base import (
    AnalysisContext,
    BackendExecutionError,
    BeatGridCandidateResult,
    BeatMarker,
    CandidateProvenance,
    TempoCandidate,
    TempoCandidateResult,
)
from .registry import BackendRegistry


ESSENTIA_RHYTHM_BACKEND = "essentia-rhythm"
ESSENTIA_RHYTHM_MODEL_NAME = "Essentia RhythmExtractor2013"
ESSENTIA_RHYTHM_LICENSE_NOTE = "Essentia is AGPLv3 for non-commercial use; commercial licensing must be reviewed before distribution."
DEFAULT_ESSENTIA_RHYTHM_METHOD = "multifeature"
DEFAULT_ESSENTIA_ANALYSIS_SAMPLE_RATE = 44_100
DEFAULT_ESSENTIA_MIN_TEMPO_BPM = 50
DEFAULT_ESSENTIA_MAX_TEMPO_BPM = 220
MAX_TEMPO_CANDIDATES = 8


@dataclass(frozen=True)
class EssentiaRhythmFeatures:
    bpm: float
    ticks: tuple[float, ...]
    confidence: float
    estimates: tuple[float, ...]
    bpm_intervals: tuple[float, ...]
    source_sample_rate: int
    analysis_sample_rate: int
    method: str
    min_tempo_bpm: float
    max_tempo_bpm: float
    resampled: bool


class EssentiaRhythmBackend:
    """Optional Essentia-backed timing candidate."""

    name = ESSENTIA_RHYTHM_BACKEND

    def __init__(
        self,
        *,
        method: str = DEFAULT_ESSENTIA_RHYTHM_METHOD,
        analysis_sample_rate: int = DEFAULT_ESSENTIA_ANALYSIS_SAMPLE_RATE,
        min_tempo_bpm: int = DEFAULT_ESSENTIA_MIN_TEMPO_BPM,
        max_tempo_bpm: int = DEFAULT_ESSENTIA_MAX_TEMPO_BPM,
        dependency_loader: Callable[..., Any] = require_optional_dependency,
        version_resolver: Callable[[str], str] = metadata.version,
        backend_version: str = __version__,
    ) -> None:
        if analysis_sample_rate <= 0:
            raise ValueError("analysis_sample_rate must be greater than zero")
        if min_tempo_bpm <= 0 or max_tempo_bpm <= min_tempo_bpm:
            raise ValueError("tempo range must be positive and max_tempo_bpm must exceed min_tempo_bpm")
        if not method:
            raise ValueError("method must not be empty")

        self.method = method
        self.analysis_sample_rate = int(analysis_sample_rate)
        self.min_tempo_bpm = int(round(min_tempo_bpm))
        self.max_tempo_bpm = int(round(max_tempo_bpm))
        self._dependency_loader = dependency_loader
        self._version_resolver = version_resolver
        self._backend_version = backend_version

    def analyze_tempo(self, audio: DecodedAudio, context: AnalysisContext) -> TempoCandidateResult:
        del context
        start = time.perf_counter()
        try:
            features = self.extract_features(audio)
            return self.tempo_result_from_features(features, processing_seconds=_elapsed(start))
        except OptionalDependencyUnavailable as exc:
            return TempoCandidateResult(
                status="unavailable",
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=BackendExecutionError.from_optional_dependency(self.name, exc),
            )
        except Exception as exc:
            return TempoCandidateResult(
                status="failed",
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=_backend_error(exc, backend_name=self.name),
            )

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
                    message="Essentia beat-grid analysis requires an ok tempo result.",
                    backend_name=self.name,
                ),
            )

        start = time.perf_counter()
        try:
            features = self.extract_features(audio)
            return self.beat_grid_result_from_features(features, processing_seconds=_elapsed(start))
        except OptionalDependencyUnavailable as exc:
            return BeatGridCandidateResult(
                status="unavailable",
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=BackendExecutionError.from_optional_dependency(self.name, exc),
            )
        except Exception as exc:
            return BeatGridCandidateResult(
                status="failed",
                provenance=self._provenance(processing_seconds=_elapsed(start)),
                error=_backend_error(exc, backend_name=self.name),
            )

    def extract_features(self, audio: DecodedAudio) -> EssentiaRhythmFeatures:
        numpy = self._dependency_loader(
            "numpy",
            module_name="numpy",
            install_extra="analysis-wsl",
        )
        essentia_standard = self._dependency_loader(
            "essentia",
            module_name="essentia.standard",
            install_extra="analysis-wsl",
        )

        samples = numpy.asarray(audio.samples, dtype=numpy.float32).reshape(-1)
        if int(samples.size) == 0:
            raise ValueError("Decoded audio contains no samples")

        resampled = False
        if audio.sample_rate != self.analysis_sample_rate:
            samples = essentia_standard.Resample(
                inputSampleRate=float(audio.sample_rate),
                outputSampleRate=float(self.analysis_sample_rate),
            )(samples).astype(numpy.float32, copy=False)
            resampled = True

        extractor = essentia_standard.RhythmExtractor2013(
            method=self.method,
            minTempo=int(self.min_tempo_bpm),
            maxTempo=int(self.max_tempo_bpm),
        )
        bpm, ticks, confidence, estimates, bpm_intervals = extractor(samples)
        return EssentiaRhythmFeatures(
            bpm=float(bpm),
            ticks=_float_sequence(ticks),
            confidence=float(confidence),
            estimates=_float_sequence(estimates),
            bpm_intervals=_float_sequence(bpm_intervals),
            source_sample_rate=int(audio.sample_rate),
            analysis_sample_rate=self.analysis_sample_rate,
            method=self.method,
            min_tempo_bpm=self.min_tempo_bpm,
            max_tempo_bpm=self.max_tempo_bpm,
            resampled=resampled,
        )

    def tempo_result_from_features(
        self,
        features: EssentiaRhythmFeatures,
        *,
        processing_seconds: float = 0.0,
    ) -> TempoCandidateResult:
        normalized = normalize_dubstep_bpm(features.bpm)
        warnings = _warnings(features, extra=() if normalized.warning is None else (normalized.warning,))
        confidence = _combined_confidence(features.confidence, features.ticks)
        return TempoCandidateResult(
            status="ok",
            provenance=self._provenance(
                parameters=_parameters(features),
                processing_seconds=processing_seconds,
                warnings=warnings,
            ),
            bpm=normalized.bpm,
            normalized_bpm=normalized.normalized_bpm,
            confidence=confidence,
            tempo_class=normalized.tempo_class,
            candidates=_tempo_candidates(features, confidence),
        )

    def beat_grid_result_from_features(
        self,
        features: EssentiaRhythmFeatures,
        *,
        processing_seconds: float = 0.0,
    ) -> BeatGridCandidateResult:
        confidence = _combined_confidence(features.confidence, features.ticks)
        beats = tuple(
            BeatMarker(
                index=index,
                time_seconds=time_seconds,
                confidence=confidence,
            )
            for index, time_seconds in enumerate(_valid_ticks(features.ticks))
        )
        return BeatGridCandidateResult(
            status="ok",
            provenance=self._provenance(
                parameters=_parameters(features) | {"beatCount": len(beats), "downbeatCount": 0},
                processing_seconds=processing_seconds,
                warnings=_warnings(features),
            ),
            beats=beats,
            downbeats=(),
            confidence=confidence if beats else 0.0,
            offset_seconds=beats[0].time_seconds if beats else None,
        )

    def _provenance(
        self,
        *,
        parameters: dict[str, Any] | None = None,
        processing_seconds: float = 0.0,
        warnings: tuple[str, ...] = (),
    ) -> CandidateProvenance:
        return CandidateProvenance(
            backend_name=self.name,
            backend_version=self._backend_version,
            model_name=ESSENTIA_RHYTHM_MODEL_NAME,
            model_version=_dependency_version("essentia", self._version_resolver),
            dependency_versions=_dependency_versions(self._version_resolver),
            parameters={
                "method": self.method,
                "analysisSampleRate": self.analysis_sample_rate,
                "minTempoBpm": self.min_tempo_bpm,
                "maxTempoBpm": self.max_tempo_bpm,
                "licenseNote": ESSENTIA_RHYTHM_LICENSE_NOTE,
            }
            | (parameters or {}),
            processing_seconds=processing_seconds,
            warnings=warnings,
        )


def register_essentia_rhythm_backends(registry: BackendRegistry) -> None:
    """Register Essentia as a tempo and beat-grid candidate."""

    registry.register_tempo(ESSENTIA_RHYTHM_BACKEND, EssentiaRhythmBackend)
    registry.register_beat_grid(ESSENTIA_RHYTHM_BACKEND, EssentiaRhythmBackend)


def _parameters(features: EssentiaRhythmFeatures) -> dict[str, Any]:
    return {
        "method": features.method,
        "analysisSampleRate": features.analysis_sample_rate,
        "sourceSampleRate": features.source_sample_rate,
        "resampled": features.resampled,
        "minTempoBpm": features.min_tempo_bpm,
        "maxTempoBpm": features.max_tempo_bpm,
        "rawConfidence": features.confidence,
        "estimateCount": len(features.estimates),
        "bpmIntervalCount": len(features.bpm_intervals),
    }


def _warnings(features: EssentiaRhythmFeatures, *, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    warnings = [
        ESSENTIA_RHYTHM_LICENSE_NOTE,
        "Essentia RhythmExtractor2013 does not emit downbeats; downbeat output is intentionally empty.",
    ]
    if features.resampled:
        warnings.append(
            f"Audio was resampled from {features.source_sample_rate} Hz to "
            f"{features.analysis_sample_rate} Hz for Essentia rhythm analysis."
        )
    if features.confidence <= 0 and features.ticks:
        warnings.append(
            "Essentia reported non-positive rhythm confidence; AutoDJ confidence uses beat-sequence regularity as a fallback."
        )
    warnings.extend(extra)
    return tuple(warnings)


def _tempo_candidates(
    features: EssentiaRhythmFeatures,
    fallback_confidence: float,
) -> tuple[TempoCandidate, ...]:
    candidates: list[TempoCandidate] = [
        TempoCandidate(
            bpm=float(features.bpm),
            confidence=fallback_confidence,
            backend="essentia.RhythmExtractor2013",
        )
    ]
    distribution = _estimate_distribution(features.estimates)
    for bpm, support in distribution[:MAX_TEMPO_CANDIDATES - 1]:
        if abs(bpm - features.bpm) < 1e-6:
            continue
        candidates.append(
            TempoCandidate(
                bpm=bpm,
                confidence=_clamp(support),
                backend="essentia.RhythmExtractor2013.estimate_distribution",
            )
        )
    return tuple(candidates[:MAX_TEMPO_CANDIDATES])


def _estimate_distribution(estimates: tuple[float, ...]) -> list[tuple[float, float]]:
    valid = [estimate for estimate in estimates if estimate > 0]
    if not valid:
        return []
    counts: dict[float, int] = {}
    for estimate in valid:
        half_bpm_bucket = round(float(estimate) * 2.0) / 2.0
        counts[half_bpm_bucket] = counts.get(half_bpm_bucket, 0) + 1
    total = float(len(valid))
    return sorted(
        ((bpm, count / total) for bpm, count in counts.items()),
        key=lambda item: (-item[1], item[0]),
    )


def _combined_confidence(raw_confidence: float, ticks: tuple[float, ...]) -> float:
    raw = _clamp(float(raw_confidence))
    sequence = _sequence_confidence(ticks)
    if raw <= 0:
        return min(0.78, sequence)
    return _clamp(max(raw, sequence * 0.85))


def _sequence_confidence(ticks: tuple[float, ...]) -> float:
    if len(ticks) < 4:
        return 0.2 if ticks else 0.0
    intervals = [later - earlier for earlier, later in zip(ticks, ticks[1:]) if later > earlier]
    if len(intervals) < 3:
        return 0.2
    median_interval = _median(intervals)
    if median_interval <= 0:
        return 0.2
    median_error = _median([abs(interval - median_interval) for interval in intervals])
    regularity = 1.0 - min(median_error / (median_interval * 0.2), 1.0)
    count_score = min(len(ticks) / 16.0, 1.0)
    return _round_float(_clamp(0.20 + 0.60 * regularity + 0.20 * count_score))


def _valid_ticks(ticks: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(_round_float(tick) for tick in sorted(tick for tick in ticks if tick >= 0))


def _float_sequence(values: Any) -> tuple[float, ...]:
    try:
        return tuple(float(value) for value in values)
    except TypeError:
        return ()


def _backend_error(exc: Exception, *, backend_name: str) -> BackendExecutionError:
    return BackendExecutionError(
        code="essentia_rhythm_failed",
        message=str(exc) or exc.__class__.__name__,
        backend_name=backend_name,
        details={"exceptionType": exc.__class__.__name__},
    )


def _dependency_versions(version_resolver: Callable[[str], str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in ("essentia", "numpy"):
        version = _dependency_version(package_name, version_resolver)
        if version is not None:
            versions[package_name] = version
    return versions


def _dependency_version(package_name: str, version_resolver: Callable[[str], str]) -> str | None:
    try:
        return version_resolver(package_name)
    except metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded


def _elapsed(start: float) -> float:
    return round(max(0.0, time.perf_counter() - start), 6)
