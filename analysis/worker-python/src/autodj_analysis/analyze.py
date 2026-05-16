"""Stub analyzed-track artifact writer."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from . import __version__
from .identity import stable_track_id, stub_source_hash

SCHEMA_VERSION = "1.0.0"
ANALYZED_TRACK_FILENAME = "analyzed-track.json"


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_uri(audio_path: str | Path) -> str:
    return Path(audio_path).as_posix()


def build_analyzed_track_stub(audio_path: str | Path) -> dict[str, Any]:
    """Build a schema-shaped AnalyzedTrack artifact without reading audio."""

    track_id = stable_track_id(audio_path)
    source_hash = stub_source_hash(audio_path)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "trackId": track_id,
        "source": {
            "trackId": track_id,
            "repositoryId": "local-stub-repository",
            "sourceUri": _source_uri(audio_path),
            "contentHash": source_hash,
            "title": Path(str(audio_path)).stem or track_id,
            "durationSeconds": 180.0,
            "sampleRate": 44100,
            "channels": 2,
            "providerMetadata": {
                "analysisMode": "stub",
            },
        },
        "analyzer": {
            "producer": "autodj_analysis.stub",
            "producerVersion": __version__,
            "createdAtUtc": _utc_now_iso(),
            "sourceContentHash": source_hash,
            "parametersHash": "sha256:stub-default-parameters",
        },
        "durationSeconds": 180.0,
        "tempo": {
            "bpm": 140.0,
            "normalizedBpm": 140.0,
            "confidence": 1.0,
            "tempoClass": "straight",
            "candidates": [
                {
                    "bpm": 140.0,
                    "confidence": 1.0,
                },
                {
                    "bpm": 70.0,
                    "confidence": 0.7,
                },
            ],
        },
        "key": {
            "tonic": "unknown",
            "mode": "unknown",
            "confidence": 0.0,
            "candidates": [],
        },
        "beatGrid": {
            "confidence": 1.0,
            "beats": [
                {
                    "index": 0,
                    "timeSeconds": 0.0,
                    "beatInBar": 1,
                    "confidence": 1.0,
                },
                {
                    "index": 64,
                    "timeSeconds": 27.428571,
                    "beatInBar": 1,
                    "confidence": 1.0,
                },
                {
                    "index": 128,
                    "timeSeconds": 54.857143,
                    "beatInBar": 1,
                    "confidence": 1.0,
                },
            ],
            "downbeats": [
                {
                    "index": 0,
                    "timeSeconds": 0.0,
                    "beatInBar": 1,
                    "confidence": 1.0,
                },
                {
                    "index": 64,
                    "timeSeconds": 27.428571,
                    "beatInBar": 1,
                    "confidence": 1.0,
                },
                {
                    "index": 128,
                    "timeSeconds": 54.857143,
                    "beatInBar": 1,
                    "confidence": 1.0,
                },
            ],
        },
        "sections": [
            {
                "id": "section-intro",
                "type": "intro",
                "startSeconds": 0.0,
                "endSeconds": 27.428571,
                "startBeatIndex": 0,
                "endBeatIndex": 64,
                "energyMean": 0.25,
                "energyPeak": 0.35,
                "vocalPresence": 0.0,
                "confidence": 0.85,
            },
            {
                "id": "section-build",
                "type": "build",
                "startSeconds": 27.428571,
                "endSeconds": 54.857143,
                "startBeatIndex": 64,
                "endBeatIndex": 128,
                "energyMean": 0.65,
                "energyPeak": 0.9,
                "vocalPresence": 0.0,
                "confidence": 0.75,
            },
            {
                "id": "section-drop",
                "type": "drop",
                "startSeconds": 54.857143,
                "endSeconds": 109.714286,
                "startBeatIndex": 128,
                "endBeatIndex": 256,
                "energyMean": 0.9,
                "energyPeak": 1.0,
                "vocalPresence": 0.0,
                "confidence": 0.8,
            },
        ],
        "energy": {
            "globalEnergy": 0.75,
            "curve": [
                {
                    "timeSeconds": 0.0,
                    "value": 0.25,
                },
                {
                    "timeSeconds": 27.428571,
                    "value": 0.65,
                },
                {
                    "timeSeconds": 54.857143,
                    "value": 0.9,
                },
            ],
            "bassEnergyCurve": [
                {
                    "timeSeconds": 0.0,
                    "value": 0.2,
                },
                {
                    "timeSeconds": 54.857143,
                    "value": 0.95,
                },
            ],
            "onsetDensityCurve": [
                {
                    "timeSeconds": 0.0,
                    "value": 0.25,
                },
                {
                    "timeSeconds": 54.857143,
                    "value": 0.8,
                },
            ],
        },
        "vocals": {
            "hasVocals": False,
            "confidence": 0.5,
            "regions": [],
        },
        "cuePoints": [
            {
                "id": "cue-mix-in",
                "type": "mix_in",
                "timeSeconds": 0.0,
                "beatIndex": 0,
                "sectionId": "section-intro",
                "confidence": 1.0,
                "tags": [
                    "stub",
                    "phrase_start",
                ],
            },
            {
                "id": "cue-build-start",
                "type": "build_start",
                "timeSeconds": 27.428571,
                "beatIndex": 64,
                "sectionId": "section-build",
                "confidence": 0.75,
            },
            {
                "id": "cue-drop",
                "type": "drop",
                "timeSeconds": 54.857143,
                "beatIndex": 128,
                "sectionId": "section-drop",
                "confidence": 0.8,
            },
        ],
        "quality": {
            "overallConfidence": 0.5,
            "warnings": [
                "Foundation stub does not decode or analyze audio",
            ],
        },
    }


def analyze_stub(audio_path: str | Path, output_dir: str | Path) -> Path:
    """Write ``analyzed-track.json`` atomically and return its path."""

    artifact = build_analyzed_track_stub(audio_path)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    destination = output_path / ANALYZED_TRACK_FILENAME
    temporary = destination.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(artifact, file, indent=2)
        file.write("\n")

    temporary.replace(destination)
    return destination
