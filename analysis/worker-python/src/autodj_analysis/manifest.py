"""Repository manifest reader for batch analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib.request import url2pathname


SUPPORTED_SCHEMA_VERSION = "1.0.0"


class ManifestError(ValueError):
    """Expected repository manifest loading or validation failure."""

    def __init__(self, code: str, message: str, source_uri: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.source_uri = source_uri

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.source_uri is not None:
            payload["sourceUri"] = self.source_uri
        return payload


@dataclass(frozen=True)
class RepositorySource:
    repository_type: str
    root_uri: str
    root_path: Path | None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepositoryTrack:
    track_id: str
    repository_id: str
    source_uri: str
    source_path: Path
    content_hash: str | None = None
    format_hint: str | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepositoryManifest:
    schema_version: str
    repository_id: str
    producer: str
    producer_version: str
    created_at_utc: str
    source: RepositorySource
    tracks: tuple[RepositoryTrack, ...]
    manifest_path: Path | None = None


def load_repository_manifest(path: str | Path) -> RepositoryManifest:
    """Load and validate a repository manifest JSON file."""

    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(
            "manifest_read_error",
            f"Could not read repository manifest: {exc}",
            str(manifest_path),
        ) from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(
            "manifest_parse_error",
            f"Could not parse repository manifest JSON: {exc.msg}",
            str(manifest_path),
        ) from exc

    return parse_repository_manifest(payload, manifest_path)


def parse_repository_manifest(
    payload: Mapping[str, Any],
    manifest_path: str | Path | None = None,
) -> RepositoryManifest:
    """Validate the manifest subset needed by the analysis worker."""

    if not isinstance(payload, Mapping):
        raise ManifestError("manifest_parse_error", "Repository manifest root must be a JSON object")

    schema_version = _required_string(payload, "schemaVersion", "manifest")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ManifestError(
            "manifest_schema_unsupported",
            f"Unsupported repository manifest schemaVersion '{schema_version}'",
        )

    repository_id = _required_string(payload, "repositoryId", "manifest")
    source_payload = _required_mapping(payload, "source", "manifest")
    source = _parse_source(source_payload)

    tracks_payload = payload.get("tracks")
    if not isinstance(tracks_payload, list):
        raise ManifestError("manifest_missing_field", "Manifest field 'tracks' must be an array")

    tracks = tuple(
        _parse_track(track_payload, source.root_path, index)
        for index, track_payload in enumerate(tracks_payload)
    )

    return RepositoryManifest(
        schema_version=schema_version,
        repository_id=repository_id,
        producer=_required_string(payload, "producer", "manifest"),
        producer_version=_required_string(payload, "producerVersion", "manifest"),
        created_at_utc=_required_string(payload, "createdAtUtc", "manifest"),
        source=source,
        tracks=tracks,
        manifest_path=Path(manifest_path) if manifest_path is not None else None,
    )


def resolve_source_path(source_uri: str, repository_root: str | Path | None = None) -> Path:
    """Resolve a manifest source URI to a local path candidate for probing.

    The returned path is intentionally separate from the stored source URI so
    provider identity remains unchanged in generated artifacts.
    """

    local_path = _local_uri_to_path(source_uri)
    if local_path is None:
        return Path(source_uri)
    if local_path.is_absolute() or repository_root is None:
        return local_path
    return Path(repository_root) / local_path


def _parse_source(payload: Mapping[str, Any]) -> RepositorySource:
    root_uri = _required_string(payload, "rootUri", "manifest.source")
    provider_metadata = _optional_mapping(payload, "providerMetadata", "manifest.source")
    return RepositorySource(
        repository_type=_required_string(payload, "repositoryType", "manifest.source"),
        root_uri=root_uri,
        root_path=_local_uri_to_path(root_uri),
        provider_metadata=provider_metadata,
    )


def _parse_track(payload: Any, repository_root: Path | None, index: int) -> RepositoryTrack:
    context = f"manifest.tracks[{index}]"
    if not isinstance(payload, Mapping):
        raise ManifestError("manifest_missing_field", f"{context} must be a JSON object")

    source_uri = _required_string(payload, "sourceUri", context)
    return RepositoryTrack(
        track_id=_required_string(payload, "trackId", context),
        repository_id=_required_string(payload, "repositoryId", context),
        source_uri=source_uri,
        source_path=resolve_source_path(source_uri, repository_root),
        content_hash=_optional_string(payload, "contentHash", context),
        format_hint=_optional_string(payload, "formatHint", context),
        title=_optional_string(payload, "title", context),
        artist=_optional_string(payload, "artist", context),
        album=_optional_string(payload, "album", context),
        duration_seconds=_optional_number(payload, "durationSeconds", context),
        sample_rate=_optional_positive_int(payload, "sampleRate", context),
        channels=_optional_positive_int(payload, "channels", context),
        provider_metadata=_optional_mapping(payload, "providerMetadata", context),
    )


def _required_mapping(payload: Mapping[str, Any], field_name: str, context: str) -> Mapping[str, Any]:
    if field_name not in payload or not isinstance(payload[field_name], Mapping):
        raise ManifestError("manifest_missing_field", f"{context}.{field_name} is required and must be an object")
    return payload[field_name]


def _required_string(payload: Mapping[str, Any], field_name: str, context: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or value == "":
        raise ManifestError(
            "manifest_missing_field",
            f"{context}.{field_name} is required and must be a non-empty string",
        )
    return value


def _optional_string(payload: Mapping[str, Any], field_name: str, context: str) -> str | None:
    if field_name not in payload or payload[field_name] is None:
        return None
    value = payload[field_name]
    if not isinstance(value, str):
        raise ManifestError("manifest_missing_field", f"{context}.{field_name} must be a string when present")
    return value


def _optional_number(payload: Mapping[str, Any], field_name: str, context: str) -> float | None:
    if field_name not in payload or payload[field_name] is None:
        return None
    value = payload[field_name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ManifestError(
            "manifest_missing_field",
            f"{context}.{field_name} must be a non-negative number when present",
        )
    return float(value)


def _optional_positive_int(payload: Mapping[str, Any], field_name: str, context: str) -> int | None:
    if field_name not in payload or payload[field_name] is None:
        return None
    value = payload[field_name]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ManifestError("manifest_missing_field", f"{context}.{field_name} must be a positive integer when present")
    return value


def _optional_mapping(payload: Mapping[str, Any], field_name: str, context: str) -> dict[str, Any]:
    if field_name not in payload or payload[field_name] is None:
        return {}
    value = payload[field_name]
    if not isinstance(value, Mapping):
        raise ManifestError("manifest_missing_field", f"{context}.{field_name} must be an object when present")
    return dict(value)


def _local_uri_to_path(value: str) -> Path | None:
    scheme = _uri_scheme(value)
    if scheme == "file":
        parsed = urlparse(value)
        path = url2pathname(parsed.path)
        if parsed.netloc and parsed.netloc != "localhost":
            path = f"//{parsed.netloc}{path}"
        return Path(path)
    if scheme:
        return None
    return Path(value)


def _uri_scheme(value: str) -> str:
    if _looks_like_windows_drive_path(value):
        return ""
    parsed = urlparse(value)
    return parsed.scheme.lower()


def _looks_like_windows_drive_path(value: str) -> bool:
    return len(value) >= 2 and value[0].isalpha() and value[1] == ":"
