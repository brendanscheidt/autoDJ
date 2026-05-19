from __future__ import annotations

import json
from pathlib import Path

from autodj_analysis import (
    AnalysisContext,
    BackendExecutionError,
    BackendRegistry,
    BeatGridCandidateResult,
    BeatMarker,
    CandidateProvenance,
    DecodedAudio,
    TempoCandidate,
    TempoCandidateResult,
    TimingBenchmarkCase,
    load_timing_benchmark_cases,
    run_timing_benchmark,
)


class _TempoAndBeatBackend:
    name = "tempo-and-beat"

    def analyze_tempo(self, audio: DecodedAudio, context: AnalysisContext) -> TempoCandidateResult:
        return TempoCandidateResult(
            status="ok",
            provenance=CandidateProvenance(
                backend_name=self.name,
                model_name="fixture-model",
                processing_seconds=0.25,
                parameters={"duration": context.duration_seconds, "sampleRate": audio.sample_rate},
            ),
            bpm=150.5,
            normalized_bpm=150.5,
            confidence=0.82,
            tempo_class="straight",
            candidates=(TempoCandidate(bpm=150.5, confidence=0.82, backend=self.name),),
        )

    def analyze_beat_grid(
        self,
        audio: DecodedAudio,
        tempo: TempoCandidateResult,
        context: AnalysisContext,
    ) -> BeatGridCandidateResult:
        del audio, context
        beats = tuple(
            BeatMarker(index=index, time_seconds=0.103 + index * 0.4, confidence=0.8)
            for index in range(6)
        )
        return BeatGridCandidateResult(
            status="ok",
            provenance=CandidateProvenance(
                backend_name=self.name,
                processing_seconds=0.15,
                parameters={"tempoStatus": tempo.status},
            ),
            beats=beats,
            downbeats=(BeatMarker(index=0, time_seconds=0.103, beat_in_bar=1, confidence=0.8),),
            confidence=0.8,
            offset_seconds=0.103,
        )


class _BeatOnlyBackend:
    name = "beat-only"

    def analyze_beat_grid(
        self,
        audio: DecodedAudio,
        tempo: TempoCandidateResult,
        context: AnalysisContext,
    ) -> BeatGridCandidateResult:
        del audio, tempo, context
        beats = tuple(
            BeatMarker(index=index, time_seconds=0.098 + index * 0.4, confidence=0.91)
            for index in range(6)
        )
        return BeatGridCandidateResult(
            status="ok",
            provenance=CandidateProvenance(
                backend_name=self.name,
                processing_seconds=0.4,
                parameters={"modelLoadSeconds": 0.1},
            ),
            beats=beats,
            downbeats=(BeatMarker(index=0, time_seconds=0.098, beat_in_bar=1, confidence=0.91),),
            confidence=0.91,
            offset_seconds=0.098,
        )


class _UnavailableBackend:
    name = "unavailable"

    def analyze_tempo(self, audio: DecodedAudio, context: AnalysisContext) -> TempoCandidateResult:
        del audio, context
        return TempoCandidateResult(
            status="unavailable",
            provenance=CandidateProvenance(backend_name=self.name),
            error=BackendExecutionError(
                code="fixture_missing_dependency",
                message="fixture dependency missing",
                backend_name=self.name,
                dependency="fixture",
            ),
        )

    def analyze_beat_grid(
        self,
        audio: DecodedAudio,
        tempo: TempoCandidateResult,
        context: AnalysisContext,
    ) -> BeatGridCandidateResult:
        del audio, context
        return BeatGridCandidateResult(
            status="failed",
            provenance=CandidateProvenance(backend_name=self.name, parameters={"tempoStatus": tempo.status}),
            error=BackendExecutionError(
                code="tempo_result_not_ok",
                message="tempo was unavailable",
                backend_name=self.name,
            ),
        )


def test_run_timing_benchmark_writes_candidate_artifacts_reports_and_summary(tmp_path: Path) -> None:
    registry = BackendRegistry()
    registry.register_tempo("tempo-and-beat", _TempoAndBeatBackend)
    registry.register_beat_grid("tempo-and-beat", _TempoAndBeatBackend)
    registry.register_beat_grid("beat-only", _BeatOnlyBackend)
    case = TimingBenchmarkCase(
        track_id="fixture-track",
        audio_path=tmp_path / "track.wav",
        rekordbox_xml_path=_write_rekordbox_xml(tmp_path),
    )
    case.audio_path.write_bytes(b"fake")

    summary = run_timing_benchmark(
        [case],
        tmp_path / "benchmark",
        candidates=("tempo-and-beat", "beat-only"),
        registry=registry,
        audio_loader=_audio_loader,
        analysis_audio_writer=_audio_writer,
        debug_waveform_builder=_debug_waveform,
        created_at_utc="2026-05-17T00:00:00Z",
    )

    assert summary["reportType"] == "timing-candidate-benchmark"
    assert summary["candidateSummary"][0]["candidate"] == "tempo-and-beat"
    assert summary["candidateSummary"][0]["ok"] == 1
    assert summary["candidateSummary"][1]["candidate"] == "beat-only"
    assert summary["candidateSummary"][1]["bpmAbsoluteError"] == 0.0

    tempo_artifact_path = tmp_path / "benchmark" / "fixture-track" / "tempo-and-beat" / "analyzed-track.json"
    beat_only_artifact_path = tmp_path / "benchmark" / "fixture-track" / "beat-only" / "analyzed-track.json"
    report_path = tmp_path / "benchmark" / "fixture-track" / "tempo-and-beat" / "rekordbox-evaluation.json"

    assert tempo_artifact_path.exists()
    assert beat_only_artifact_path.exists()
    assert report_path.exists()
    assert (tmp_path / "benchmark" / "timing-benchmark-summary.json").exists()
    assert (tmp_path / "benchmark" / "fixture-track" / "beat-only" / "debug-waveform.json").exists()

    beat_only_artifact = json.loads(beat_only_artifact_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert beat_only_artifact["tempo"]["bpm"] == 150.0
    assert beat_only_artifact["tempo"]["provenance"]["backendName"] == "beat-only-derived-tempo"
    assert beat_only_artifact["beatGrid"]["downbeats"][0]["beatInBar"] == 1
    assert report["candidate"]["name"] == "tempo-and-beat"
    assert report["candidate"]["processingSeconds"] == 0.4
    assert report["metrics"]["beatGrid"]["firstBeatOffsetMilliseconds"] == 5.0


def test_run_timing_benchmark_records_unavailable_candidate_without_crashing(tmp_path: Path) -> None:
    registry = BackendRegistry()
    registry.register_tempo("unavailable", _UnavailableBackend)
    registry.register_beat_grid("unavailable", _UnavailableBackend)
    case = TimingBenchmarkCase(
        track_id="fixture-track",
        audio_path=tmp_path / "track.wav",
        rekordbox_xml_path=_write_rekordbox_xml(tmp_path),
    )
    case.audio_path.write_bytes(b"fake")

    summary = run_timing_benchmark(
        [case],
        tmp_path / "benchmark",
        candidates=("unavailable",),
        registry=registry,
        audio_loader=_audio_loader,
        analysis_audio_writer=_audio_writer,
        debug_waveform_builder=_debug_waveform,
    )

    candidate = summary["cases"][0]["candidates"][0]
    report = json.loads(Path(candidate["rekordboxEvaluationPath"]).read_text(encoding="utf-8"))

    assert candidate["status"] == "unavailable"
    assert candidate["error"]["errors"][0]["code"] == "fixture_missing_dependency"
    assert report["candidate"]["status"] == "unavailable"
    assert report["metrics"]["beatGrid"]["candidateBeatCount"] == 0


def test_load_timing_benchmark_cases_accepts_object_or_list_and_coerces_windows_paths(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "trackId": "win",
                        "audioPath": r"C:\Users\Brendan\Desktop\Music\track.mp3",
                        "rekordboxXmlPath": r"C:\Users\Brendan\Desktop\track.xml",
                        "trackName": "Track",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cases = load_timing_benchmark_cases(cases_path)

    assert cases[0].track_id == "win"
    assert cases[0].track_name == "Track"
    if Path("/mnt/c").anchor:
        assert str(cases[0].audio_path).replace("\\", "/").endswith("/Users/Brendan/Desktop/Music/track.mp3")


def _audio_loader(path: Path, *, target_sample_rate: int) -> DecodedAudio:
    return DecodedAudio(
        samples=[0.0, 0.1, -0.1, 0.0],
        sample_rate=target_sample_rate,
        duration_seconds=2.2,
        channels=1,
        source_path=Path(path),
    )


def _audio_writer(path: Path, audio: DecodedAudio) -> Path:
    del audio
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"wav")
    return path


def _debug_waveform(*_args, **_kwargs) -> dict:
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "debug-waveform",
        "trackId": "fixture-track",
        "durationSeconds": 2.2,
        "points": [{"timeSeconds": 0.0, "low": 0.0, "mid": 0.0, "high": 0.0}],
    }


def _write_rekordbox_xml(tmp_path: Path) -> Path:
    xml_path = tmp_path / "rekordbox.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="1">
    <TRACK Name="Fixture Track" AverageBpm="150.00" Location="file://localhost/fixture.mp3">
      <TEMPO Inizio="0.098" Bpm="150.00" Metro="4/4" Battito="1"/>
      <POSITION_MARK Name="" Type="0" Start="0.898" Num="0" Red="255" Green="55" Blue="111"/>
      <POSITION_MARK Name="" Type="0" Start="1.698" Num="1" Red="69" Green="172" Blue="219"/>
    </TRACK>
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )
    return xml_path
