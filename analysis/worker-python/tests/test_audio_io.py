from __future__ import annotations

import importlib.util
from pathlib import Path
import wave

import pytest

from audio_fixtures import create_140_bpm_click_fixture, create_silence_fixture
from autodj_analysis.audio_io import AudioLoadError, DEFAULT_ANALYSIS_SAMPLE_RATE, load_audio


def test_load_audio_rejects_unsupported_extensions_before_importing_analysis_dependencies(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "notes.txt"
    source_path.write_text("not audio", encoding="utf-8")

    with pytest.raises(AudioLoadError) as exc_info:
        load_audio(source_path, source_uri="notes.txt", track_id="track-notes")

    error = exc_info.value.to_dict()
    assert error["code"] == "audio_unsupported_format"
    assert error["trackId"] == "track-notes"
    assert error["sourceUri"] == "notes.txt"
    assert "Unsupported audio file extension" in error["message"]


def test_load_audio_reports_missing_source_as_structured_error(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.wav"

    with pytest.raises(AudioLoadError) as exc_info:
        load_audio(missing_path, source_uri="missing.wav", track_id="track-missing")

    error = exc_info.value.to_dict()
    assert error["code"] == "source_missing"
    assert error["trackId"] == "track-missing"
    assert error["sourceUri"] == "missing.wav"


def test_load_audio_reports_missing_analysis_dependency(monkeypatch, tmp_path: Path) -> None:
    fixture = create_140_bpm_click_fixture(tmp_path)

    def missing_dependency(*args, **kwargs):
        from autodj_analysis.dependencies import DependencyError, OptionalDependencyUnavailable

        raise OptionalDependencyUnavailable(
            DependencyError(
                code="analysis_dependency_missing",
                dependency="soundfile",
                module_name="soundfile",
                install_extra="analysis",
                message="Install the worker with the 'analysis' extra and retry.",
            )
        )

    monkeypatch.setattr("autodj_analysis.audio_io.require_optional_dependency", missing_dependency)

    with pytest.raises(AudioLoadError) as exc_info:
        load_audio(fixture.path, source_uri="click.wav", track_id="track-click")

    error = exc_info.value.to_dict()
    assert error["code"] == "audio_dependency_missing"
    assert error["trackId"] == "track-click"
    assert error["sourceUri"] == "click.wav"
    assert "analysis" in error["message"]


@pytest.mark.analysis
def test_load_audio_reads_generated_wav_as_mono_float_pcm(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_140_bpm_click_fixture(tmp_path)

    decoded = load_audio(fixture.path, source_uri="click-140.wav", track_id="track-click")

    assert decoded.source_path == fixture.path
    assert decoded.sample_rate == DEFAULT_ANALYSIS_SAMPLE_RATE
    assert decoded.channels == 1
    assert decoded.samples.ndim == 1
    assert decoded.samples.dtype.name == "float32"
    assert decoded.samples.shape[0] == round(fixture.duration_seconds * decoded.sample_rate)
    assert decoded.duration_seconds == pytest.approx(fixture.duration_seconds)
    assert float(abs(decoded.samples).max()) > 0.40


@pytest.mark.analysis
def test_load_audio_can_preserve_native_sample_rate(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_140_bpm_click_fixture(tmp_path, sample_rate=11_025, duration_seconds=2.0)

    decoded = load_audio(fixture.path, target_sample_rate=None)

    assert decoded.sample_rate == 11_025
    assert decoded.samples.shape[0] == round(fixture.duration_seconds * decoded.sample_rate)
    assert decoded.duration_seconds == pytest.approx(2.0)


@pytest.mark.analysis
def test_load_audio_resamples_to_analysis_sample_rate(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies(require_librosa=True)
    fixture = create_140_bpm_click_fixture(tmp_path, sample_rate=11_025, duration_seconds=2.0)

    decoded = load_audio(fixture.path)

    assert decoded.sample_rate == DEFAULT_ANALYSIS_SAMPLE_RATE
    assert decoded.samples.shape[0] == round(fixture.duration_seconds * DEFAULT_ANALYSIS_SAMPLE_RATE)
    assert decoded.duration_seconds == pytest.approx(2.0)


@pytest.mark.analysis
def test_load_audio_reports_malformed_wav_as_decode_error(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    source_path = tmp_path / "malformed.wav"
    source_path.write_bytes(b"not a valid wav file")

    with pytest.raises(AudioLoadError) as exc_info:
        load_audio(source_path, source_uri="malformed.wav", track_id="track-bad")

    error = exc_info.value.to_dict()
    assert error["code"] == "audio_decode_error"
    assert error["trackId"] == "track-bad"
    assert error["sourceUri"] == "malformed.wav"


@pytest.mark.analysis
def test_load_audio_reports_empty_wav_as_audio_empty(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    source_path = tmp_path / "empty.wav"
    with wave.open(str(source_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(DEFAULT_ANALYSIS_SAMPLE_RATE)
        wav_file.writeframes(b"")

    with pytest.raises(AudioLoadError) as exc_info:
        load_audio(source_path, source_uri="empty.wav", track_id="track-empty")

    error = exc_info.value.to_dict()
    assert error["code"] == "audio_empty"
    assert error["trackId"] == "track-empty"
    assert error["sourceUri"] == "empty.wav"


@pytest.mark.analysis
def test_load_audio_accepts_generated_silence_fixture(tmp_path: Path) -> None:
    _skip_without_analysis_dependencies()
    fixture = create_silence_fixture(tmp_path)

    decoded = load_audio(fixture.path)

    assert decoded.sample_rate == DEFAULT_ANALYSIS_SAMPLE_RATE
    assert decoded.duration_seconds == pytest.approx(fixture.duration_seconds)
    assert float(abs(decoded.samples).max()) == 0.0


def _skip_without_analysis_dependencies(*, require_librosa: bool = False) -> None:
    modules = ["numpy", "soundfile"]
    if require_librosa:
        modules.append("librosa")

    missing = [module for module in modules if importlib.util.find_spec(module) is None]
    if missing:
        pytest.skip(
            "analysis dependencies are not installed; missing "
            + ", ".join(missing)
            + ". Install the worker with `[analysis]`."
        )
