"""Stub genre classification for the foundation worker."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .identity import stable_track_id


def classify_stub(audio_path: str | Path) -> dict[str, Any]:
    """Return the MVP genre verdict shape without reading audio."""

    return {
        "trackId": stable_track_id(audio_path),
        "primaryGenre": "dubstep",
        "confidence": 1.0,
        "allowedForAutoDj": True,
        "candidateGenres": [
            {
                "genre": "dubstep",
                "confidence": 1.0,
            }
        ],
        "reason": "MVP stub assumes local imports are dubstep",
    }
