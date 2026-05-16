# Spec 002: Local Repository And Metadata Cache

> Kiro-style execution package:
> `.codex/specs/002-local-repository-metadata-cache/`
>
> Use that folder's `kiro.json`, `requirements.md`, `design.md`, and
> `tasks.md` when executing implementation tasks. This file remains the source
> summary.

## Purpose

Implement the first real ingestion layer for AutoDJ. This spec turns the
repository skeleton into a local folder scanner that discovers WAV/MP3 files,
assigns stable track identities, computes content hashes, writes a repository
manifest, and creates the metadata cache layout needed by later analysis specs.

This spec should make local music visible to the system, but it should not
decode audio, analyze BPM/key/sections, play audio, or integrate streaming
providers.

## Steering References

Read these before implementing:

- `.codex/steering/00-product-vision.md`
- `.codex/steering/01-system-architecture.md`
- `.codex/steering/02-core-contracts.md`
- `.codex/steering/03-tech-stack.md`
- `.codex/steering/04-project-structure.md`
- `.codex/steering/08-engineering-practices.md`
- `.codex/steering/09-roadmap.md`

## Goals

- Expand `LocalAudioRepository` from a placeholder into a deterministic local
  scanner.
- Discover `.wav` and `.mp3` files from a configured folder.
- Return stable `TrackAsset` records with IDs, source URIs, format hints, and
  content hashes.
- Write and read `repository-manifest.json` matching the repository manifest
  contract.
- Establish `.autodj-cache/tracks/<track-id>/` paths for later analysis
  artifacts.
- Detect changed files by content hash.
- Keep repository code independent from playback, DJ strategy, and analysis
  algorithms.
- Add tests using generated temporary files only.

## Non-goals

- No FFmpeg, Essentia, librosa, Demucs, or waveform generation.
- No duration/sample-rate/channel probing beyond optional placeholders.
- No real audio decoding.
- No desktop UI import workflow beyond optional thin wiring if the task list
  explicitly asks for it.
- No SQLite.
- No Spotify, SoundCloud, YouTube, Apple Music, or cloud sync.
- No genre analysis beyond preserving the existing stub boundary.

## Required Deliverables

### Repository Domain Surface

Add C++ data structures for repository artifacts where appropriate:

- `TrackAsset`
- `RepositoryScanResult`
- `RepositoryError`
- `RepositoryManifest`
- `ResolvedAudioAsset`

These should align with `.codex/steering/02-core-contracts.md` and
`core/contracts/schemas/repository-manifest.schema.json`.

### Local Scanner

`LocalAudioRepository` should:

- Accept a repository root path and optional repository ID.
- Recursively discover files with `.wav` and `.mp3` extensions,
  case-insensitively.
- Ignore directories and unsupported file types.
- Avoid following symlinked directories unless explicitly implemented with loop
  protection.
- Generate stable track IDs from repository ID plus normalized relative path.
- Compute content hashes for discovered files.
- Return deterministic ordering for scanned tracks.
- Report per-file errors without failing the whole scan when possible.

### Manifest Persistence

Implement writing and reading:

```text
.autodj-cache/
  repository-manifest.json
```

The manifest should include:

- `schemaVersion`
- `repositoryId`
- `producer`
- `producerVersion`
- `createdAtUtc`
- `source.repositoryType`
- `source.rootUri`
- `tracks[]`
- `scan`

The JSON shape should stay compatible with
`repository-manifest.schema.json`.

### Metadata Cache Layout

Add helpers for:

```text
.autodj-cache/
  tracks/
    <track-id>/
      analyzed-track.json
      waveform.json
      stems/
```

This spec only creates and resolves paths. It should not write real analysis,
waveform, or stem artifacts.

### Tests

Use CTest and temporary directories.

Tests should cover:

- WAV/MP3 discovery.
- Unsupported file filtering.
- Deterministic track ordering and IDs.
- Content hash changes when a file changes.
- Manifest write/read roundtrip.
- Cache path helper behavior.
- Error handling for missing roots or unreadable paths where practical.

## Suggested Verification Commands

```powershell
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
```

Python commands should continue to pass even though this spec does not extend
the Python worker:

```powershell
.\.venv\Scripts\python -m pytest .\analysis\worker-python
.\.venv\Scripts\python -m autodj_analysis --help
```

## Acceptance Criteria

- `LocalAudioRepository` can scan a folder containing fake `.wav` and `.mp3`
  files.
- Repository scan results are deterministic.
- Track IDs are stable across repeated scans of the same folder.
- Track content hashes change when file bytes change.
- A repository manifest can be written and read back.
- The manifest shape matches the contract examples at the top level.
- Cache path helpers produce `.autodj-cache/tracks/<track-id>/` paths.
- Existing C++ and Python tests remain green.

## Follow-up Specs

Likely next specs:

- `003-analysis-mvp`
- `004-playback-engine-command-scheduler`
- `005-dubstep-dj-first-transitions`
