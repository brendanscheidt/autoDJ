"""AutoDJ offline analysis worker stub."""

__version__ = "0.1.0"

from .analyze import analyze_stub, build_analyzed_track_stub
from .batch import (
    ANALYZER_PRODUCER,
    ANALYZER_VERSION,
    BatchAnalysisResult,
    BatchTrackResult,
    DEFAULT_PARAMETERS_HASH,
    analyze_manifest,
    analyze_repository_manifest,
    artifact_identity_for_track,
    build_analyzed_track_artifact,
)
from .cache import (
    ArtifactIdentity,
    CacheError,
    FreshnessDecision,
    LoadedArtifact,
    analyzed_track_path,
    check_artifact_freshness,
    load_analyzed_artifact,
    track_cache_dir,
    write_json_atomic,
)
from .genre import classify_stub
from .manifest import (
    ManifestError,
    RepositoryManifest,
    RepositorySource,
    RepositoryTrack,
    load_repository_manifest,
    parse_repository_manifest,
    resolve_source_path,
)
from .probe import AudioProbe, ProbeError, parse_ffprobe_output, probe_audio

__all__ = [
    "__version__",
    "analyze_stub",
    "build_analyzed_track_stub",
    "ANALYZER_PRODUCER",
    "ANALYZER_VERSION",
    "BatchAnalysisResult",
    "BatchTrackResult",
    "DEFAULT_PARAMETERS_HASH",
    "analyze_manifest",
    "analyze_repository_manifest",
    "artifact_identity_for_track",
    "build_analyzed_track_artifact",
    "ArtifactIdentity",
    "CacheError",
    "FreshnessDecision",
    "LoadedArtifact",
    "analyzed_track_path",
    "check_artifact_freshness",
    "classify_stub",
    "load_analyzed_artifact",
    "track_cache_dir",
    "write_json_atomic",
    "ManifestError",
    "RepositoryManifest",
    "RepositorySource",
    "RepositoryTrack",
    "load_repository_manifest",
    "parse_repository_manifest",
    "AudioProbe",
    "ProbeError",
    "parse_ffprobe_output",
    "probe_audio",
    "resolve_source_path",
]
