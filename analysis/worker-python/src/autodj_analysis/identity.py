"""Deterministic identity helpers for stub artifacts."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re


def stable_track_id(audio_path: str | Path) -> str:
    """Create a stable placeholder track ID from the submitted path."""

    path_text = str(audio_path).strip()
    if not path_text:
        raise ValueError("audio path must not be empty")

    stem = Path(path_text).stem or "track"
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "track"
    digest = sha256(path_text.encode("utf-8")).hexdigest()[:12]
    return f"track-{slug}-{digest}"


def stub_source_hash(audio_path: str | Path) -> str:
    """Return a deterministic non-content hash for the foundation stub."""

    digest = sha256(str(audio_path).encode("utf-8")).hexdigest()
    return f"sha256:stub-path-{digest}"
