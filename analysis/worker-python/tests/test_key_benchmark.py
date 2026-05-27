from __future__ import annotations

from pathlib import Path

from autodj_analysis import (
    BackendRegistry,
    CandidateProvenance,
    KeyCandidate,
    KeyCandidateResult,
    load_key_benchmark_cases,
    load_rekordbox_key_truth,
    run_key_benchmark,
)
from autodj_analysis.audio_io import DecodedAudio


class _ExactKeyBackend:
    name = "exact-key"

    def analyze_key(self, audio, context):
        return KeyCandidateResult(
            status="ok",
            provenance=CandidateProvenance(backend_name=self.name, processing_seconds=0.25),
            tonic="E",
            mode="minor",
            camelot="9A",
            confidence=0.9,
            candidates=(
                KeyCandidate(
                    tonic="E",
                    mode="minor",
                    camelot="9A",
                    confidence=0.9,
                    backend=self.name,
                ),
            ),
        )


class _AdjacentKeyBackend:
    name = "adjacent-key"

    def analyze_key(self, audio, context):
        return KeyCandidateResult(
            status="ok",
            provenance=CandidateProvenance(backend_name=self.name, processing_seconds=0.5),
            tonic="B",
            mode="minor",
            camelot="10A",
            confidence=0.7,
            candidates=(
                KeyCandidate(
                    tonic="B",
                    mode="minor",
                    camelot="10A",
                    confidence=0.7,
                    backend=self.name,
                ),
            ),
        )


def test_load_rekordbox_key_truth_keeps_truth_separate_from_analysis(tmp_path: Path) -> None:
    truth = load_rekordbox_key_truth(_write_rekordbox_xml(tmp_path))

    assert truth.scored_count == 1
    assert truth.unscored_count == 2
    assert truth.rows[0].track_name == "Valid Key"
    assert truth.rows[0].camelot is not None
    assert truth.rows[0].camelot.camelot == "9A"
    assert truth.rows[0].camelot.tonic == "E"
    assert truth.rows[0].status == "scored"
    assert truth.rows[1].status == "unscored"
    assert truth.rows[1].warnings[0]["code"] == "rekordbox_tonality_missing"
    assert truth.rows[2].warnings[0]["code"] == "camelot_invalid"

    payload = truth.to_dict()
    assert payload["reportType"] == "rekordbox-key-truth-table"
    assert payload["scoredTracks"] == 1
    assert payload["unscoredTracks"] == 2
    assert payload["tracks"][0]["truth"]["camelot"] == "9A"


def test_run_key_benchmark_scores_exact_and_compatible_candidates(tmp_path: Path) -> None:
    audio_path = tmp_path / "valid.mp3"
    audio_path.write_bytes(b"fake")
    xml_path = _write_single_track_rekordbox_xml(tmp_path, audio_path)
    registry = BackendRegistry()
    registry.register_key("exact-key", _ExactKeyBackend)
    registry.register_key("adjacent-key", _AdjacentKeyBackend)

    summary = run_key_benchmark(
        load_key_benchmark_cases(xml_path),
        tmp_path / "key-benchmark",
        candidates=("exact-key", "adjacent-key"),
        registry=registry,
        audio_loader=_fake_audio_loader,
        analysis_sample_rate=22_050,
        created_at_utc="2026-05-22T00:00:00Z",
    )

    assert summary["reportType"] == "key-candidate-benchmark"
    assert summary["truthSummary"]["scoredTracks"] == 1
    assert summary["candidateSummary"][0]["exactCamelotAccuracy"] == 1.0
    assert summary["candidateSummary"][1]["exactCamelotAccuracy"] == 0.0
    assert summary["candidateSummary"][1]["compatibleAccuracy"] == 1.0
    assert summary["cases"][0]["candidates"][0]["score"]["exactCamelotMatch"] is True
    assert summary["cases"][0]["candidates"][1]["score"]["compatibility"]["classification"] == "adjacent"
    assert (tmp_path / "key-benchmark" / "valid" / "exact-key" / "key-candidate.json").exists()


def _write_rekordbox_xml(tmp_path: Path) -> Path:
    xml_path = tmp_path / "rekordbox-keys.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="3">
    <TRACK Name="Valid Key" AverageBpm="140.00" Tonality=" 09a " Location="file://localhost/valid.mp3">
      <TEMPO Inizio="0.000" Bpm="140.00" Metro="4/4" Battito="1"/>
    </TRACK>
    <TRACK Name="Missing Key" AverageBpm="150.00" Tonality="" Location="file://localhost/missing.mp3">
      <TEMPO Inizio="0.000" Bpm="150.00" Metro="4/4" Battito="1"/>
    </TRACK>
    <TRACK Name="Bad Key" AverageBpm="145.00" Tonality="13Z" Location="file://localhost/bad.mp3">
      <TEMPO Inizio="0.000" Bpm="145.00" Metro="4/4" Battito="1"/>
    </TRACK>
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )
    return xml_path


def _write_single_track_rekordbox_xml(tmp_path: Path, audio_path: Path) -> Path:
    xml_path = tmp_path / "single-track.xml"
    xml_path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="1">
    <TRACK Name="Valid Key" AverageBpm="140.00" Tonality="9A" Location="{audio_path.as_uri()}">
      <TEMPO Inizio="0.000" Bpm="140.00" Metro="4/4" Battito="1"/>
    </TRACK>
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )
    return xml_path


def _fake_audio_loader(audio_path: Path, *, target_sample_rate: int):
    return DecodedAudio(
        samples=[0.0, 1.0, 0.0],
        sample_rate=target_sample_rate,
        duration_seconds=1.0,
        channels=1,
        source_path=audio_path,
    )
