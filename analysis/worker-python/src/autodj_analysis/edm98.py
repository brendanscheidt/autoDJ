"""EDM-98 / EDMFormer section prediction adapter.

The EDMFormer stack is intentionally optional and heavy. Keep all imports lazy
so the normal analyzer and tests still import without the model dependencies or
external checkpoints installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Sequence

from .cache import SCHEMA_VERSION, write_json_atomic


EDM98_ARTIFACT_TYPE = "edm98-section-prediction"
EDM98_ADAPTER_VERSION = "edm98-adapter-v1"
DEFAULT_EDM98_DEVICE = "auto"


class Edm98Error(ValueError):
    """Expected EDM-98 adapter failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class Edm98Options:
    checkpoint: str | None = None
    config: str | None = None
    musicfm_stat: str | None = None
    musicfm_model: str | None = None
    device: str = DEFAULT_EDM98_DEVICE
    low_memory: bool = True
    hf_cache_dir: str | None = None
    offline: bool = False
    no_cache: bool = False


class Edm98Predictor:
    """Loaded EDMFormer pipeline reused across one or more predictions."""

    def __init__(self, options: Edm98Options | None = None) -> None:
        self.options = options or Edm98Options()
        self._pipeline = self._create_pipeline(self.options)

    def predict(self, audio_path: str | Path) -> dict[str, Any]:
        audio_path = Path(audio_path)
        if not audio_path.is_file():
            raise Edm98Error("audio_not_found", f"Audio file does not exist: {audio_path}")

        segments = self._pipeline.predict_file(audio_path)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "artifact": EDM98_ARTIFACT_TYPE,
            "createdAtUtc": _utc_now_iso(),
            "producer": {
                "name": "edm98-edmformer",
                "adapterVersion": EDM98_ADAPTER_VERSION,
            },
            "audioPath": str(audio_path),
            "parameters": _options_payload(self.options),
            "segments": [_segment_payload(segment) for segment in segments],
        }

    @staticmethod
    def _create_pipeline(options: Edm98Options):
        try:
            from edm98.inference import create_pipeline  # type: ignore
        except ImportError as exc:
            raise Edm98Error(
                "edm98_dependencies_missing",
                "EDM-98/EDMFormer dependencies are not installed. Install the EDM-98 inference stack first.",
            ) from exc

        kwargs: dict[str, Any] = {
            "device": options.device,
            "low_memory": options.low_memory,
            "offline": options.offline,
            "no_cache": options.no_cache,
        }
        if options.checkpoint:
            kwargs["checkpoint_path"] = options.checkpoint
        if options.config:
            kwargs["config_path"] = options.config
        if options.musicfm_stat:
            kwargs["musicfm_stat_path"] = options.musicfm_stat
        if options.musicfm_model:
            kwargs["musicfm_model_path"] = options.musicfm_model
        if options.hf_cache_dir:
            kwargs["hf_cache_dir"] = options.hf_cache_dir
        try:
            return create_pipeline(**kwargs)
        except FileNotFoundError as exc:
            raise Edm98Error("edm98_asset_missing", str(exc)) from exc
        except RuntimeError as exc:
            raise Edm98Error("edm98_runtime_error", str(exc)) from exc


def predict_edm98_file(
    audio_path: str | Path,
    output_path: str | Path,
    *,
    options: Edm98Options | None = None,
) -> Path:
    predictor = Edm98Predictor(options)
    artifact = predictor.predict(audio_path)
    return write_json_atomic(Path(output_path), artifact)


def edm98_segments_to_drop_candidates(
    segments: Sequence[dict[str, Any]],
    *,
    include_buildup_ends: bool = True,
    collapse_contiguous_drop_segments: bool = True,
) -> list[dict[str, Any]]:
    """Convert EDMFormer section segments into drop-start candidates.

    EDMFormer's strongest signal for us is a predicted `drop` segment start.
    If a `buildup` segment directly precedes another label, the buildup end is
    also useful as a weaker fallback because drop transitions often occur at
    that boundary even when the following section label is noisy.
    """

    raw_candidates: list[dict[str, Any]] = []
    previous_label = ""
    previous_end: float | None = None
    for index, segment in enumerate(segments):
        label = str(segment.get("label") or "").lower()
        start = _coerce_float(segment.get("start"))
        end = _coerce_float(segment.get("end"))
        if start is None:
            previous_label = label
            previous_end = end
            continue
        if label == "drop":
            contiguous_previous_drop = (
                collapse_contiguous_drop_segments
                and previous_label == "drop"
                and previous_end is not None
                and abs(start - previous_end) <= 1.0
            )
            if not contiguous_previous_drop:
                raw_candidates.append(
                    {
                        "timeSeconds": _round_float(start),
                        "score": 1.0,
                        "sourceLabel": label,
                        "sourceSegmentIndex": index,
                        "reason": "edmformer_drop_start",
                    }
                )
        if include_buildup_ends and label == "buildup" and end is not None:
            raw_candidates.append(
                {
                    "timeSeconds": _round_float(end),
                    "score": 0.72,
                    "sourceLabel": label,
                    "sourceSegmentIndex": index,
                    "reason": "edmformer_buildup_end",
                }
            )
        previous_label = label
        previous_end = end

    candidates = []
    seen: set[float] = set()
    for candidate in sorted(raw_candidates, key=lambda item: (-float(item["score"]), float(item["timeSeconds"]))):
        key = round(float(candidate["timeSeconds"]), 3)
        if key in seen:
            continue
        seen.add(key)
        output = dict(candidate)
        output["rank"] = len(candidates) + 1
        candidates.append(output)
    return candidates


def _segment_payload(segment: Any) -> dict[str, Any]:
    if not isinstance(segment, dict):
        raise Edm98Error("edm98_invalid_segment", "EDM-98 segment must be an object")
    return {
        "label": str(segment.get("label") or "unknown"),
        "start": _round_float(float(segment.get("start", 0.0))),
        "end": _round_float(float(segment.get("end", 0.0))),
    }


def _options_payload(options: Edm98Options) -> dict[str, Any]:
    return {
        "checkpoint": options.checkpoint,
        "config": options.config,
        "musicfmStat": options.musicfm_stat,
        "musicfmModel": options.musicfm_model,
        "device": options.device,
        "lowMemory": options.low_memory,
        "hfCacheDir": options.hf_cache_dir,
        "offline": options.offline,
        "noCache": options.no_cache,
    }


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _round_float(value: float) -> float:
    return round(float(value), 6)
