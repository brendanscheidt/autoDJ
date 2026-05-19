from dataclasses import dataclass
from pathlib import Path

from autodj_analysis import (
    ALL_IN_ONE_BACKEND,
    ALL_IN_ONE_LICENSE_NOTE,
    ALL_IN_ONE_MP3_TIMELINE_WARNING,
    ALL_IN_ONE_UNLOCKED_BACKEND,
    AnalysisContext,
    AllInOneBackend,
    AllInOneUnlockedBackend,
    BackendExecutionError,
    BackendRegistry,
    BeatGridCandidateResult,
    CandidateProvenance,
    DecodedAudio,
    DependencyError,
    FeatureBundle,
    TempoCandidate,
    TempoCandidateResult,
    register_all_in_one_backends,
)
from autodj_analysis.dependencies import OptionalDependencyUnavailable


@dataclass
class _Segment:
    start: float
    end: float
    label: str


@dataclass
class _Result:
    path: Path
    bpm: float
    beats: list[float]
    downbeats: list[float]
    beat_positions: list[int]
    segments: list[_Segment]


def _audio() -> DecodedAudio:
    return DecodedAudio(
        samples=[0.0, 0.5, 0.0, -0.5],
        sample_rate=44100,
        duration_seconds=2.5,
        channels=1,
        source_path=Path("fixture-analysis.wav"),
    )


def _context() -> AnalysisContext:
    return AnalysisContext(
        track_id="track-001",
        source_path=Path("fixture.mp3"),
        analysis_audio_path=Path("fixture-analysis.wav"),
        duration_seconds=2.5,
        temp_dir=Path("tmp"),
    )


def _tempo(status: str = "ok") -> TempoCandidateResult:
    if status == "ok":
        return TempoCandidateResult(
            status="ok",
            provenance=CandidateProvenance(backend_name="tempo-a"),
            bpm=142.0,
            normalized_bpm=142.0,
            confidence=0.9,
            tempo_class="straight",
            candidates=(TempoCandidate(bpm=142.0, confidence=0.9, backend="tempo-a"),),
        )
    return TempoCandidateResult(
        status=status,
        provenance=CandidateProvenance(backend_name="tempo-a"),
        error=BackendExecutionError(
            code="tempo_failed",
            message="tempo failed",
            backend_name="tempo-a",
        ),
    )


def _beat_grid() -> BeatGridCandidateResult:
    return BeatGridCandidateResult(
        status="ok",
        provenance=CandidateProvenance(backend_name="beat-a"),
        beats=[],
        confidence=0.5,
    )


def _result() -> _Result:
    return _Result(
        path=Path("fixture-analysis.wav"),
        bpm=142.0,
        beats=[0.1, 0.522535, 0.94507, 1.367605, 1.79014],
        downbeats=[0.1, 1.79014],
        beat_positions=[1, 2, 3, 4, 1],
        segments=[
            _Segment(start=0.0, end=0.1, label="start"),
            _Segment(start=0.1, end=0.94507, label="intro"),
            _Segment(start=0.94507, end=1.79014, label="chorus"),
            _Segment(start=1.79014, end=2.4, label="outro"),
        ],
    )


def test_all_in_one_maps_runner_outputs_to_tempo_beatgrid_and_sections() -> None:
    calls: list[tuple[Path, dict]] = []

    def runner(path, options):
        calls.append((path, dict(options)))
        return _result()

    backend = AllInOneBackend(
        analysis_runner=runner,
        version_resolver=lambda package: f"{package}-version",
        module_available=lambda module: module in {"allin1", "torch"},
        ffmpeg_resolver=lambda _name: "/usr/bin/ffmpeg",
    )

    analysis = backend.analyze_file(_context())
    tempo = backend.tempo_result_from_analysis(analysis, processing_seconds=0.25)
    beat_grid = backend.beat_grid_result_from_analysis(
        analysis,
        tempo_status="failed",
        processing_seconds=0.11,
    )
    sections = backend.section_result_from_analysis(
        analysis,
        beat_grid=beat_grid,
        processing_seconds=0.08,
    )

    assert calls == [
        (
            Path("fixture-analysis.wav"),
            {
                "out_dir": None,
                "visualize": False,
                "sonify": False,
                "model": "harmonix-all",
                "device": "cpu",
                "include_activations": False,
                "include_embeddings": False,
                "demix_dir": "tmp/all-in-one-demix",
                "spec_dir": "tmp/all-in-one-spec",
                "keep_byproducts": False,
                "overwrite": True,
                "multiprocess": True,
            },
        )
    ]
    assert tempo.ok is True
    assert tempo.bpm == 142.0
    assert tempo.normalized_bpm == 142.0
    assert tempo.provenance.backend_name == ALL_IN_ONE_BACKEND
    assert tempo.provenance.dependency_versions["allin1"] == "allin1-version"
    assert tempo.provenance.parameters["licenseNote"] == ALL_IN_ONE_LICENSE_NOTE
    assert tempo.provenance.parameters["timelineMode"] == "analysis_audio_path"
    assert tempo.provenance.parameters["ffmpegPath"] == "/usr/bin/ffmpeg"
    assert tempo.provenance.parameters["dependencyAvailability"]["allin1"] is True
    assert tempo.provenance.processing_seconds == 0.25
    assert any("analysis_audio_path" in warning for warning in tempo.provenance.warnings)

    assert beat_grid.ok is True
    assert beat_grid.provenance.parameters["tempoStatus"] == "failed"
    assert beat_grid.beats[0].to_dict() == {
        "index": 0,
        "timeSeconds": 0.1,
        "beatInBar": 1,
        "confidence": beat_grid.confidence,
    }
    assert beat_grid.downbeats[0].beat_in_bar == 1
    assert beat_grid.offset_seconds == 0.1

    assert sections.ok is True
    assert [section.type for section in sections.sections] == [
        "unknown",
        "intro",
        "unknown",
        "outro",
    ]
    assert sections.sections[2].source_label == "chorus"
    assert sections.sections[2].confidence <= 0.45
    assert "requires energy/bass/onset/phrase evidence" in sections.sections[2].mapping_notes[0]
    assert sections.sections[1].start_beat_index == 0


def test_all_in_one_analyze_methods_use_cached_runner_result() -> None:
    call_count = 0

    def runner(_path, _options):
        nonlocal call_count
        call_count += 1
        return _result()

    backend = AllInOneBackend(analysis_runner=runner)

    tempo = backend.analyze_tempo(_audio(), _context())
    beat_grid = backend.analyze_beat_grid(_audio(), tempo, _context())
    sections = backend.analyze_sections(_audio(), FeatureBundle(), beat_grid, _context())

    assert tempo.ok is True
    assert beat_grid.ok is True
    assert sections.ok is True
    assert call_count == 1


def test_all_in_one_unlocked_enables_activation_summary() -> None:
    class _Activations:
        shape = (10, 4)
        size = 40

        def min(self):
            return 0.1

        def max(self):
            return 0.9

        def mean(self):
            return 0.5

    result = _result()
    result.activations = {"label": _Activations()}  # type: ignore[attr-defined]
    backend = AllInOneUnlockedBackend(analysis_runner=lambda _path, _options: result)

    sections = backend.analyze_sections(_audio(), FeatureBundle(), _beat_grid(), _context())

    assert backend.name == ALL_IN_ONE_UNLOCKED_BACKEND
    assert sections.status == "ok"
    assert sections.provenance.parameters["includeActivations"] is True
    assert sections.provenance.parameters["activationSummary"]["label"] == {
        "shape": [10, 4],
        "min": 0.1,
        "max": 0.9,
        "mean": 0.5,
    }


def test_all_in_one_warns_when_source_mp3_timeline_is_used() -> None:
    backend = AllInOneBackend(
        analysis_runner=lambda _path, _options: _result(),
        prefer_analysis_audio=False,
    )

    tempo = backend.analyze_tempo(_audio(), _context())

    assert tempo.ok is True
    assert tempo.provenance.parameters["timelineMode"] == "source_path"
    assert ALL_IN_ONE_MP3_TIMELINE_WARNING in tempo.provenance.warnings


def test_all_in_one_reports_unavailable_dependency_structurally() -> None:
    def missing_dependency(*_args, **_kwargs):
        raise OptionalDependencyUnavailable(
            DependencyError(
                code="analysis_dependency_missing",
                dependency="torch",
                module_name="torch",
                install_extra="all-in-one",
                message="torch is unavailable",
            )
        )

    backend = AllInOneBackend(dependency_loader=missing_dependency)

    result = backend.analyze_tempo(_audio(), _context())

    assert result.status == "unavailable"
    assert result.error is not None
    assert result.error.backend_name == ALL_IN_ONE_BACKEND
    assert result.error.dependency == "torch"
    assert result.error.details["installExtra"] == "all-in-one"


def test_all_in_one_reports_runner_failures_structurally() -> None:
    def runner(_path, _options):
        raise RuntimeError("model checkpoint download failed")

    backend = AllInOneBackend(analysis_runner=runner)

    result = backend.analyze_beat_grid(_audio(), _tempo(), _context())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "all_in_one_failed"
    assert result.error.details["exceptionType"] == "RuntimeError"


def test_all_in_one_reports_missing_beats_structurally() -> None:
    result = _Result(
        path=Path("fixture-analysis.wav"),
        bpm=142.0,
        beats=[],
        downbeats=[],
        beat_positions=[],
        segments=[],
    )
    backend = AllInOneBackend(analysis_runner=lambda _path, _options: result)

    tempo = backend.analyze_tempo(_audio(), _context())
    beat_grid = backend.analyze_beat_grid(_audio(), tempo, _context())

    assert beat_grid.status == "failed"
    assert beat_grid.error is not None
    assert beat_grid.error.code == "all_in_one_missing_beats"


def test_all_in_one_registers_timing_and_section_backends() -> None:
    registry = BackendRegistry()

    register_all_in_one_backends(registry)

    assert registry.tempo_names() == (ALL_IN_ONE_BACKEND,)
    assert registry.beat_grid_names() == (ALL_IN_ONE_BACKEND,)
    assert registry.section_names() == (ALL_IN_ONE_BACKEND, ALL_IN_ONE_UNLOCKED_BACKEND)
    assert registry.create_tempo(ALL_IN_ONE_BACKEND).name == ALL_IN_ONE_BACKEND
    assert registry.create_beat_grid(ALL_IN_ONE_BACKEND).name == ALL_IN_ONE_BACKEND
    assert registry.create_section(ALL_IN_ONE_BACKEND).name == ALL_IN_ONE_BACKEND
