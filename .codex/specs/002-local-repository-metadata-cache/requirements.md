# Requirements Document

## Introduction

This spec implements AutoDJ's first real ingestion layer. The foundation spec
created a repository module and JSON contract surfaces; this spec makes the
local repository useful by scanning local folders, generating stable track
records, computing content hashes, persisting repository manifests, and creating
metadata cache paths for later analysis artifacts.

The implementation must stay focused on ingestion and cache identity. It should
not decode audio, analyze audio, classify genres, choose transitions, play
audio, or integrate streaming providers.

## Requirement 1: Local Folder Scanning

**User Story:** As a user, I want AutoDJ to scan a local folder for audio files,
so my local tracks can enter the AutoDJ pipeline.

### Acceptance Criteria

1. WHEN `LocalAudioRepository` is constructed with a root folder THEN it SHALL
   retain that folder as repository configuration.
2. WHEN a scan runs against an existing folder THEN it SHALL discover `.wav` and
   `.mp3` files case-insensitively.
3. WHEN a scan encounters unsupported file extensions THEN it SHALL ignore them
   without producing track records.
4. WHEN a scan completes THEN discovered tracks SHALL be returned in
   deterministic order.
5. WHEN a scan is requested for a missing or invalid root THEN the repository
   SHALL return a structured scan result or error without crashing.

## Requirement 2: Stable Track Assets

**User Story:** As an analysis developer, I want stable track assets, so cached
analysis artifacts can be associated with the same local file across runs.

### Acceptance Criteria

1. WHEN a supported file is discovered THEN the repository SHALL create a
   `TrackAsset` or equivalent record.
2. WHEN a track record is inspected THEN it SHALL include `trackId`,
   `repositoryId`, `sourceUri`, `contentHash`, and `formatHint` where known.
3. WHEN the same repository root is scanned repeatedly without file path
   changes THEN the same file SHALL receive the same `trackId`.
4. WHEN file contents change THEN the file's content hash SHALL change.
5. WHEN track IDs are generated THEN they SHALL be stable strings rather than
   array indexes.

## Requirement 3: Repository Scan Results

**User Story:** As a UI developer, I want scan results that describe changes, so
the app can explain what was imported or updated.

### Acceptance Criteria

1. WHEN a scan runs with no prior manifest THEN the result SHALL report newly
   discovered tracks as added.
2. WHEN a scan runs with a prior manifest THEN unchanged files SHALL not be
   reported as updated.
3. WHEN a previously scanned file changes content hash THEN the result SHALL
   report it as updated.
4. WHEN a previously scanned file is missing THEN the result SHALL report it as
   removed.
5. WHEN a per-file error occurs THEN the result SHALL include a structured
   `RepositoryError` or equivalent without discarding successful tracks.

## Requirement 4: Repository Manifest Persistence

**User Story:** As a maintainer, I want a versioned repository manifest, so the
repository state can be restored and compared between runs.

### Acceptance Criteria

1. WHEN a scan result is persisted THEN the repository SHALL write
   `.autodj-cache/repository-manifest.json` or a caller-provided equivalent path.
2. WHEN the manifest is inspected THEN it SHALL include `schemaVersion`,
   `repositoryId`, producer provenance, source information, track records, and
   scan summary fields.
3. WHEN the manifest is written THEN its top-level shape SHALL remain compatible
   with `core/contracts/schemas/repository-manifest.schema.json`.
4. WHEN the manifest is read back THEN the repository SHALL recover the track
   list and source metadata needed for a later scan comparison.
5. WHEN malformed or incompatible manifest JSON is read THEN the reader SHALL
   report a structured error.

## Requirement 5: Metadata Cache Layout

**User Story:** As an analysis developer, I want deterministic cache paths, so
analysis workers can write artifacts in predictable locations.

### Acceptance Criteria

1. WHEN a cache root is configured THEN the repository/cache helper SHALL resolve
   `.autodj-cache` by default or use the provided root.
2. WHEN a track ID is provided THEN the helper SHALL resolve
   `tracks/<track-id>/`.
3. WHEN an analyzed-track path is requested THEN the helper SHALL resolve
   `tracks/<track-id>/analyzed-track.json`.
4. WHEN a waveform path is requested THEN the helper SHALL resolve
   `tracks/<track-id>/waveform.json`.
5. WHEN a stems directory is requested THEN the helper SHALL resolve
   `tracks/<track-id>/stems/`.
6. WHEN path helpers are called THEN they SHALL not write analysis, waveform, or
   stem artifacts in this spec.

## Requirement 6: Module Boundaries

**User Story:** As an architecture maintainer, I want repository work isolated,
so future playback and DJ implementations remain independent.

### Acceptance Criteria

1. WHEN repository code is inspected THEN it SHALL not import playback or DJ
   strategy modules.
2. WHEN repository code is inspected THEN it SHALL not call the Python analysis
   worker.
3. WHEN repository code is inspected THEN it SHALL not decode audio or estimate
   duration, BPM, key, sections, or waveform data.
4. WHEN repository tests run THEN they SHALL use generated temporary test files
   only and SHALL NOT require real music files.

## Requirement 7: Verification

**User Story:** As a future task executor, I want repeatable verification, so
the ingestion layer can evolve without regressing the foundation.

### Acceptance Criteria

1. WHEN implementation completes THEN `cmake --preset debug` SHALL configure.
2. WHEN implementation completes THEN `cmake --build --preset debug` SHALL
   build all C++ targets.
3. WHEN implementation completes THEN `ctest --preset debug` SHALL pass all C++
   tests.
4. WHEN implementation completes THEN existing Python worker tests SHALL still
   pass or an explicit blocker SHALL be documented.
5. WHEN a task is completed THEN `tasks.md` SHALL be updated to mark only the
   completed verified work.
