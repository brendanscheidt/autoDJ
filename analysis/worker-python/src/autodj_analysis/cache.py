"""Metadata cache helpers for analysis artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


ANALYZED_TRACK_FILENAME = "analyzed-track.json"
WAVEFORM_FILENAME = "waveform.json"
SCHEMA_VERSION = "1.0.0"


class CacheError(ValueError):
    """Expected metadata cache path or write failure."""

    def __init__(self, code: str, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.path is not None:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class ArtifactIdentity:
    track_id: str
    analyzer_producer: str
    analyzer_version: str
    source_content_hash: str | None
    parameters_hash: str | None
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class LoadedArtifact:
    path: Path
    artifact: dict[str, Any] | None
    error_code: str | None = None
    message: str | None = None

    @property
    def loaded(self) -> bool:
        return self.artifact is not None and self.error_code is None


@dataclass(frozen=True)
class FreshnessDecision:
    is_fresh: bool
    reason: str
    message: str

    @property
    def should_analyze(self) -> bool:
        return not self.is_fresh


def track_cache_dir(cache_root: str | Path, track_id: str) -> Path:
    """Return the per-track cache directory without creating it."""

    return Path(cache_root) / "tracks" / _safe_track_id(track_id)


def analyzed_track_path(cache_root: str | Path, track_id: str) -> Path:
    """Return `<cache-root>/tracks/<track-id>/analyzed-track.json`."""

    return track_cache_dir(cache_root, track_id) / ANALYZED_TRACK_FILENAME


def waveform_path(cache_root: str | Path, track_id: str) -> Path:
    """Return `<cache-root>/tracks/<track-id>/waveform.json`."""

    return track_cache_dir(cache_root, track_id) / WAVEFORM_FILENAME


def write_json_atomic(destination: str | Path, payload: Mapping[str, Any]) -> Path:
    """Write JSON to a destination path using a same-directory temp file."""

    destination_path = Path(destination)
    temporary_path: Path | None = None
    try:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = destination_path.parent / f".{destination_path.name}.{uuid4().hex}.tmp"
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
            file.write("\n")
        temporary_path.replace(destination_path)
    except (OSError, TypeError, ValueError) as exc:
        if temporary_path is not None:
            _remove_temporary_file(temporary_path)
        raise CacheError(
            "artifact_write_error",
            f"Could not write JSON artifact: {exc}",
            str(destination_path),
        ) from exc
    return destination_path


def load_analyzed_artifact(path: str | Path) -> LoadedArtifact:
    """Load an existing artifact without throwing for expected cache states."""

    return load_json_artifact(path, artifact_name="Analyzed artifact")


def load_waveform_artifact(path: str | Path) -> LoadedArtifact:
    """Load an existing waveform artifact without throwing for expected cache states."""

    return load_json_artifact(path, artifact_name="Waveform artifact")


def load_json_artifact(path: str | Path, *, artifact_name: str = "Artifact") -> LoadedArtifact:
    """Load an existing JSON artifact without throwing for expected cache states."""

    artifact_path = Path(path)
    if not artifact_path.exists():
        return LoadedArtifact(
            path=artifact_path,
            artifact=None,
            error_code="artifact_missing",
            message=f"{artifact_name} does not exist",
        )

    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return LoadedArtifact(
            path=artifact_path,
            artifact=None,
            error_code="artifact_read_error",
            message=f"Could not read {artifact_name.lower()}: {exc}",
        )
    except json.JSONDecodeError as exc:
        return LoadedArtifact(
            path=artifact_path,
            artifact=None,
            error_code="artifact_malformed_json",
            message=f"Could not parse {artifact_name.lower()} JSON: {exc.msg}",
        )

    if not isinstance(payload, dict):
        return LoadedArtifact(
            path=artifact_path,
            artifact=None,
            error_code="artifact_malformed_json",
            message=f"{artifact_name} root must be a JSON object",
        )

    return LoadedArtifact(path=artifact_path, artifact=payload)


def check_artifact_freshness(
    loaded: LoadedArtifact,
    expected: ArtifactIdentity,
    *,
    force: bool = False,
) -> FreshnessDecision:
    """Compare an existing artifact with the freshness key required by spec 003."""

    if force:
        return FreshnessDecision(False, "force", "Forced analysis requested")
    if expected.source_content_hash is None:
        return FreshnessDecision(
            False,
            "source_content_hash_unavailable",
            "Cannot prove artifact freshness without a source content hash",
        )
    if expected.parameters_hash is None:
        return FreshnessDecision(
            False,
            "parameters_hash_unavailable",
            "Cannot prove artifact freshness without an analyzer parameters hash",
        )
    if not loaded.loaded:
        return FreshnessDecision(
            False,
            loaded.error_code or "artifact_unavailable",
            loaded.message or "Analyzed artifact is unavailable",
        )

    artifact = loaded.artifact
    assert artifact is not None

    analyzer = artifact.get("analyzer")
    if not isinstance(analyzer, Mapping):
        return FreshnessDecision(False, "artifact_missing_field", "analyzer must be an object")

    comparisons = (
        ("schemaVersion", artifact.get("schemaVersion"), expected.schema_version, "schema_version_mismatch"),
        ("trackId", artifact.get("trackId"), expected.track_id, "track_id_mismatch"),
        (
            "analyzer.producer",
            analyzer.get("producer"),
            expected.analyzer_producer,
            "analyzer_producer_mismatch",
        ),
        (
            "analyzer.producerVersion",
            analyzer.get("producerVersion"),
            expected.analyzer_version,
            "analyzer_version_mismatch",
        ),
        (
            "analyzer.sourceContentHash",
            analyzer.get("sourceContentHash"),
            expected.source_content_hash,
            "source_content_hash_mismatch",
        ),
        (
            "analyzer.parametersHash",
            analyzer.get("parametersHash"),
            expected.parameters_hash,
            "parameters_hash_mismatch",
        ),
    )

    for field_name, actual, expected_value, mismatch_reason in comparisons:
        if actual is None and expected_value is not None:
            return FreshnessDecision(False, "artifact_missing_field", f"{field_name} is missing")
        if actual != expected_value:
            return FreshnessDecision(
                False,
                mismatch_reason,
                f"{field_name} expected {expected_value!r} but found {actual!r}",
            )

    return FreshnessDecision(True, "fresh", "Analyzed artifact is current")


def check_analysis_artifact_freshness(
    analyzed: LoadedArtifact,
    waveform: LoadedArtifact,
    expected: ArtifactIdentity,
    *,
    force: bool = False,
) -> FreshnessDecision:
    """Require both analyzed-track and waveform artifacts to be current."""

    analyzed_decision = check_artifact_freshness(analyzed, expected, force=force)
    if not analyzed_decision.is_fresh:
        return analyzed_decision

    waveform_decision = check_artifact_freshness(waveform, expected)
    if not waveform_decision.is_fresh:
        return FreshnessDecision(
            False,
            _waveform_reason(waveform_decision.reason),
            f"Waveform artifact is not current: {waveform_decision.message}",
        )

    return FreshnessDecision(True, "fresh", "Analyzed and waveform artifacts are current")


def _safe_track_id(track_id: str) -> str:
    if not track_id or track_id in {".", ".."}:
        raise CacheError("artifact_path_error", "Track ID must be a non-empty cache path segment")
    if "/" in track_id or "\\" in track_id:
        raise CacheError("artifact_path_error", f"Unsafe track ID for cache path: {track_id!r}")
    return track_id


def _remove_temporary_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _waveform_reason(reason: str) -> str:
    if reason.startswith("waveform_"):
        return reason
    if reason.startswith("artifact_"):
        return f"waveform_{reason}"
    return f"waveform_{reason}"
