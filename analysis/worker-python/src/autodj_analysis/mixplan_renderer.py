"""Offline MixPlan audition renderer for the playback-engine POC."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import json
import math
from pathlib import Path
import wave
from urllib.parse import unquote, urlparse
from typing import Any, Sequence

from .audio_io import AudioLoadError, load_audio
from .canonical_audio import (
    CANONICAL_AUDIO_FILENAME,
    CANONICAL_AUDIO_METADATA_FILENAME,
    CANONICAL_TIMELINE_POLICY,
)
from .tempo_mapping import source_seconds_to_stretched_seconds
from .tempo_stretch import TempoStretchError, TempoStretchOptions, stretch_audio_file


DEFAULT_RENDER_SAMPLE_RATE = 44_100
DEFAULT_LOW_CUTOFF_HZ = 180.0


class MixPlanRenderError(ValueError):
    """Expected MixPlan render failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class RenderOptions:
    sample_rate: int = DEFAULT_RENDER_SAMPLE_RATE
    asset_root: Path | None = None
    output_filename: str = "audition.wav"
    summary_filename: str = "render-summary.json"
    trace_filename: str = "state-trace.json"
    low_cutoff_hz: float = DEFAULT_LOW_CUTOFF_HZ
    reverb_highpass_cutoff_hz: float = 320.0
    reverb_delay_seconds: float = 0.14
    reverb_decay_reference_delay_seconds: float = 0.04
    reverb_feedback: float = 0.78
    reverb_return_gain: float = 1.05
    echo_delay_seconds: float = 0.5
    echo_feedback: float = 0.48
    echo_return_gain: float = 0.65
    output_gain: float = 1.0
    tempo_backend: str = "soundstretch"
    tempo_quality: str = "standard"
    ffmpeg_path: str = "ffmpeg"


@dataclass(frozen=True)
class RenderResult:
    output_wav: Path
    summary_path: Path
    trace_path: Path
    duration_seconds: float
    sample_rate: int
    frames: int
    transition_templates: tuple[str, ...]
    automation_controls: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "artifact": "mixplan-audition-render",
            "outputWav": str(self.output_wav),
            "summaryPath": str(self.summary_path),
            "tracePath": str(self.trace_path),
            "durationSeconds": self.duration_seconds,
            "sampleRate": self.sample_rate,
            "frames": self.frames,
            "transitionTemplates": list(self.transition_templates),
            "automationControls": list(self.automation_controls),
        }


@dataclass(frozen=True)
class LoadedAudio:
    samples: Sequence[float]
    sample_rate: int
    source_path: Path


def render_mix_plan_file(mix_plan_path: str | Path, out_dir: str | Path, options: RenderOptions | None = None) -> RenderResult:
    """Render a contract-shaped MixPlan JSON file to local WAV audition artifacts."""

    mix_plan_path = Path(mix_plan_path)
    out_dir = Path(out_dir)
    options = options or RenderOptions()
    if options.sample_rate <= 0:
        raise MixPlanRenderError("invalid_sample_rate", "Render sample rate must be greater than zero")
    if options.low_cutoff_hz <= 0.0:
        raise MixPlanRenderError("invalid_low_cutoff", "Low-EQ cutoff must be greater than zero")
    if options.reverb_highpass_cutoff_hz <= 0.0:
        raise MixPlanRenderError("invalid_reverb_options", "Reverb high-pass cutoff must be greater than zero")
    if options.reverb_delay_seconds <= 0.0 or options.reverb_feedback < 0.0 or options.reverb_feedback >= 1.0:
        raise MixPlanRenderError("invalid_reverb_options", "Reverb delay and feedback options are invalid")
    if options.reverb_decay_reference_delay_seconds <= 0.0:
        raise MixPlanRenderError("invalid_reverb_options", "Reverb decay reference delay must be greater than zero")
    if options.reverb_return_gain <= 0.0:
        raise MixPlanRenderError("invalid_reverb_options", "Reverb return gain must be greater than zero")
    if options.echo_delay_seconds <= 0.0 or options.echo_feedback < 0.0 or options.echo_feedback >= 1.0:
        raise MixPlanRenderError("invalid_echo_options", "Echo delay and feedback options are invalid")
    if options.echo_return_gain <= 0.0:
        raise MixPlanRenderError("invalid_echo_options", "Echo return gain must be greater than zero")
    if not mix_plan_path.exists():
        raise MixPlanRenderError("mix_plan_missing", f"MixPlan file does not exist: {mix_plan_path}")

    try:
        plan = json.loads(mix_plan_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise MixPlanRenderError("invalid_mix_plan_json", f"Could not parse MixPlan JSON: {exc}") from exc

    result = render_mix_plan(plan, mix_plan_path=mix_plan_path, out_dir=out_dir, options=options)
    return result


def render_mix_plan(
    plan: dict[str, Any],
    *,
    mix_plan_path: Path,
    out_dir: Path,
    options: RenderOptions,
) -> RenderResult:
    """Render an already parsed MixPlan object."""

    out_dir.mkdir(parents=True, exist_ok=True)
    assets = _asset_map(plan)
    commands = _list_field(plan, "commands")
    placements = _list_field(plan, "tracks")
    transitions = _list_field(plan, "transitions")
    if not placements:
        raise MixPlanRenderError("empty_tracks", "MixPlan must contain at least one track placement")
    if not commands:
        raise MixPlanRenderError("empty_commands", "MixPlan must contain at least one command")

    render_duration = _render_duration_seconds(placements, transitions, commands)
    frames = max(1, math.ceil(render_duration * options.sample_rate))
    mix = array("f", [0.0]) * frames
    automation = _automation_maps(commands)
    effect_parameters = _effect_parameter_maps(commands)
    _reject_unsupported_tempo_ramps(automation)
    has_crossfader = None in automation and "crossfader" in automation[None]
    audio_cache: dict[tuple[str, str], tuple[LoadedAudio, list[float], list[float], dict[str, Any] | None]] = {}
    tempo_stretch_reports: dict[tuple[str, str], dict[str, Any]] = {}
    reverb_states: dict[int, _ReverbState] = {}
    echo_states: dict[int, _EchoState] = {}

    for placement in sorted(placements, key=lambda item: float(item.get("timelineStartSeconds", 0.0))):
        track_id = _required_string(placement, "trackId")
        deck = _required_int(placement, "deck")
        tempo_plan = _tempo_plan_from_placement(placement)
        cache_key = (track_id, _tempo_cache_key(tempo_plan))
        audio, low_band, high_band, tempo_report = audio_cache.setdefault(
            cache_key,
            _load_asset_bands(
                track_id,
                assets,
                mix_plan_path=mix_plan_path,
                out_dir=out_dir,
                tempo_plan=tempo_plan,
                options=options,
            ),
        )
        if tempo_report is not None:
            tempo_stretch_reports[cache_key] = tempo_report
        reverb = reverb_states.setdefault(deck, _ReverbState(options.sample_rate, options.reverb_delay_seconds))
        echo = echo_states.setdefault(
            deck,
            _EchoState(options.sample_rate, _echo_delay_seconds(deck, effect_parameters, options)),
        )
        _render_placement(
            mix,
            placement,
            deck=deck,
            audio=audio,
            low_band=low_band,
            high_band=high_band,
            automation=automation,
            effect_parameters=effect_parameters,
            has_crossfader=has_crossfader,
            reverb=reverb,
            echo=echo,
            tempo_ratio=_tempo_ratio_from_plan(tempo_plan),
            options=options,
        )

    output_wav = out_dir / options.output_filename
    _write_pcm16_mono_wav(output_wav, mix, options.sample_rate, output_gain=options.output_gain)
    summary = _summary_payload(
        plan,
        output_wav=output_wav,
        duration_seconds=frames / options.sample_rate,
        frames=frames,
        sample_rate=options.sample_rate,
        tempo_stretch_reports=list(tempo_stretch_reports.values()),
        audio_sources=_audio_source_reports(audio_cache),
    )
    trace = _trace_payload(plan, automation=automation, duration_seconds=frames / options.sample_rate)
    summary_path = out_dir / options.summary_filename
    trace_path = out_dir / options.trace_filename
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    trace_path.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")

    return RenderResult(
        output_wav=output_wav,
        summary_path=summary_path,
        trace_path=trace_path,
        duration_seconds=frames / options.sample_rate,
        sample_rate=options.sample_rate,
        frames=frames,
        transition_templates=tuple(summary["transitionTemplates"]),
        automation_controls=tuple(summary["automationControls"]),
    )


def _asset_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = _list_field(plan, "assets")
    result: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            raise MixPlanRenderError("invalid_asset", "MixPlan assets must be objects")
        track_id = _required_string(asset, "trackId")
        result[track_id] = asset
    return result


def _list_field(plan: dict[str, Any], field: str) -> list[Any]:
    value = plan.get(field, [])
    if not isinstance(value, list):
        raise MixPlanRenderError(f"invalid_{field}", f"MixPlan {field} must be an array")
    return value


def _required_string(value: dict[str, Any], field: str) -> str:
    field_value = value.get(field)
    if not isinstance(field_value, str) or not field_value:
        raise MixPlanRenderError(f"missing_{field}", f"Expected non-empty string field: {field}")
    return field_value


def _required_int(value: dict[str, Any], field: str) -> int:
    field_value = value.get(field)
    if not isinstance(field_value, int):
        raise MixPlanRenderError(f"missing_{field}", f"Expected integer field: {field}")
    return field_value


def _number(value: dict[str, Any], field: str, default: float | None = None) -> float:
    field_value = value.get(field, default)
    if not isinstance(field_value, int | float):
        raise MixPlanRenderError(f"missing_{field}", f"Expected numeric field: {field}")
    return float(field_value)


def _optional_number(value: dict[str, Any], field: str) -> float | None:
    field_value = value.get(field)
    if field_value is None:
        return None
    if not isinstance(field_value, int | float):
        raise MixPlanRenderError(f"invalid_{field}", f"Expected numeric field: {field}")
    return float(field_value)


def _optional_bool(value: dict[str, Any], field: str) -> bool | None:
    field_value = value.get(field)
    if field_value is None:
        return None
    if not isinstance(field_value, bool):
        raise MixPlanRenderError(f"invalid_{field}", f"Expected boolean field: {field}")
    return field_value


def _render_duration_seconds(placements: list[Any], transitions: list[Any], commands: list[Any]) -> float:
    end_seconds = 0.0
    for placement in placements:
        if not isinstance(placement, dict):
            raise MixPlanRenderError("invalid_placement", "MixPlan track placements must be objects")
        end_seconds = max(end_seconds, _number(placement, "timelineEndSeconds", _number(placement, "timelineStartSeconds")))
    for transition in transitions:
        if not isinstance(transition, dict):
            raise MixPlanRenderError("invalid_transition", "MixPlan transitions must be objects")
        end_seconds = max(end_seconds, _number(transition, "timelineEndSeconds", 0.0))
    for command in commands:
        if not isinstance(command, dict):
            raise MixPlanRenderError("invalid_command", "MixPlan commands must be objects")
        end_seconds = max(end_seconds, _number(command, "at", 0.0))
        for keyframe in command.get("keyframes", []):
            if not isinstance(keyframe, dict):
                raise MixPlanRenderError("invalid_keyframe", "Automation keyframes must be objects")
            end_seconds = max(end_seconds, _number(keyframe, "at", 0.0))
    return end_seconds


def _load_asset_bands(
    track_id: str,
    assets: dict[str, dict[str, Any]],
    *,
    mix_plan_path: Path,
    out_dir: Path,
    tempo_plan: dict[str, Any] | None,
    options: RenderOptions,
) -> tuple[LoadedAudio, list[float], list[float], dict[str, Any] | None]:
    asset = assets.get(track_id)
    if asset is None:
        raise MixPlanRenderError("missing_asset", f"MixPlan has no asset entry for trackId: {track_id}")
    source_uri = _required_string(asset, "sourceUri")
    source_path = _resolve_source_path(source_uri, mix_plan_path=mix_plan_path, asset_root=options.asset_root)
    source_path, tempo_report = _tempo_stretched_source_path(
        track_id,
        source_path,
        out_dir=out_dir,
        tempo_plan=tempo_plan,
        options=options,
    )
    audio = _load_audio(source_path, sample_rate=options.sample_rate)
    low_band, high_band = _split_low_high(audio.samples, sample_rate=audio.sample_rate, cutoff_hz=options.low_cutoff_hz)
    return audio, low_band, high_band, tempo_report


def _tempo_stretched_source_path(
    track_id: str,
    source_path: Path,
    *,
    out_dir: Path,
    tempo_plan: dict[str, Any] | None,
    options: RenderOptions,
) -> tuple[Path, dict[str, Any] | None]:
    if not tempo_plan:
        return source_path, None
    source_bpm = _optional_number(tempo_plan, "sourceBpm")
    target_bpm = _optional_number(tempo_plan, "targetBpm")
    ratio = _tempo_ratio_from_plan(tempo_plan)
    if source_bpm is None or target_bpm is None or ratio is None:
        return source_path, None
    if math.isclose(ratio, 1.0, rel_tol=0.0, abs_tol=0.000001):
        return source_path, None
    preserve_pitch = _optional_bool(tempo_plan, "preservePitch")
    if preserve_pitch is False:
        raise MixPlanRenderError(
            "preserve_pitch_required",
            "Tempo-stretched MixPlan rendering requires tempoPlan.preservePitch=true",
        )
    backend = str(tempo_plan.get("backend") or options.tempo_backend)
    quality = str(tempo_plan.get("quality") or options.tempo_quality)
    target_bpm_bias = float(tempo_plan.get("targetBpmBias", 0.0) or 0.0)
    safe_track_id = _safe_filename(track_id)
    stem = f"{safe_track_id}-{source_bpm:g}-to-{target_bpm:g}-{backend}"
    stretch_dir = out_dir / "tempo-stretched-assets"
    stretch_dir.mkdir(parents=True, exist_ok=True)
    output_wav = stretch_dir / f"{stem}.wav"
    report_path = stretch_dir / f"{stem}.tempo-stretch-report.json"
    try:
        result = stretch_audio_file(
            source_path,
            output_wav,
            report_path=report_path,
            options=TempoStretchOptions(
                source_bpm=source_bpm,
                target_bpm=target_bpm,
                backend=backend,
                sample_rate=options.sample_rate,
                quality=quality,
                preserve_pitch=True,
                target_bpm_bias=target_bpm_bias,
                ffmpeg_path=options.ffmpeg_path,
            ),
        )
    except TempoStretchError as exc:
        raise MixPlanRenderError(exc.code, exc.message) from exc
    report = result.to_dict()
    report["trackId"] = track_id
    report["requiresRenderedBpmValidation"] = bool(tempo_plan.get("requiresRenderedBpmValidation", True))
    report["validationStatus"] = str(tempo_plan.get("validationStatus", "pending"))
    return output_wav, report


def _safe_filename(value: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in value)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "track"


def _tempo_plan_from_placement(placement: dict[str, Any]) -> dict[str, Any] | None:
    tempo_plan = placement.get("tempoPlan")
    if tempo_plan is None:
        return None
    if not isinstance(tempo_plan, dict):
        raise MixPlanRenderError("invalid_tempo_plan", "tempoPlan must be an object")
    return tempo_plan


def _tempo_ratio_from_plan(tempo_plan: dict[str, Any] | None) -> float | None:
    if not tempo_plan:
        return None
    ratio = _optional_number(tempo_plan, "tempoRatio")
    if ratio is not None:
        if ratio <= 0.0:
            raise MixPlanRenderError("invalid_tempo_ratio", "tempoPlan.tempoRatio must be greater than zero")
        return ratio
    source_bpm = _optional_number(tempo_plan, "sourceBpm")
    target_bpm = _optional_number(tempo_plan, "targetBpm")
    if source_bpm is None or target_bpm is None:
        return None
    if source_bpm <= 0.0 or target_bpm <= 0.0:
        raise MixPlanRenderError("invalid_tempo_plan", "tempoPlan sourceBpm and targetBpm must be greater than zero")
    return target_bpm / source_bpm


def _tempo_cache_key(tempo_plan: dict[str, Any] | None) -> str:
    if not tempo_plan:
        return "native"
    source_bpm = _optional_number(tempo_plan, "sourceBpm")
    target_bpm = _optional_number(tempo_plan, "targetBpm")
    ratio = _tempo_ratio_from_plan(tempo_plan)
    backend = str(tempo_plan.get("backend", ""))
    quality = str(tempo_plan.get("quality", ""))
    bias = float(tempo_plan.get("targetBpmBias", 0.0) or 0.0)
    return f"{source_bpm}:{target_bpm}:{ratio}:{backend}:{quality}:{bias}"


def _reject_unsupported_tempo_ramps(
    automation: dict[int | None, dict[str, list[dict[str, Any]]]]
) -> None:
    for deck, controls in automation.items():
        tempo_keyframes = controls.get("tempo")
        if not tempo_keyframes or len(tempo_keyframes) <= 1:
            continue
        values = [float(keyframe.get("value", 1.0)) for keyframe in tempo_keyframes]
        if any(not math.isclose(value, values[0], rel_tol=0.0, abs_tol=0.000001) for value in values[1:]):
            deck_label = "global" if deck is None else f"deck {deck}"
            raise MixPlanRenderError(
                "tempo_ramp_unsupported",
                f"Offline renderer supports constant tempo stretch only for now; tempo ramp found on {deck_label}",
            )


def _resolve_source_path(source_uri: str, *, mix_plan_path: Path, asset_root: Path | None) -> Path:
    if source_uri.startswith("file://"):
        parsed = urlparse(source_uri)
        if parsed.netloc and parsed.netloc not in {"localhost", ""}:
            raw_path = f"//{parsed.netloc}{parsed.path}"
        else:
            raw_path = parsed.path
        return _platform_path(unquote(raw_path))

    candidate = _platform_path(source_uri)
    if candidate.is_absolute():
        return candidate
    if asset_root is not None:
        asset_root_candidate = asset_root / candidate
        if asset_root_candidate.exists():
            return asset_root_candidate
    cwd_candidate = Path.cwd() / candidate
    if cwd_candidate.exists():
        return cwd_candidate
    return mix_plan_path.parent / candidate


def _platform_path(path_text: str) -> Path:
    normalized = path_text.replace("\\", "/")
    if len(normalized) >= 3 and normalized[0] == "/" and normalized[2] == ":" and normalized[1].isalpha():
        return Path(f"/mnt/{normalized[1].lower()}{normalized[3:]}")
    if len(normalized) >= 2 and normalized[1] == ":" and normalized[0].isalpha():
        return Path(f"/mnt/{normalized[0].lower()}/{normalized[2:].lstrip('/')}")
    return Path(path_text)


def _load_audio(path: Path, *, sample_rate: int) -> LoadedAudio:
    if not path.exists():
        raise MixPlanRenderError("audio_source_missing", f"Audio source does not exist: {path}")
    if path.suffix.lower() == ".wav":
        return _load_wav(path, sample_rate=sample_rate)
    try:
        decoded = load_audio(path, target_sample_rate=sample_rate)
    except AudioLoadError as exc:
        raise MixPlanRenderError(exc.code, exc.message) from exc
    samples = array("f", (float(sample) for sample in decoded.samples))
    return LoadedAudio(samples=samples, sample_rate=sample_rate, source_path=path)


def _load_wav(path: Path, *, sample_rate: int) -> LoadedAudio:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        source_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        compression = wav_file.getcomptype()
        frame_count = wav_file.getnframes()
        frames = wav_file.readframes(frame_count)

    if compression != "NONE":
        raise MixPlanRenderError("audio_unsupported_format", f"Compressed WAV is not supported: {path}")
    if channels <= 0:
        raise MixPlanRenderError("audio_unsupported_format", f"WAV has no channels: {path}")
    if sample_width not in {1, 2, 3, 4}:
        raise MixPlanRenderError("audio_unsupported_format", f"Unsupported WAV sample width: {sample_width}")

    samples = _decode_pcm_frames(frames, channels=channels, sample_width=sample_width)
    if source_rate != sample_rate:
        samples = _resample_linear(samples, source_rate=source_rate, target_rate=sample_rate)
    return LoadedAudio(samples=samples, sample_rate=sample_rate, source_path=path)


def _decode_pcm_frames(frames: bytes, *, channels: int, sample_width: int) -> array:
    stride = channels * sample_width
    if stride <= 0:
        return array("f")
    samples = array("f")
    for offset in range(0, len(frames) - stride + 1, stride):
        channel_sum = 0.0
        for channel in range(channels):
            start = offset + channel * sample_width
            raw = frames[start : start + sample_width]
            if sample_width == 1:
                value = (raw[0] - 128) / 128.0
            elif sample_width == 2:
                value = int.from_bytes(raw, byteorder="little", signed=True) / 32768.0
            elif sample_width == 3:
                sign_byte = b"\xff" if raw[2] & 0x80 else b"\x00"
                value = int.from_bytes(raw + sign_byte, byteorder="little", signed=True) / 8388608.0
            else:
                value = int.from_bytes(raw, byteorder="little", signed=True) / 2147483648.0
            channel_sum += value
        samples.append(channel_sum / channels)
    return samples


def _resample_linear(samples: Sequence[float], *, source_rate: int, target_rate: int) -> array:
    if not samples or source_rate == target_rate:
        return array("f", samples)
    target_count = max(1, round(len(samples) * target_rate / source_rate))
    scale = source_rate / target_rate
    result = array("f")
    last_index = len(samples) - 1
    for target_index in range(target_count):
        source_position = target_index * scale
        left = min(last_index, int(math.floor(source_position)))
        right = min(last_index, left + 1)
        fraction = source_position - left
        result.append(samples[left] * (1.0 - fraction) + samples[right] * fraction)
    return result


def _split_low_high(samples: Sequence[float], *, sample_rate: int, cutoff_hz: float) -> tuple[array, array]:
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    dt = 1.0 / sample_rate
    alpha = dt / (rc + dt)
    low_band = array("f")
    high_band = array("f")
    previous_low = 0.0
    for sample in samples:
        previous_low += alpha * (sample - previous_low)
        low_band.append(previous_low)
        high_band.append(sample - previous_low)
    return low_band, high_band


def _automation_maps(commands: list[Any]) -> dict[int | None, dict[str, list[dict[str, Any]]]]:
    maps: dict[int | None, dict[str, list[dict[str, Any]]]] = {}
    for command in commands:
        if not isinstance(command, dict) or command.get("type") != "automate":
            continue
        control = command.get("control")
        if not isinstance(control, str):
            continue
        deck = command.get("deck")
        if deck is not None and not isinstance(deck, int):
            continue
        keyframes = command.get("keyframes", [])
        if not isinstance(keyframes, list):
            continue
        maps.setdefault(deck, {}).setdefault(control, []).extend(k for k in keyframes if isinstance(k, dict))

    for controls in maps.values():
        for keyframes in controls.values():
            keyframes.sort(key=lambda item: float(item.get("at", 0.0)))
    return maps


def _effect_parameter_maps(commands: list[Any]) -> dict[int | None, dict[str, dict[str, Any]]]:
    maps: dict[int | None, dict[str, dict[str, Any]]] = {}
    for command in commands:
        if not isinstance(command, dict) or command.get("type") != "automate":
            continue
        control = command.get("control")
        if not isinstance(control, str):
            continue
        deck = command.get("deck")
        if deck is not None and not isinstance(deck, int):
            continue
        parameters = command.get("effectParameters", {})
        if not isinstance(parameters, dict):
            continue
        maps.setdefault(deck, {}).setdefault(control, {}).update(parameters)
    return maps


class _ReverbState:
    def __init__(self, sample_rate: int, delay_seconds: float) -> None:
        # Smooth send-style wash network. Keep it darker and quieter than the
        # dry deck; short bright combs read as a metallic swish on dubstep drops.
        self.sample_rate = sample_rate
        scale = sample_rate / DEFAULT_RENDER_SAMPLE_RATE
        room_scale = max(1.05, min(1.85, delay_seconds / 0.11))
        comb_samples_44k = (1557, 1617, 1711, 1801, 1907, 2029, 2161, 2293, 2417, 2549, 2677, 2803)
        allpass_samples_44k = (671, 557, 463, 379, 293)
        self.comb_buffers = [
            [0.0] * max(1, round(samples * scale * room_scale))
            for samples in comb_samples_44k
        ]
        self.comb_indices = [0 for _ in self.comb_buffers]
        self.comb_filters = [0.0 for _ in self.comb_buffers]
        self.allpass_buffers = [
            [0.0] * max(1, round(samples * scale * room_scale))
            for samples in allpass_samples_44k
        ]
        self.allpass_indices = [0 for _ in self.allpass_buffers]
        self.highpass_low = 0.0
        self.tone_lowpass = 0.0

    def process(self, value: float, *, feedback: float) -> float:
        damping = 0.62
        combined = 0.0
        for index, buffer in enumerate(self.comb_buffers):
            read_index = self.comb_indices[index]
            delayed = buffer[read_index]
            self.comb_filters[index] = delayed * (1.0 - damping) + self.comb_filters[index] * damping
            buffer[read_index] = value + self.comb_filters[index] * feedback
            self.comb_indices[index] = (read_index + 1) % len(buffer)
            combined += delayed

        if self.comb_buffers:
            combined *= 0.42 / len(self.comb_buffers)

        allpass_value = combined
        for index, buffer in enumerate(self.allpass_buffers):
            read_index = self.allpass_indices[index]
            delayed = buffer[read_index]
            output = delayed - allpass_value
            buffer[read_index] = allpass_value + delayed * 0.38
            self.allpass_indices[index] = (read_index + 1) % len(buffer)
            allpass_value = output

        return self.lowpass(allpass_value, sample_rate=self.sample_rate, cutoff_hz=5200.0)

    def highpass(self, value: float, *, sample_rate: int, cutoff_hz: float) -> float:
        rc = 1.0 / (2.0 * math.pi * cutoff_hz)
        dt = 1.0 / sample_rate
        alpha = dt / (rc + dt)
        self.highpass_low += alpha * (value - self.highpass_low)
        return value - self.highpass_low

    def lowpass(self, value: float, *, sample_rate: int, cutoff_hz: float) -> float:
        rc = 1.0 / (2.0 * math.pi * cutoff_hz)
        dt = 1.0 / sample_rate
        alpha = dt / (rc + dt)
        self.tone_lowpass += alpha * (value - self.tone_lowpass)
        return self.tone_lowpass


class _EchoState:
    def __init__(self, sample_rate: int, delay_seconds: float) -> None:
        self.buffer = [0.0] * max(1, round(sample_rate * delay_seconds))
        self.index = 0

    def process(self, value: float, *, feedback: float) -> float:
        delayed = self.buffer[self.index]
        self.buffer[self.index] = value + delayed * feedback
        self.index = (self.index + 1) % len(self.buffer)
        return delayed


class _ControlCursor:
    def __init__(self, keyframes: list[dict[str, Any]] | None, default: float) -> None:
        self.keyframes = keyframes or []
        self.default = default
        self.index = 0

    def value(self, time_seconds: float) -> float:
        keyframes = self.keyframes
        if not keyframes:
            return self.default
        first_at = float(keyframes[0].get("at", 0.0))
        if time_seconds < first_at:
            return self.default
        if len(keyframes) == 1:
            return float(keyframes[0].get("value", self.default))

        while self.index < len(keyframes) - 1 and time_seconds > float(keyframes[self.index + 1].get("at", 0.0)):
            self.index += 1

        if self.index >= len(keyframes) - 1:
            return float(keyframes[-1].get("value", self.default))

        previous = keyframes[self.index]
        next_keyframe = keyframes[self.index + 1]
        previous_at = float(previous.get("at", 0.0))
        keyframe_at = float(next_keyframe.get("at", 0.0))
        previous_value = float(previous.get("value", self.default))
        next_value = float(next_keyframe.get("value", previous_value))
        if keyframe_at <= previous_at:
            return next_value
        progress = (time_seconds - previous_at) / (keyframe_at - previous_at)
        interpolation = str(next_keyframe.get("interpolation", "linear"))
        if interpolation == "hold":
            return previous_value
        if interpolation == "smoothstep":
            progress = progress * progress * (3.0 - 2.0 * progress)
        elif interpolation == "exponential":
            progress = progress * progress
        return previous_value * (1.0 - progress) + next_value * progress


def _render_placement(
    mix: list[float],
    placement: dict[str, Any],
    *,
    deck: int,
    audio: LoadedAudio,
    low_band: list[float],
    high_band: list[float],
    automation: dict[int | None, dict[str, list[dict[str, Any]]]],
    effect_parameters: dict[int | None, dict[str, dict[str, Any]]],
    has_crossfader: bool,
    reverb: _ReverbState,
    echo: _EchoState,
    tempo_ratio: float | None,
    options: RenderOptions,
) -> None:
    timeline_start = _number(placement, "timelineStartSeconds")
    timeline_end = _optional_number(placement, "timelineEndSeconds")
    source_time_scale = tempo_ratio if tempo_ratio is not None else 1.0
    source_start = source_seconds_to_stretched_seconds(
        _number(placement, "sourceStartSeconds"),
        tempo_ratio=source_time_scale,
    )
    source_end = _optional_number(placement, "sourceEndSeconds")
    if source_end is not None:
        source_end = source_seconds_to_stretched_seconds(source_end, tempo_ratio=source_time_scale)
    if timeline_end is None:
        timeline_end = timeline_start + max(0.0, len(audio.samples) / audio.sample_rate - source_start)
    start_frame = max(0, math.floor(timeline_start * options.sample_rate))
    end_frame = min(len(mix), math.ceil(timeline_end * options.sample_rate))

    deck_controls = automation.get(deck, {})
    global_controls = automation.get(None, {})
    volume_cursor = _ControlCursor(deck_controls.get("volume"), 1.0)
    eq_low_cursor = _ControlCursor(deck_controls.get("eqLow"), 1.0)
    eq_high_cursor = _ControlCursor(deck_controls.get("eqHigh"), 1.0)
    reverb_wet_cursor = _ControlCursor(deck_controls.get("reverbWet"), 0.0)
    tail_gain_cursor = _ControlCursor(deck_controls.get("reverbTailGain"), 0.0)
    echo_wet_cursor = _ControlCursor(deck_controls.get("echoWet"), 0.0)
    crossfader_cursor = _ControlCursor(global_controls.get("crossfader"), 0.0)
    for frame in range(start_frame, end_frame):
        timeline_seconds = frame / options.sample_rate
        source_seconds = source_start + (timeline_seconds - timeline_start)
        source_index = round(source_seconds * audio.sample_rate)
        source_available = 0 <= source_index < len(audio.samples)
        if source_end is not None and source_seconds >= source_end:
            source_available = False

        low = low_band[source_index] if source_available else 0.0
        high = high_band[source_index] if source_available else 0.0
        volume = volume_cursor.value(timeline_seconds)
        eq_low = eq_low_cursor.value(timeline_seconds)
        eq_high = eq_high_cursor.value(timeline_seconds)
        reverb_wet = reverb_wet_cursor.value(timeline_seconds)
        tail_gain = tail_gain_cursor.value(timeline_seconds)
        echo_wet = echo_wet_cursor.value(timeline_seconds)
        cross_gain = _crossfader_gain(
            deck,
            crossfader_cursor.value(timeline_seconds),
            enabled=has_crossfader,
        )

        eq_signal = high * eq_high + low * eq_low
        dry = eq_signal * volume * cross_gain
        wet_component = 0.0
        if reverb_wet > 0.000001 or tail_gain > 0.000001:
            reverb_band = reverb.highpass(
                high,
                sample_rate=options.sample_rate,
                cutoff_hz=options.reverb_highpass_cutoff_hz,
            )
            reverb_input = reverb_band * reverb_wet * volume * cross_gain
            wet_return = reverb.process(
                reverb_input,
                feedback=_reverb_feedback(deck, effect_parameters, options),
            )
            wet_gain = max(reverb_wet * cross_gain, tail_gain)
            wet_component = wet_return * wet_gain * options.reverb_return_gain

        echo_component = 0.0
        if echo_wet > 0.000001:
            echo_return = echo.process(
                high * volume * echo_wet * cross_gain,
                feedback=_echo_feedback(deck, effect_parameters, options),
            )
            echo_gain = max(echo_wet * volume * cross_gain, echo_wet)
            echo_component = echo_return * echo_gain * _echo_return_gain(deck, effect_parameters, options)
        mix[frame] += (
            dry
            + wet_component
            + echo_component
        )


def _reverb_feedback(
    deck: int,
    effect_parameters: dict[int | None, dict[str, dict[str, Any]]],
    options: RenderOptions,
) -> float:
    deck_parameters = effect_parameters.get(deck, {})
    decay_seconds = None
    for control in ("reverbTailGain", "reverbWet"):
        raw_value = deck_parameters.get(control, {}).get("reverbDecaySeconds")
        if isinstance(raw_value, int | float):
            decay_seconds = float(raw_value)
            break
        if isinstance(raw_value, str):
            try:
                decay_seconds = float(raw_value)
                break
            except ValueError:
                continue
    if decay_seconds is None or decay_seconds <= 0.0:
        return options.reverb_feedback

    feedback = math.exp(math.log(0.01) * options.reverb_decay_reference_delay_seconds / decay_seconds)
    return max(0.0, min(0.992, feedback))


def _echo_delay_seconds(
    deck: int,
    effect_parameters: dict[int | None, dict[str, dict[str, Any]]],
    options: RenderOptions,
) -> float:
    value = _effect_parameter_float(deck, effect_parameters, "echoWet", ("delaySeconds", "echoDelaySeconds"))
    if value is None or value <= 0.0:
        return options.echo_delay_seconds
    return value


def _echo_feedback(
    deck: int,
    effect_parameters: dict[int | None, dict[str, dict[str, Any]]],
    options: RenderOptions,
) -> float:
    value = _effect_parameter_float(deck, effect_parameters, "echoWet", ("feedback", "echoFeedback"))
    if value is None:
        return options.echo_feedback
    return max(0.0, min(0.985, value))


def _echo_return_gain(
    deck: int,
    effect_parameters: dict[int | None, dict[str, dict[str, Any]]],
    options: RenderOptions,
) -> float:
    value = _effect_parameter_float(deck, effect_parameters, "echoWet", ("returnGain", "echoReturnGain"))
    if value is None or value <= 0.0:
        return options.echo_return_gain
    return value


def _effect_parameter_float(
    deck: int,
    effect_parameters: dict[int | None, dict[str, dict[str, Any]]],
    control: str,
    names: tuple[str, ...],
) -> float | None:
    parameters = effect_parameters.get(deck, {}).get(control, {})
    for name in names:
        raw_value = parameters.get(name)
        if isinstance(raw_value, int | float):
            return float(raw_value)
        if isinstance(raw_value, str):
            try:
                return float(raw_value)
            except ValueError:
                continue
    return None


def _control_value(
    controls: dict[str, list[dict[str, Any]]],
    control: str,
    time_seconds: float,
    *,
    default: float,
) -> float:
    keyframes = controls.get(control)
    if not keyframes:
        return default
    first_at = float(keyframes[0].get("at", 0.0))
    if time_seconds < first_at:
        return default
    if len(keyframes) == 1:
        return float(keyframes[0].get("value", default))

    previous = keyframes[0]
    for keyframe in keyframes[1:]:
        keyframe_at = float(keyframe.get("at", 0.0))
        if time_seconds <= keyframe_at:
            previous_at = float(previous.get("at", 0.0))
            previous_value = float(previous.get("value", default))
            next_value = float(keyframe.get("value", previous_value))
            if keyframe_at <= previous_at:
                return next_value
            progress = (time_seconds - previous_at) / (keyframe_at - previous_at)
            interpolation = str(keyframe.get("interpolation", "linear"))
            if interpolation == "hold":
                return previous_value
            if interpolation == "smoothstep":
                progress = progress * progress * (3.0 - 2.0 * progress)
            elif interpolation == "exponential":
                progress = progress * progress
            return previous_value * (1.0 - progress) + next_value * progress
        previous = keyframe
    return float(keyframes[-1].get("value", default))


def _crossfader_gain(deck: int, value: float, *, enabled: bool) -> float:
    if not enabled:
        return 1.0
    if deck == 1:
        return max(0.0, min(1.0, (1.0 - value) / 2.0))
    if deck == 2:
        return max(0.0, min(1.0, (1.0 + value) / 2.0))
    return 1.0


def _write_pcm16_mono_wav(path: Path, samples: list[float], sample_rate: int, *, output_gain: float) -> None:
    frames = bytearray()
    for sample in samples:
        value = _soft_limit(sample * output_gain)
        frames.extend(round(value * 32767).to_bytes(2, byteorder="little", signed=True))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def _soft_limit(value: float) -> float:
    """Preserve normal level and only tame overs instead of scaling the whole render."""
    threshold = 0.96
    magnitude = abs(value)
    if magnitude <= threshold:
        return value
    limited = threshold + (1.0 - threshold) * math.tanh((magnitude - threshold) / (1.0 - threshold))
    return math.copysign(min(1.0, limited), value)


def _summary_payload(
    plan: dict[str, Any],
    *,
    output_wav: Path,
    duration_seconds: float,
    frames: int,
    sample_rate: int,
    tempo_stretch_reports: list[dict[str, Any]],
    audio_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    transitions = _list_field(plan, "transitions")
    commands = _list_field(plan, "commands")
    controls = sorted(
        {
            str(command["control"])
            for command in commands
            if isinstance(command, dict) and command.get("type") == "automate" and isinstance(command.get("control"), str)
        }
    )
    return {
        "ok": True,
        "artifact": "mixplan-audition-render",
        "outputWav": str(output_wav),
        "durationSeconds": duration_seconds,
        "sampleRate": sample_rate,
        "frames": frames,
        "transitionTemplates": [
            str(transition.get("templateId", ""))
            for transition in transitions
            if isinstance(transition, dict) and transition.get("templateId")
        ],
        "tempoStretchReports": tempo_stretch_reports,
        "audioSources": audio_sources,
        "automationControls": controls,
        "tracks": [
            {
                "placementId": placement.get("placementId"),
                "trackId": placement.get("trackId"),
                "deck": placement.get("deck"),
                "timelineStartSeconds": placement.get("timelineStartSeconds"),
                "timelineEndSeconds": placement.get("timelineEndSeconds"),
            }
            for placement in _list_field(plan, "tracks")
            if isinstance(placement, dict)
        ],
    }


def _audio_source_reports(
    audio_cache: dict[tuple[str, str], tuple[LoadedAudio, list[float], list[float], dict[str, Any] | None]]
) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for (track_id, tempo_key), (audio, _low_band, _high_band, tempo_report) in sorted(audio_cache.items()):
        reports.append(
            {
                "trackId": track_id,
                "tempoCacheKey": tempo_key,
                "sourcePath": str(audio.source_path),
                "timelinePolicy": _timeline_policy_for_audio_path(audio.source_path),
                "tempoStretched": tempo_report is not None,
            }
        )
    return reports


def _timeline_policy_for_audio_path(path: Path) -> str:
    if path.name == CANONICAL_AUDIO_FILENAME and (path.parent / CANONICAL_AUDIO_METADATA_FILENAME).exists():
        return CANONICAL_TIMELINE_POLICY
    return "direct-audio-path"


def _trace_payload(
    plan: dict[str, Any],
    *,
    automation: dict[int | None, dict[str, list[dict[str, Any]]]],
    duration_seconds: float,
) -> dict[str, Any]:
    command_trace = [
        {
            "at": command.get("at"),
            "type": command.get("type"),
            "deck": command.get("deck"),
            "trackId": command.get("trackId"),
            "control": command.get("control"),
        }
        for command in _list_field(plan, "commands")
        if isinstance(command, dict)
    ]
    automation_trace = []
    for deck, controls in sorted(automation.items(), key=lambda item: -1 if item[0] is None else item[0]):
        for control, keyframes in sorted(controls.items()):
            automation_trace.append(
                {
                    "deck": deck,
                    "control": control,
                    "keyframes": keyframes,
                }
            )
    return {
        "durationSeconds": duration_seconds,
        "commands": command_trace,
        "automation": automation_trace,
    }
