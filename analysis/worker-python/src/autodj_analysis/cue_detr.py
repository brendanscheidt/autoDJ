"""CUE-DETR cue-point prediction adapter.

This module intentionally keeps the heavy ML imports lazy. The normal analysis
worker can still import the package without torch/transformers installed, while
the CUE-DETR commands fail clearly when their optional dependency set is absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
import warnings

from .cache import SCHEMA_VERSION, write_json_atomic


CUE_DETR_ARTIFACT_TYPE = "cue-detr-cue-candidates"
CUE_DETR_ADAPTER_VERSION = "cue-detr-adapter-v1"
DEFAULT_CUE_DETR_CHECKPOINT = "disco-eth/cue-detr"
DEFAULT_CUE_DETR_SAMPLE_RATE = 22_050
DEFAULT_CUE_DETR_SENSITIVITY = 0.70
DEFAULT_CUE_DETR_MIN_DISTANCE_SECONDS = 2.0
DEFAULT_CUE_DETR_MAX_CANDIDATES = 96
DEFAULT_CUE_DETR_BATCH_SIZE = 16

_OVERLAP = 0.75
_WINDOW_WIDTH = 355
_PADDING = 266
_MEL_ROWS = 128
_HOP_LENGTH = 512


class CueDetrError(ValueError):
    """Expected CUE-DETR adapter failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class CueDetrOptions:
    checkpoint: str = DEFAULT_CUE_DETR_CHECKPOINT
    sensitivity: float = DEFAULT_CUE_DETR_SENSITIVITY
    min_distance_seconds: float = DEFAULT_CUE_DETR_MIN_DISTANCE_SECONDS
    max_candidates: int = DEFAULT_CUE_DETR_MAX_CANDIDATES
    batch_size: int = DEFAULT_CUE_DETR_BATCH_SIZE
    sample_rate: int = DEFAULT_CUE_DETR_SAMPLE_RATE
    device: str | None = None


class CueDetrPredictor:
    """Loaded CUE-DETR model reused across one or more predictions."""

    def __init__(self, options: CueDetrOptions | None = None) -> None:
        self.options = options or CueDetrOptions()
        _validate_options(self.options)
        self._deps = _load_dependencies()
        torch = self._deps["torch"]
        DetrImageProcessor = self._deps["DetrImageProcessor"]
        DetrForObjectDetection = self._deps["DetrForObjectDetection"]

        self.device = self.options.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.image_processor = DetrImageProcessor.from_pretrained("facebook/detr-resnet-50")
        with warnings.catch_warnings():
            # Current torch/transformers combinations can emit hundreds of
            # no-op meta-parameter warnings for this checkpoint. The smoke test
            # shows the model still predicts useful cues, so suppress the noise
            # to preserve JSON-friendly CLI output.
            warnings.filterwarnings("ignore", message=".*copying from a non-meta parameter.*")
            self.model = DetrForObjectDetection.from_pretrained(
                self.options.checkpoint,
                low_cpu_mem_usage=False,
            )
        self.model.to(self.device)
        self.model.eval()

    def predict(self, audio_path: str | Path) -> dict[str, Any]:
        audio_path = Path(audio_path)
        if not audio_path.is_file():
            raise CueDetrError("audio_not_found", f"Audio file does not exist: {audio_path}")

        np = self._deps["np"]
        librosa = self._deps["librosa"]
        Image = self._deps["Image"]
        cm = self._deps["cm"]
        torch = self._deps["torch"]

        y, _ = librosa.load(str(audio_path), sr=self.options.sample_rate, mono=True)
        duration_seconds = float(len(y) / self.options.sample_rate) if self.options.sample_rate else 0.0
        if len(y) == 0:
            raw_detections: list[dict[str, Any]] = []
        else:
            mel = librosa.feature.melspectrogram(
                y=y,
                sr=self.options.sample_rate,
                n_fft=2048,
            )
            mel_db = librosa.power_to_db(mel, ref=np.max)
            spectrogram_image = _spectrogram_to_rgb_image(mel_db, np=np, cm=cm, Image=Image)
            raw_detections = self._predict_image_detections(spectrogram_image, np=np, torch=torch)

        thresholded = [
            detection
            for detection in raw_detections
            if detection["score"] >= self.options.sensitivity
            and 0.0 <= detection["timeSeconds"] <= duration_seconds
        ]
        candidates = _non_max_suppressed_candidates(
            thresholded,
            min_distance_seconds=self.options.min_distance_seconds,
            max_candidates=self.options.max_candidates,
        )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "artifact": CUE_DETR_ARTIFACT_TYPE,
            "createdAtUtc": _utc_now_iso(),
            "producer": {
                "name": "cue-detr",
                "adapterVersion": CUE_DETR_ADAPTER_VERSION,
                "checkpoint": self.options.checkpoint,
            },
            "audioPath": str(audio_path),
            "durationSeconds": _round_float(duration_seconds),
            "parameters": {
                "sensitivity": self.options.sensitivity,
                "minDistanceSeconds": self.options.min_distance_seconds,
                "maxCandidates": self.options.max_candidates,
                "batchSize": self.options.batch_size,
                "sampleRate": self.options.sample_rate,
                "device": self.device,
            },
            "rawDetectionCount": len(raw_detections),
            "thresholdedDetectionCount": len(thresholded),
            "candidates": candidates,
        }

    def _predict_image_detections(self, image: Any, *, np: Any, torch: Any) -> list[dict[str, Any]]:
        image_width = int(image.shape[1])
        padded_width = image_width + _PADDING
        stride = _WINDOW_WIDTH * (1.0 - _OVERLAP)
        window_count = int(np.floor(padded_width / stride))
        if window_count <= 0:
            return []

        images = []
        borders: list[int] = []
        for index in range(window_count):
            left = int(np.floor(index * stride)) - _PADDING
            right = left + _WINDOW_WIDTH
            borders.append(left)
            images.append(_image_segment(image, left, right, np=np))

        raw_scores: list[float] = []
        raw_positions: list[int] = []
        target_sizes = [(_MEL_ROWS, _WINDOW_WIDTH)]
        for batch_start in range(0, len(images), self.options.batch_size):
            batch = images[batch_start : batch_start + self.options.batch_size]
            batch_borders = borders[batch_start : batch_start + self.options.batch_size]
            encoding = self.image_processor.preprocess(batch, do_resize=False, return_tensors="pt")
            pixel_values = encoding["pixel_values"].to(self.device)
            with torch.no_grad():
                outputs = self.model(pixel_values)
            predictions = self.image_processor.post_process_object_detection(
                outputs,
                threshold=0.0,
                target_sizes=target_sizes * pixel_values.shape[0],
            )
            for prediction, border in zip(predictions, batch_borders):
                scores = prediction["scores"].detach().cpu().tolist()
                boxes = prediction["boxes"].detach().cpu()
                centers = ((boxes[:, 0] + boxes[:, 2]) / 2.0).round().long().tolist()
                raw_scores.extend(float(score) for score in scores)
                raw_positions.extend(int(center + border) for center in centers)

        scaled_scores = _minmax_scale(raw_scores)
        detections = []
        for raw_position, raw_score, score in sorted(
            zip(raw_positions, raw_scores, scaled_scores),
            key=lambda item: item[0],
        ):
            detections.append(
                {
                    "timeSeconds": _round_float(
                        _frame_position_to_time_seconds(raw_position, self.options.sample_rate)
                    ),
                    "score": _round_float(score),
                    "rawScore": _round_float(raw_score),
                    "spectrogramFrame": int(raw_position),
                }
            )
        return detections


def predict_cue_detr_file(
    audio_path: str | Path,
    output_path: str | Path,
    *,
    options: CueDetrOptions | None = None,
) -> Path:
    """Predict CUE-DETR cue candidates and write a JSON artifact."""

    predictor = CueDetrPredictor(options)
    artifact = predictor.predict(audio_path)
    return write_json_atomic(Path(output_path), artifact)


def _load_dependencies() -> dict[str, Any]:
    missing = []
    loaded: dict[str, Any] = {}
    try:
        import librosa  # type: ignore

        loaded["librosa"] = librosa
    except ImportError:
        missing.append("librosa")
    try:
        from matplotlib import cm  # type: ignore

        loaded["cm"] = cm
    except ImportError:
        missing.append("matplotlib")
    try:
        import numpy as np  # type: ignore

        loaded["np"] = np
    except ImportError:
        missing.append("numpy")
    try:
        from PIL import Image  # type: ignore

        loaded["Image"] = Image
    except ImportError:
        missing.append("Pillow")
    try:
        import torch  # type: ignore

        loaded["torch"] = torch
    except ImportError:
        missing.append("torch")
    try:
        from transformers import DetrForObjectDetection, DetrImageProcessor  # type: ignore

        loaded["DetrForObjectDetection"] = DetrForObjectDetection
        loaded["DetrImageProcessor"] = DetrImageProcessor
    except ImportError:
        missing.append("transformers")

    if missing:
        raise CueDetrError(
            "cue_detr_dependencies_missing",
            "CUE-DETR dependencies are not installed. Install the cue-detr optional dependency set. "
            f"Missing imports: {', '.join(sorted(set(missing)))}",
        )
    return loaded


def _validate_options(options: CueDetrOptions) -> None:
    if not (0.0 <= options.sensitivity <= 1.0):
        raise CueDetrError("invalid_sensitivity", "sensitivity must be between 0.0 and 1.0")
    if options.min_distance_seconds < 0.0:
        raise CueDetrError("invalid_min_distance", "min_distance_seconds must be zero or greater")
    if options.max_candidates <= 0:
        raise CueDetrError("invalid_max_candidates", "max_candidates must be greater than zero")
    if options.batch_size <= 0:
        raise CueDetrError("invalid_batch_size", "batch_size must be greater than zero")
    if options.sample_rate <= 0:
        raise CueDetrError("invalid_sample_rate", "sample_rate must be greater than zero")


def _spectrogram_to_rgb_image(mel_db: Any, *, np: Any, cm: Any, Image: Any) -> Any:
    arr = mel_db[::-1]
    mapper = cm.ScalarMappable(cmap="viridis")
    mapper.set_clim(arr.min(), arr.max())
    rgba = mapper.to_rgba(arr, bytes=True)
    rgb_shape = (rgba.shape[1], rgba.shape[0])
    rgba = np.require(rgba, requirements="C")
    image = Image.frombuffer("RGBA", rgb_shape, rgba, "raw", "RGBA", 0, 1)
    return np.array(image)[:, :, :3]


def _image_segment(image: Any, left: int, right: int, *, np: Any) -> Any:
    if left < 0:
        segment = image[:, :right]
        return np.pad(segment, ((0, 0), (-left, 0), (0, 0)), mode="linear_ramp")
    if right > image.shape[1]:
        segment = image[:, left:]
        pad = right - left - segment.shape[1]
        return np.pad(segment, ((0, 0), (0, pad), (0, 0)), mode="linear_ramp")
    return image[:, left:right]


def _minmax_scale(values: list[float]) -> list[float]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if maximum <= minimum:
        return [1.0 for _ in values]
    return [(value - minimum) / (maximum - minimum) for value in values]


def _non_max_suppressed_candidates(
    detections: list[dict[str, Any]],
    *,
    min_distance_seconds: float,
    max_candidates: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for detection in sorted(detections, key=lambda item: (-float(item["score"]), float(item["timeSeconds"]))):
        time_seconds = float(detection["timeSeconds"])
        if any(abs(time_seconds - float(existing["timeSeconds"])) < min_distance_seconds for existing in selected):
            continue
        selected.append(dict(detection))
        if len(selected) >= max_candidates:
            break
    for rank, candidate in enumerate(selected, start=1):
        candidate["rank"] = rank
        candidate["backend"] = "cue-detr"
    return selected


def _frame_position_to_time_seconds(position: int, sample_rate: int) -> float:
    return float(position) * _HOP_LENGTH / sample_rate


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_cue_detr_artifact(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
