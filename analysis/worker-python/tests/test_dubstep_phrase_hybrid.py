from pathlib import Path

from autodj_analysis import (
    AnalysisContext,
    BeatGridCandidateResult,
    BeatMarker,
    CandidateProvenance,
    DecodedAudio,
    DubstepPhraseHybridBackend,
    EnergyFeatures,
    FeatureBundle,
    SectionCandidate,
    SectionCandidateResult,
)


def test_dubstep_phrase_hybrid_infers_build_drop_and_break_from_boundaries() -> None:
    backend = DubstepPhraseHybridBackend(
        all_in_one_backend=_FakeBoundaryBackend("all-in-one-unlocked"),
        songformer_backend=_FakeBoundaryBackend("songformer"),
    )

    result = backend.analyze_sections(_audio(), FeatureBundle(energy=_energy_features()), _beat_grid(), _context())

    assert result.status == "ok"
    assert [section.type for section in result.sections] == ["intro", "build", "drop", "outro"]
    assert result.sections[1].start_seconds == 19.2
    assert result.sections[1].end_seconds == 32.0
    assert result.sections[2].start_seconds == 32.0
    assert result.sections[2].end_seconds == 48.0
    assert result.sections[2].provider_metadata["sourceBackend"] == "dubstep-phrase-hybrid"
    assert result.sections[2].provider_metadata["anchorScore"] >= 0.58
    assert result.cue_points[0]["type"] == "drop"


def _audio() -> DecodedAudio:
    return DecodedAudio(
        samples=(0.0, 0.1, -0.1, 0.0),
        sample_rate=44100,
        duration_seconds=64.0,
        channels=1,
        source_path=Path("fixture.wav"),
    )


def _context() -> AnalysisContext:
    return AnalysisContext(
        track_id="track-a",
        source_path=Path("fixture.mp3"),
        analysis_audio_path=Path("fixture.wav"),
        duration_seconds=64.0,
        temp_dir=Path("tmp"),
    )


def _beat_grid() -> BeatGridCandidateResult:
    return BeatGridCandidateResult(
        status="ok",
        provenance=CandidateProvenance(backend_name="current"),
        beats=tuple(BeatMarker(index=index, time_seconds=round(index * 0.4, 6), confidence=0.95) for index in range(170)),
        confidence=0.95,
    )


def _energy_features() -> EnergyFeatures:
    curve = []
    bass = []
    onset = []
    for second in range(65):
        if second < 16:
            energy_value = 0.18
            bass_value = 0.15
        elif second < 32:
            energy_value = 0.38
            bass_value = 0.28
        elif second < 48:
            energy_value = 0.88
            bass_value = 0.80
        else:
            energy_value = 0.25
            bass_value = 0.20
        curve.append({"timeSeconds": float(second), "value": energy_value})
        bass.append({"timeSeconds": float(second), "value": bass_value})
        onset.append({"timeSeconds": float(second), "value": 0.95 if second == 32 else 0.08})
    return EnergyFeatures(
        global_energy=0.4,
        curve=tuple(curve),
        bass_energy_curve=tuple(bass),
        onset_density_curve=tuple(onset),
        warnings=(),
        frame_length=2048,
        hop_length=512,
        curve_point_count=len(curve),
        bass_cutoff_hz=180.0,
    )


class _FakeBoundaryBackend:
    def __init__(self, name: str) -> None:
        self.name = name

    def analyze_sections(self, _audio, _features, _beat_grid, _context) -> SectionCandidateResult:
        return SectionCandidateResult(
            status="ok",
            provenance=CandidateProvenance(backend_name=self.name),
            sections=(
                SectionCandidate("section-verse-001", "verse", 0.0, 16.0, 0.6, source_label="verse"),
                SectionCandidate("section-unknown-001", "unknown", 16.0, 32.0, 0.45, source_label="chorus"),
                SectionCandidate("section-unknown-002", "unknown", 32.0, 48.0, 0.45, source_label="inst"),
                SectionCandidate("section-verse-002", "verse", 48.0, 64.0, 0.6, source_label="verse"),
            ),
        )
