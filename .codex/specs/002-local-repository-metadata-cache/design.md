# Design Document

## Overview

This spec expands `core/repository` from a constructible placeholder into the
first useful ingestion module. The local repository scans a folder for supported
audio files, creates stable `TrackAsset` records, computes content hashes,
writes a versioned manifest, and exposes metadata cache paths for later
analysis.

The design intentionally stops before audio decoding. WAV/MP3 files are treated
as files with names, paths, extensions, and bytes. Duration, sample rate,
channels, tags, waveform previews, BPM, key, sections, cue points, and stems are
left to later analysis specs.

## Steering Context

Implementation agents must read:

- `.codex/steering/00-product-vision.md`
- `.codex/steering/01-system-architecture.md`
- `.codex/steering/02-core-contracts.md`
- `.codex/steering/03-tech-stack.md`
- `.codex/steering/04-project-structure.md`
- `.codex/steering/08-engineering-practices.md`
- `.codex/steering/09-roadmap.md`

## Architecture

Relevant pipeline segment:

```text
LocalAudioRepository
  -> RepositoryManifest
  -> MetadataCache paths
  -> future GenreAnalyzer / AnalysisWorker
```

Dependency direction:

```text
core/repository
  -> core/domain
  -> core/contracts artifacts by shape only
```

`core/repository` must not depend on `core/playback`, `core/dj`, the JUCE
desktop app, or the Python analysis worker.

## Public Surface

The exact C++ naming can follow existing project style, but the module should
expose these concepts.

### `TrackAsset`

Suggested shape:

```cpp
struct TrackAsset {
    domain::TrackId trackId;
    std::string repositoryId;
    std::filesystem::path sourcePath;
    std::string sourceUri;
    std::string contentHash;
    std::string formatHint;
    std::optional<std::string> title;
    std::optional<std::string> artist;
    std::optional<double> durationSeconds;
    std::optional<int> sampleRate;
    std::optional<int> channels;
};
```

For this spec:

- `sourcePath` is for local implementation use.
- `sourceUri` should be a stable serialized path string suitable for JSON.
- `formatHint` should be `wav`, `mp3`, or `unknown`.
- duration/sample-rate/channels can remain unset.

### `RepositoryScanResult`

Suggested shape:

```cpp
struct RepositoryScanResult {
    std::string repositoryId;
    std::vector<TrackAsset> tracks;
    std::size_t tracksAdded = 0;
    std::size_t tracksUpdated = 0;
    std::size_t tracksRemoved = 0;
    std::vector<RepositoryError> errors;
};
```

The scan result should carry enough state to write a manifest and enough
summary counts for UI display.

### `RepositoryManifest`

Suggested shape:

```cpp
struct RepositoryManifest {
    std::string schemaVersion;
    std::string repositoryId;
    std::string producer;
    std::string producerVersion;
    std::string createdAtUtc;
    RepositorySource source;
    std::vector<TrackAsset> tracks;
    RepositoryScanSummary scan;
};
```

The persisted JSON should align with
`core/contracts/schemas/repository-manifest.schema.json`.

### `MetadataCachePaths`

Suggested helper:

```cpp
class MetadataCachePaths {
public:
    explicit MetadataCachePaths(std::filesystem::path cacheRoot);

    std::filesystem::path root() const;
    std::filesystem::path repositoryManifestPath() const;
    std::filesystem::path trackRoot(const domain::TrackId& trackId) const;
    std::filesystem::path analyzedTrackPath(const domain::TrackId& trackId) const;
    std::filesystem::path waveformPath(const domain::TrackId& trackId) const;
    std::filesystem::path stemsDirectory(const domain::TrackId& trackId) const;
};
```

This helper may create directories only when explicitly asked by a method such
as `ensureTrackDirectories(trackId)`. Path resolution alone should not write
analysis artifacts.

## Local Repository Behavior

### Construction

`LocalAudioRepository` should accept:

- A repository root path.
- Optional repository ID.
- Optional cache root path, defaulting to `<repository-root>/.autodj-cache` or
  caller-provided `.autodj-cache`.

Repository ID should be stable for a given configured root unless explicitly
provided. A conservative default is a slug plus hash derived from the normalized
root path.

### Scanning

Scan steps:

1. Validate the root exists and is a directory.
2. Recursively walk the root.
3. Ignore directories, cache directories, and unsupported extensions.
4. Treat `.wav` and `.mp3` as supported extensions case-insensitively.
5. Avoid following symlinked directories unless loop protection is implemented.
6. For each supported file:
   - compute normalized relative path from root,
   - compute stable `trackId`,
   - compute file content hash,
   - create a `TrackAsset`.
7. Sort tracks by normalized relative path or track ID.
8. Compare against prior manifest when available.
9. Return scan result with added/updated/removed counts.

### Track IDs

Track IDs must not be array indexes.

Suggested deterministic strategy:

```text
track-<short-slug-of-relative-path>-<first-12-hex-of-hash(repositoryId + relativePath)>
```

Use normalized forward slashes for the relative path before hashing. Keep path
case as the filesystem reports it, but compare/sort consistently.

### Content Hashing

Use SHA-256 for content invalidation and prefix values with `sha256:`.

This is for cache correctness, not security. It is acceptable to add a small
internal SHA-256 helper under `core/repository` if no existing dependency is
available. Do not introduce OpenSSL, Crypto++, or another large dependency just
for this spec.

### Manifest Comparison

Given previous manifest tracks and current scan tracks:

- added: current track ID not present in previous manifest.
- updated: same track ID present but content hash changed.
- removed: previous track ID not present in current scan.
- unchanged: same track ID and same content hash.

If track IDs include relative path, renames will naturally appear as removed +
added. That is acceptable for this spec.

## JSON Persistence

Use structured JSON writing with deterministic field order where practical.

Manifest path:

```text
.autodj-cache/repository-manifest.json
```

Minimum manifest example shape:

```json
{
  "schemaVersion": "1.0.0",
  "repositoryId": "local-my-folder-a1b2c3d4",
  "producer": "autodj.repository.local",
  "producerVersion": "0.1.0",
  "createdAtUtc": "2026-01-01T00:00:00Z",
  "source": {
    "repositoryType": "local",
    "rootUri": "C:/Music"
  },
  "tracks": [],
  "scan": {
    "repositoryId": "local-my-folder-a1b2c3d4",
    "tracksAdded": 0,
    "tracksUpdated": 0,
    "tracksRemoved": 0,
    "errors": []
  }
}
```

The implementation may use a narrow JSON writer/parser for this manifest only
if no JSON library has been introduced yet. Prefer keeping JSON handling
isolated in repository persistence files so a future generated-contract layer
can replace it.

## Error Handling

Expected failures should be represented as values, not crashes.

Examples:

- root missing.
- root is not a directory.
- file cannot be opened for hashing.
- manifest cannot be parsed.
- manifest schema version is unsupported.

Fatal programming errors can still use assertions in tests, but user-facing
repository operations should return structured errors.

## Tests

Use CTest through `core/repository/tests`.

Create temporary directories under the test process temp directory. Test files
can contain simple ASCII bytes; they do not need to be valid audio because this
spec does not decode.

Recommended tests:

- `scanDiscoversSupportedAudioFiles`
- `scanIgnoresUnsupportedFiles`
- `scanOrdersTracksDeterministically`
- `trackIdsAreStableAcrossScans`
- `contentHashChangesWhenFileBytesChange`
- `manifestRoundTrips`
- `scanReportsAddedUpdatedRemoved`
- `cachePathsResolveExpectedLocations`
- `missingRootReturnsStructuredError`

## Verification

Required:

```powershell
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
```

Recommended regression checks:

```powershell
.\.venv\Scripts\python -m pytest .\analysis\worker-python
.\.venv\Scripts\python -m autodj_analysis --help
```

## Implementation Constraints

- Do not add real audio files.
- Do not decode audio.
- Do not probe duration or tags with FFmpeg.
- Do not call Python from repository code.
- Do not add SQLite.
- Do not alter playback or DJ strategy behavior except if test/build wiring
  requires a narrow include adjustment.
- Keep repository tests fast and deterministic.
