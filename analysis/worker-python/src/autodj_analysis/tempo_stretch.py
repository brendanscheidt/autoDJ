"""Pitch-preserving tempo-stretch helpers for offline audition renders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import subprocess
import tempfile
import time
from typing import Callable, Sequence
import wave


TEMPO_STRETCH_REPORT_TYPE = "tempo-stretch-report"
TEMPO_STRETCH_SMOKE_REPORT_TYPE = "tempo-stretch-smoke-report"
DEFAULT_TEMPO_STRETCH_BACKENDS = ("rubberband", "soundstretch")
RUBBERBAND_LICENSE_NOTE = "GPL/commercial licensing; product distribution needs review."
SOUNDTOUCH_LICENSE_NOTE = "SoundTouch/SoundStretch is LGPL 2.1."


@dataclass(frozen=True)
class TempoStretchOptions:
    source_bpm: float
    target_bpm: float
    backend: str = "rubberband"
    sample_rate: int = 44_100
    quality: str = "fine"
    preserve_pitch: bool = True
    target_bpm_bias: float = 0.0
    ffmpeg_path: str = "ffmpeg"


@dataclass(frozen=True)
class TempoStretchResult:
    ok: bool
    input_path: Path
    output_path: Path
    report_path: Path | None
    backend_name: str
    backend_version: str | None
    source_bpm: float
    target_bpm: float
    requested_target_bpm: float
    tempo_ratio: float
    preserve_pitch: bool
    quality_mode: str
    sample_rate: int
    target_bpm_bias: float
    input_duration_seconds: float | None
    output_duration_seconds: float | None
    runtime_seconds: float
    command: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "ok": self.ok,
            "artifact": TEMPO_STRETCH_REPORT_TYPE,
            "inputPath": str(self.input_path),
            "outputPath": str(self.output_path),
            "backendName": self.backend_name,
            "backendVersion": self.backend_version,
            "sourceBpm": self.source_bpm,
            "targetBpm": self.target_bpm,
            "requestedTargetBpm": self.requested_target_bpm,
            "tempoRatio": self.tempo_ratio,
            "preservePitch": self.preserve_pitch,
            "qualityMode": self.quality_mode,
            "sampleRate": self.sample_rate,
            "targetBpmBias": self.target_bpm_bias,
            "inputDurationSeconds": self.input_duration_seconds,
            "outputDurationSeconds": self.output_duration_seconds,
            "runtimeSeconds": self.runtime_seconds,
            "command": list(self.command),
            "warnings": list(self.warnings),
        }
        if self.report_path is not None:
            payload["reportPath"] = str(self.report_path)
        if self.error is not None:
            payload["error"] = self.error
        return payload


class TempoStretchError(ValueError):
    """Expected tempo-stretch setup or execution failure."""

    def __init__(self, code: str, message: str, *, command: Sequence[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.command = tuple(command or ())

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.command:
            payload["command"] = " ".join(self.command)
        return payload


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def stretch_audio_file(
    audio_path: str | Path,
    output_wav: str | Path,
    *,
    report_path: str | Path | None = None,
    options: TempoStretchOptions,
    command_runner: CommandRunner | None = None,
) -> TempoStretchResult:
    """Render one pitch-preserving tempo-stretched WAV and optional report."""

    source = Path(audio_path)
    output = Path(output_wav)
    report = Path(report_path) if report_path is not None else None
    runner = command_runner or _run_command
    _validate_options(options)
    if not source.exists():
        raise TempoStretchError("source_missing", f"Audio source does not exist: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)

    backend = _normalize_backend(options.backend)
    effective_target_bpm = _biased_target_bpm(options.target_bpm, options.target_bpm_bias)
    ratio = effective_target_bpm / options.source_bpm
    warnings = _quality_warnings(ratio, options)
    started = time.perf_counter()
    version = _backend_version(backend, runner)
    input_duration: float | None = None
    output_duration: float | None = None
    stretch_command: tuple[str, ...] = ()

    with tempfile.TemporaryDirectory(prefix="autodj-tempo-stretch-") as tmp:
        tmp_path = Path(tmp)
        input_wav = tmp_path / "input.wav"
        converted = _convert_to_wav(
            source,
            input_wav,
            sample_rate=options.sample_rate,
            ffmpeg_path=options.ffmpeg_path,
            runner=runner,
        )
        input_duration = _wav_duration_seconds(input_wav)
        stretch_command = _stretch_command(
            backend,
            input_wav,
            output,
            tempo_ratio=ratio,
            quality=options.quality,
        )
        _run_checked(stretch_command, runner, code=f"{backend}_failed")
        output_duration = _wav_duration_seconds(output)

    result = TempoStretchResult(
        ok=True,
        input_path=source,
        output_path=output,
        report_path=report,
        backend_name=backend,
        backend_version=version,
        source_bpm=float(options.source_bpm),
        target_bpm=float(effective_target_bpm),
        requested_target_bpm=float(options.target_bpm),
        tempo_ratio=float(ratio),
        preserve_pitch=options.preserve_pitch,
        quality_mode=_quality_mode(backend, options.quality),
        sample_rate=int(options.sample_rate),
        target_bpm_bias=float(options.target_bpm_bias),
        input_duration_seconds=input_duration,
        output_duration_seconds=output_duration,
        runtime_seconds=float(time.perf_counter() - started),
        command=stretch_command,
        warnings=tuple(warnings + converted),
    )
    if report is not None:
        report.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return result


def run_tempo_stretch_smoke(
    audio_path: str | Path,
    output_root: str | Path,
    *,
    source_bpm: float,
    target_bpm: float,
    backends: Sequence[str] = DEFAULT_TEMPO_STRETCH_BACKENDS,
    sample_rate: int = 44_100,
    quality: str = "fine",
    target_bpm_bias: float = 0.0,
    command_runner: CommandRunner | None = None,
) -> dict[str, object]:
    """Run a smoke render for every requested backend and write a summary."""

    source = Path(audio_path)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    ok = True
    for backend in backends:
        backend_name = _normalize_backend(backend)
        backend_dir = root / backend_name
        backend_dir.mkdir(parents=True, exist_ok=True)
        output_wav = backend_dir / "stretched.wav"
        report_path = backend_dir / "tempo-stretch-report.json"
        try:
            result = stretch_audio_file(
                source,
                output_wav,
                report_path=report_path,
                options=TempoStretchOptions(
                    source_bpm=source_bpm,
                    target_bpm=target_bpm,
                    backend=backend_name,
                    sample_rate=sample_rate,
                    quality=quality,
                    target_bpm_bias=target_bpm_bias,
                ),
                command_runner=command_runner,
            )
            results.append(result.to_dict())
        except TempoStretchError as exc:
            ok = False
            results.append(
                {
                    "ok": False,
                    "artifact": TEMPO_STRETCH_REPORT_TYPE,
                    "inputPath": str(source),
                    "outputPath": str(output_wav),
                    "reportPath": str(report_path),
                    "backendName": backend_name,
                    "sourceBpm": source_bpm,
                    "targetBpm": target_bpm,
                    "requestedTargetBpm": target_bpm,
                    "tempoRatio": target_bpm / source_bpm if source_bpm else None,
                    "error": exc.to_dict(),
                }
            )

    summary = {
        "ok": ok,
        "artifact": TEMPO_STRETCH_SMOKE_REPORT_TYPE,
        "inputPath": str(source),
        "outputRoot": str(root),
        "sourceBpm": source_bpm,
        "targetBpm": target_bpm,
        "targetBpmBias": target_bpm_bias,
        "backends": list(backends),
        "results": results,
    }
    (root / "tempo-stretch-smoke-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def _validate_options(options: TempoStretchOptions) -> None:
    if options.source_bpm <= 0 or not math.isfinite(options.source_bpm):
        raise TempoStretchError("invalid_source_bpm", "source_bpm must be a finite positive value")
    if options.target_bpm <= 0 or not math.isfinite(options.target_bpm):
        raise TempoStretchError("invalid_target_bpm", "target_bpm must be a finite positive value")
    if options.sample_rate <= 0:
        raise TempoStretchError("invalid_sample_rate", "sample_rate must be a positive integer")
    if not math.isfinite(options.target_bpm_bias):
        raise TempoStretchError("invalid_target_bpm_bias", "target_bpm_bias must be finite")
    if not options.preserve_pitch:
        raise TempoStretchError(
            "preserve_pitch_required",
            "Spec 009 tempo stretching requires preserve_pitch=true.",
        )
    _normalize_backend(options.backend)


def _biased_target_bpm(target_bpm: float, target_bpm_bias: float) -> float:
    if target_bpm_bias == 0.0:
        return float(target_bpm)
    biased = target_bpm + target_bpm_bias
    if biased <= 0.0:
        raise TempoStretchError("invalid_target_bpm_bias", "target_bpm plus target_bpm_bias must be positive")
    return float(biased)


def _normalize_backend(backend: str) -> str:
    normalized = backend.strip().lower().replace("_", "-")
    aliases = {
        "rubber-band": "rubberband",
        "rubberband-cli": "rubberband",
        "soundtouch": "soundstretch",
        "soundtouch-cli": "soundstretch",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"rubberband", "soundstretch"}:
        raise TempoStretchError(
            "unsupported_tempo_stretch_backend",
            f"Unsupported tempo-stretch backend: {backend}",
        )
    return normalized


def _quality_mode(backend: str, quality: str) -> str:
    if backend == "rubberband":
        if quality == "fast":
            return "fast"
        if quality == "fine-centre":
            return "fine-centre"
        return "fine"
    return "standard"


def _quality_warnings(ratio: float, options: TempoStretchOptions) -> list[str]:
    warnings: list[str] = []
    percent_change = abs(ratio - 1.0) * 100.0
    if percent_change > 6.0:
        warnings.append(
            f"Tempo ratio changes playback speed by {percent_change:.2f}%; audition quality carefully."
        )
    if abs(options.target_bpm - options.source_bpm) > 10.0:
        warnings.append(
            "Requested BPM delta exceeds the default automatic planner gate of 10 BPM per deck."
        )
    return warnings


def _convert_to_wav(
    source: Path,
    output: Path,
    *,
    sample_rate: int,
    ffmpeg_path: str,
    runner: CommandRunner,
) -> list[str]:
    command = (
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-ar",
        str(sample_rate),
        "-ac",
        "2",
        str(output),
    )
    _run_checked(command, runner, code="ffmpeg_convert_failed")
    return []


def _stretch_command(
    backend: str,
    input_wav: Path,
    output_wav: Path,
    *,
    tempo_ratio: float,
    quality: str,
) -> tuple[str, ...]:
    if backend == "rubberband":
        command = ["rubberband", "--quiet", "--tempo", f"{tempo_ratio:.12g}"]
        if quality == "fast":
            command.append("--fast")
        else:
            command.append("--fine")
            if quality == "fine-centre":
                command.append("--centre-focus")
        command.extend([str(input_wav), str(output_wav)])
        return tuple(command)
    if backend == "soundstretch":
        tempo_percent = (tempo_ratio - 1.0) * 100.0
        return (
            "soundstretch",
            str(input_wav),
            str(output_wav),
            f"-tempo={tempo_percent:.12g}",
        )
    raise TempoStretchError(
        "unsupported_tempo_stretch_backend",
        f"Unsupported tempo-stretch backend: {backend}",
    )


def _backend_version(backend: str, runner: CommandRunner) -> str | None:
    command = ("rubberband", "--version") if backend == "rubberband" else ("soundstretch", "-license")
    try:
        completed = runner(command)
    except OSError:
        return None
    text = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    if backend == "rubberband":
        return text.splitlines()[0].strip() if text else None
    if backend == "soundstretch":
        return "2.3.2" if "SoundStretch v2.3.2" in text else _first_soundstretch_version(text)
    return None


def _first_soundstretch_version(text: str) -> str | None:
    for line in text.splitlines():
        if "SoundStretch v" in line:
            return line.split("SoundStretch v", 1)[1].split()[0].strip()
    return None


def _wav_duration_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.getnframes()
            sample_rate = wav_file.getframerate()
    except (wave.Error, OSError):
        return None
    if sample_rate <= 0:
        return None
    return float(frames / sample_rate)


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
    )


def _run_checked(command: Sequence[str], runner: CommandRunner, *, code: str) -> subprocess.CompletedProcess[str]:
    try:
        completed = runner(command)
    except FileNotFoundError as exc:
        raise TempoStretchError(
            "tempo_stretch_executable_missing",
            f"Executable was not found: {command[0]}",
            command=command,
        ) from exc
    except OSError as exc:
        raise TempoStretchError(
            code,
            f"Could not run command: {exc}",
            command=command,
        ) from exc
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        message = f"Command failed with exit code {completed.returncode}"
        if details:
            message += f": {details}"
        raise TempoStretchError(code, message, command=command)
    return completed
