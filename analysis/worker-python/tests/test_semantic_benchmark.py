from pathlib import Path

from autodj_analysis import (
    AnalysisContext,
    BackendRegistry,
    BeatGridCandidateResult,
    BeatMarker,
    CandidateProvenance,
    DecodedAudio,
    FeatureBundle,
    ReferenceSection,
    SectionCandidate,
    SectionCandidateResult,
    SemanticBenchmarkCase,
    TempoCandidateResult,
    evaluate_sections_against_references,
    load_rekordbox_tracks,
    load_semantic_benchmark_cases,
    reference_sections_from_rekordbox,
    run_semantic_section_benchmark,
)


def test_reference_sections_are_derived_from_labeled_rekordbox_cues(tmp_path: Path) -> None:
    track = load_rekordbox_tracks(_write_rekordbox_xml(tmp_path))[0]

    sections = reference_sections_from_rekordbox(track, duration_seconds=64.0)

    assert [section.type for section in sections] == ["intro", "build", "drop", "break"]
    assert [section.id for section in sections] == [
        "section-rekordbox-intro-001",
        "section-rekordbox-build-001",
        "section-rekordbox-drop-001",
        "section-rekordbox-break-001",
    ]
    assert sections[2].start_seconds == 32.0
    assert sections[2].end_seconds == 48.0
    assert sections[2].source_cue_name == "drop_1_start"
    assert sections[2].end_cue_name == "drop_1_end"


def test_semantic_evaluation_reports_missing_and_false_positive_sections() -> None:
    section_result = SectionCandidateResult(
        status="ok",
        provenance=CandidateProvenance(backend_name="candidate", processing_seconds=0.5),
        sections=(
            SectionCandidate(
                id="section-drop-001",
                type="drop",
                start_seconds=32.1,
                end_seconds=47.9,
                confidence=0.7,
                source_label="chorus",
            ),
            SectionCandidate(
                id="section-outro-001",
                type="outro",
                start_seconds=56.0,
                end_seconds=64.0,
                confidence=0.8,
            ),
            SectionCandidate(
                id="section-unknown-001",
                type="unknown",
                start_seconds=0.0,
                end_seconds=16.0,
                confidence=0.3,
            ),
        ),
    )
    references = (
        ReferenceSection("ref-build", "build", 16.0, 32.0, "build_1_start", ordinal=1),
        ReferenceSection("ref-drop", "drop", 32.0, 48.0, "drop_1_start", "drop_1_end", ordinal=1),
    )

    report = evaluate_sections_against_references(
        section_result,
        references,
        candidate_name="candidate",
        track_id="track-a",
        track_name="Track A",
    )

    metrics = report["metrics"]
    assert metrics["matchedSectionCount"] == 1
    assert metrics["missingReferenceSectionCount"] == 1
    assert metrics["falsePositiveSectionCount"] == 1
    assert metrics["missedByType"] == {"build": 1}
    assert metrics["falsePositiveByType"] == {"outro": 1}
    assert metrics["medianStartErrorMilliseconds"] == 100.0
    assert metrics["medianEndErrorMilliseconds"] == 100.0


def test_semantic_benchmark_writes_candidate_artifacts_and_summary(tmp_path: Path) -> None:
    xml_path = _write_rekordbox_xml(tmp_path)
    cases = load_semantic_benchmark_cases(xml_path)
    registry = BackendRegistry()
    registry.register_section("candidate-sections", _FakeSectionBackend)

    summary = run_semantic_section_benchmark(
        cases,
        tmp_path / "benchmark",
        candidates=("candidate-sections",),
        registry=registry,
        audio_loader=_audio_loader,
        analysis_audio_writer=_analysis_audio_writer,
        debug_waveform_builder=_debug_waveform_builder,
        current_backend_factory=_FakeCurrentBackend,
        analysis_sample_rate=44_100,
        debug_waveform_points=128,
    )

    candidate = summary["cases"][0]["candidates"][0]
    assert summary["reportType"] == "semantic-section-candidate-benchmark"
    assert summary["candidateSummary"][0]["matchedSectionCount"] == 2
    assert candidate["status"] == "ok"
    assert candidate["matchedSectionCount"] == 2
    assert Path(candidate["analyzedTrackPath"]).exists()
    assert Path(candidate["debugWaveformPath"]).exists()
    assert Path(candidate["audioPath"]).exists()
    assert Path(candidate["audioPath"]).name == "source-audio.mp3"
    assert Path(candidate["sectionEvaluationPath"]).exists()


def _write_rekordbox_xml(tmp_path: Path) -> Path:
    audio_path = tmp_path / "Track A.mp3"
    audio_path.write_bytes(b"audio")
    location = audio_path.as_uri()
    xml_path = tmp_path / "rekordbox.xml"
    xml_path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="1">
    <TRACK Name="Track A" AverageBpm="150.00" Location="{location}">
      <TEMPO Inizio="0.000" Bpm="150.00" Metro="4/4" Battito="1"/>
      <POSITION_MARK Name="intro_start" Type="0" Start="0.000" Num="0"/>
      <POSITION_MARK Name="build_1_start" Type="0" Start="16.000" Num="1"/>
      <POSITION_MARK Name="drop_1_start" Type="0" Start="32.000" Num="2"/>
      <POSITION_MARK Name="drop_1_end" Type="0" Start="48.000" Num="3"/>
      <POSITION_MARK Name="break_start" Type="0" Start="48.000" Num="4"/>
    </TRACK>
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )
    return xml_path


def _audio_loader(path, *, target_sample_rate):
    return DecodedAudio(
        samples=(0.0, 0.1, -0.1, 0.0),
        sample_rate=target_sample_rate,
        duration_seconds=64.0,
        channels=1,
        source_path=Path(path),
    )


def _analysis_audio_writer(path: Path, _audio: DecodedAudio) -> Path:
    path.write_bytes(b"wav")
    return path


def _debug_waveform_builder(track_id, audio, **kwargs):
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "debug-waveform",
        "trackId": track_id,
        "durationSeconds": audio.duration_seconds,
        "analyzer": {"producer": kwargs["analyzer_producer"]},
        "parameters": {"targetPointCount": kwargs["target_point_count"]},
        "points": [],
    }


class _FakeCurrentResults:
    tempo = TempoCandidateResult(
        status="ok",
        provenance=CandidateProvenance(backend_name="current", processing_seconds=0.1),
        bpm=150.0,
        normalized_bpm=150.0,
        confidence=0.9,
        tempo_class="straight",
    )
    beat_grid = BeatGridCandidateResult(
        status="ok",
        provenance=CandidateProvenance(backend_name="current", processing_seconds=0.1),
        beats=tuple(BeatMarker(index=index, time_seconds=index * 0.4, confidence=0.9) for index in range(160)),
        confidence=0.9,
    )
    sections = SectionCandidateResult(
        status="ok",
        provenance=CandidateProvenance(backend_name="current", processing_seconds=0.1),
        sections=(
            SectionCandidate("section-drop-001", "drop", 32.0, 48.0, 0.7),
        ),
    )


class _FakeCurrentBackend:
    def analyze_candidates(self, _audio, _context):
        return _FakeCurrentResults()


class _FakeSectionBackend:
    name = "candidate-sections"

    def analyze_sections(
        self,
        _audio: DecodedAudio,
        _features: FeatureBundle,
        _beat_grid: BeatGridCandidateResult,
        _context: AnalysisContext,
    ) -> SectionCandidateResult:
        return SectionCandidateResult(
            status="ok",
            provenance=CandidateProvenance(backend_name=self.name, processing_seconds=0.2),
            sections=(
                SectionCandidate("section-build-001", "build", 16.0, 32.0, 0.75),
                SectionCandidate("section-drop-001", "drop", 32.0, 48.0, 0.8),
            ),
        )
