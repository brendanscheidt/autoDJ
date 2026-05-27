from pathlib import Path

import pytest

from autodj_analysis.audio_io import DecodedAudio
from autodj_analysis.backends import (
    AnalysisContext,
    BackendExecutionError,
    BackendRegistry,
    BackendRegistryError,
    BeatGridCandidateResult,
    BeatMarker,
    CandidateProvenance,
    FeatureBundle,
    KeyCandidate,
    KeyCandidateResult,
    SectionCandidate,
    SectionCandidateResult,
    TempoCandidate,
    TempoCandidateResult,
)
from autodj_analysis.dependencies import DependencyError, OptionalDependencyUnavailable


def _audio() -> DecodedAudio:
    return DecodedAudio(
        samples=[0.0, 1.0, 0.0],
        sample_rate=3,
        duration_seconds=1.0,
        channels=1,
        source_path=Path("fixture.wav"),
    )


def _context() -> AnalysisContext:
    return AnalysisContext(
        track_id="track-001",
        source_path=Path("fixture.mp3"),
        analysis_audio_path=Path("fixture-analysis.wav"),
        duration_seconds=1.0,
        ffprobe_start_time_seconds=0.023,
        temp_dir=Path("tmp"),
        source_content_hash="sha256:fixture",
    )


def _provenance(name: str = "test-backend") -> CandidateProvenance:
    return CandidateProvenance(
        backend_name=name,
        backend_version="0.1.0",
        model_name="test-model",
        model_version="v1",
        dependency_versions={"dep": "1.2.3"},
        parameters={"threshold": 0.25},
        processing_seconds=0.01,
        warnings=("test warning",),
    )


class _TempoBackend:
    name = "tempo-a"

    def __init__(self, bpm: float) -> None:
        self._bpm = bpm

    def analyze_tempo(self, audio: DecodedAudio, context: AnalysisContext) -> TempoCandidateResult:
        return TempoCandidateResult(
            status="ok",
            provenance=_provenance(self.name),
            bpm=self._bpm,
            normalized_bpm=self._bpm,
            confidence=0.9,
            tempo_class="straight",
            candidates=(TempoCandidate(bpm=self._bpm, confidence=0.9, backend=self.name),),
        )


class _BeatGridBackend:
    name = "grid-a"

    def analyze_beat_grid(
        self,
        audio: DecodedAudio,
        tempo: TempoCandidateResult,
        context: AnalysisContext,
    ) -> BeatGridCandidateResult:
        return BeatGridCandidateResult(
            status="ok",
            provenance=_provenance(self.name),
            beats=(BeatMarker(index=0, time_seconds=0.0, beat_in_bar=1, confidence=0.88),),
            downbeats=(BeatMarker(index=0, time_seconds=0.0, beat_in_bar=1, confidence=0.88),),
            confidence=0.88,
        )


class _SectionBackend:
    name = "section-a"

    def analyze_sections(
        self,
        audio: DecodedAudio,
        features: FeatureBundle,
        beat_grid: BeatGridCandidateResult,
        context: AnalysisContext,
    ) -> SectionCandidateResult:
        return SectionCandidateResult(
            status="ok",
            provenance=_provenance(self.name),
            sections=(
                SectionCandidate(
                    id="section-drop-001",
                    type="drop",
                    start_seconds=0.0,
                    end_seconds=1.0,
                    confidence=0.7,
                    source_label="chorus",
                    start_beat_index=0,
                    mapping_notes=("promoted by fixture evidence",),
                ),
            ),
        )


class _KeyBackend:
    name = "key-a"

    def analyze_key(self, audio: DecodedAudio, context: AnalysisContext) -> KeyCandidateResult:
        return KeyCandidateResult(
            status="ok",
            provenance=_provenance(self.name),
            tonic="E",
            mode="minor",
            camelot="9A",
            confidence=0.82,
            candidates=(
                KeyCandidate(
                    tonic="E",
                    mode="minor",
                    camelot="9A",
                    confidence=0.82,
                    backend=self.name,
                ),
            ),
        )


def test_candidate_provenance_and_context_serialize_with_camel_case() -> None:
    assert _provenance().to_dict() == {
        "backendName": "test-backend",
        "dependencyVersions": {"dep": "1.2.3"},
        "parameters": {"threshold": 0.25},
        "processingSeconds": 0.01,
        "warnings": ["test warning"],
        "backendVersion": "0.1.0",
        "modelName": "test-model",
        "modelVersion": "v1",
    }

    assert _context().to_dict() == {
        "trackId": "track-001",
        "sourcePath": "fixture.mp3",
        "analysisAudioPath": "fixture-analysis.wav",
        "durationSeconds": 1.0,
        "ffprobeStartTimeSeconds": 0.023,
        "tempDir": "tmp",
        "sourceContentHash": "sha256:fixture",
    }


def test_registry_selects_swappable_backends_by_name() -> None:
    registry = BackendRegistry()
    registry.register_tempo("tempo-a", lambda: _TempoBackend(140.0))
    registry.register_tempo("tempo-b", lambda: _TempoBackend(150.0))
    registry.register_beat_grid("grid-a", _BeatGridBackend)
    registry.register_section("section-a", _SectionBackend)
    registry.register_key("key-a", _KeyBackend)

    assert registry.tempo_names() == ("tempo-a", "tempo-b")
    assert registry.beat_grid_names() == ("grid-a",)
    assert registry.section_names() == ("section-a",)
    assert registry.key_names() == ("key-a",)

    audio = _audio()
    context = _context()
    tempo = registry.create_tempo("tempo-b").analyze_tempo(audio, context)
    grid = registry.create_beat_grid("grid-a").analyze_beat_grid(audio, tempo, context)
    sections = registry.create_section("section-a").analyze_sections(audio, FeatureBundle(), grid, context)
    key = registry.create_key("key-a").analyze_key(audio, context)

    assert tempo.bpm == 150.0
    assert grid.beats[0].to_dict() == {
        "index": 0,
        "timeSeconds": 0.0,
        "beatInBar": 1,
        "confidence": 0.88,
    }
    assert sections.sections[0].to_dict()["sourceLabel"] == "chorus"
    assert key.to_dict()["camelot"] == "9A"
    assert key.to_dict()["candidates"][0]["backend"] == "key-a"


def test_registry_reports_missing_and_duplicate_backends_structurally() -> None:
    registry = BackendRegistry()
    registry.register_tempo("tempo-a", lambda: _TempoBackend(140.0))

    with pytest.raises(BackendRegistryError) as duplicate:
        registry.register_tempo("tempo-a", lambda: _TempoBackend(150.0))
    assert duplicate.value.to_dict()["code"] == "backend_already_registered"

    with pytest.raises(BackendRegistryError) as missing:
        registry.create_section("missing-section")
    assert missing.value.to_dict() == {
        "code": "backend_not_registered",
        "message": "section backend is not registered: missing-section",
        "backendKind": "section",
        "backendName": "missing-section",
    }


def test_unavailable_backend_result_serializes_optional_dependency_error() -> None:
    dependency_error = DependencyError(
        code="analysis_dependency_missing",
        dependency="beat-this",
        module_name="beat_this",
        install_extra="analysis-candidates",
        message="beat-this is unavailable",
    )
    error = BackendExecutionError.from_optional_dependency(
        "beat-this",
        OptionalDependencyUnavailable(dependency_error),
    )
    result = BeatGridCandidateResult(
        status="unavailable",
        provenance=CandidateProvenance(backend_name="beat-this"),
        error=error,
    )

    assert result.ok is False
    assert result.to_dict()["error"] == {
        "code": "analysis_dependency_missing",
        "message": "beat-this is unavailable",
        "backendName": "beat-this",
        "dependency": "beat-this",
        "details": {
            "code": "analysis_dependency_missing",
            "dependency": "beat-this",
            "moduleName": "beat_this",
            "message": "beat-this is unavailable",
            "installExtra": "analysis-candidates",
        },
    }


def test_non_ok_results_require_structured_error() -> None:
    with pytest.raises(ValueError, match="non-ok tempo results require an error"):
        TempoCandidateResult(
            status="unavailable",
            provenance=CandidateProvenance(backend_name="missing-tempo"),
        )
    with pytest.raises(ValueError, match="non-ok key results require an error"):
        KeyCandidateResult(
            status="failed",
            provenance=CandidateProvenance(backend_name="bad-key"),
        )


def test_invalid_contract_values_fail_before_backend_execution() -> None:
    with pytest.raises(ValueError, match="duration_seconds"):
        AnalysisContext(
            track_id="track-001",
            source_path=Path("fixture.mp3"),
            analysis_audio_path=Path("fixture.wav"),
            duration_seconds=-1.0,
        )
    with pytest.raises(ValueError, match="confidence"):
        BeatMarker(index=0, time_seconds=0.0, confidence=1.5)
