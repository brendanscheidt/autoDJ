# Implementation Plan

## Execution Rules

- Before starting any task, read `kiro.json`, `requirements.md`, `design.md`,
  and the required steering docs listed in `kiro.json`.
- Only mark a checkbox complete after implementing and verifying that task.
- Keep work within the task ownership unless the task explicitly says
  otherwise.
- Do not implement real audio decoding, audio analysis, stem separation,
  playback changes, mobile UI, SQLite, or streaming-service integrations in this
  spec.
- Use generated temporary files in tests. Do not add real music files.
- If a task is blocked, leave it unchecked and add a short blocker note under
  that task with the command/error and affected requirement.

## Tasks

- [x] 1. Review current repository module and contract surfaces
  - Read `core/repository` headers, implementation, and tests.
  - Read `core/contracts/schemas/repository-manifest.schema.json` and
    `core/contracts/examples/repository-manifest.stub.json`.
  - Identify whether existing repository interfaces should be expanded in place
    or supplemented with new types.
  - Document any interface compatibility concerns in implementation notes or
    comments only where needed.
  - _Requirements: 2.1, 2.2, 4.3, 6.1_
  - Implementation note: expand the current repository API in place during task
    2. `RepositoryTrack` is only used by repository tests today and is narrower
    than the manifest `trackAsset` shape, so replacing or superseding it with
    `TrackAsset` is lower-risk than carrying parallel legacy and contract types.
    `RepositoryScanResult` can be extended with scanned tracks, while
    `RepositoryError` should gain code/source context to match the manifest
    schema. No playback, DJ, desktop UI, Python, or analysis coupling was found
    in `core/repository`.

- [x] 2. Add repository data model types
  - Add C++ types for `TrackAsset`, `RepositoryError`,
    `RepositoryScanResult`, `RepositoryManifest`, `RepositorySource`, and
    `ResolvedAudioAsset` or equivalent names.
  - Keep the types in `core/repository` unless a truly shared primitive belongs
    in `core/domain`.
  - Align field names and meaning with `.codex/steering/02-core-contracts.md`.
  - Add tests for basic construction and value access.
  - _Requirements: 2.1, 2.2, 2.5, 3.5, 4.2_

- [x] 3. Implement supported audio file discovery
  - Expand `LocalAudioRepository` to accept a root folder and optional
    repository ID.
  - Recursively discover `.wav` and `.mp3` files case-insensitively.
  - Ignore unsupported files and cache directories.
  - Return deterministic ordering.
  - Add tests using temporary directories and fake file contents.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 6.4_

- [x] 4. Implement stable track IDs and source URI normalization
  - Generate stable track IDs from repository ID plus normalized relative path.
  - Use normalized forward-slash relative paths for hashing/ID generation.
  - Populate `sourceUri`, `repositoryId`, and `formatHint` on discovered
    `TrackAsset` records.
  - Add tests proving IDs remain stable across repeated scans.
  - _Requirements: 2.1, 2.2, 2.3, 2.5_

- [x] 5. Implement content hashing
  - Add a repository-local SHA-256 helper or another small dependency-free
    implementation suitable for cache invalidation.
  - Prefix content hashes with `sha256:`.
  - Return structured per-file errors when a supported file cannot be read.
  - Add tests proving hashes are stable for unchanged files and change when file
    bytes change.
  - _Requirements: 2.2, 2.4, 3.3, 3.5_

- [x] 6. Implement metadata cache path helpers
  - Add helper(s) for resolving cache root, repository manifest path, track root,
    analyzed-track path, waveform path, and stems directory.
  - Default cache root to `.autodj-cache` under the repository root unless the
    caller provides a cache root.
  - Add an explicit method for creating needed directories; path resolution
    alone should not write analysis artifacts.
  - Add tests for all expected paths.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 7. Implement repository manifest writer
  - Write `.autodj-cache/repository-manifest.json` or a caller-provided manifest
    path.
  - Include `schemaVersion`, `repositoryId`, producer provenance,
    `createdAtUtc`, source metadata, tracks, and scan summary.
  - Keep JSON output deterministic enough for tests.
  - Add tests that inspect required top-level fields and at least one track.
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 8. Implement repository manifest reader
  - Read persisted repository manifests.
  - Recover repository ID, source metadata, track list, and scan summary.
  - Return structured errors for malformed JSON, unsupported schema versions, or
    missing required fields.
  - Add manifest roundtrip and malformed-manifest tests.
  - _Requirements: 4.4, 4.5_

- [x] 9. Implement scan comparison against prior manifest
  - Compare current scan results against a previous manifest when provided.
  - Report `tracksAdded`, `tracksUpdated`, and `tracksRemoved`.
  - Treat renamed files as removed plus added.
  - Add tests for initial scan, unchanged rescan, content update, and removed
    file behavior.
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 10. Integrate repository scan, manifest, and cache flow
  - Add a high-level repository method or workflow that scans, compares with the
    prior manifest if available, and persists the new manifest.
  - Ensure missing prior manifest behaves like a first scan.
  - Ensure successful tracks are preserved when individual files produce errors.
  - Add integration tests using temporary directories.
  - _Requirements: 1.5, 3.1, 3.5, 4.1, 4.4_

- [x] 11. Preserve architectural boundaries
  - Search repository code to confirm it does not import playback, DJ strategy,
    desktop UI, or Python analysis modules.
  - Confirm repository code does not decode audio or estimate BPM/key/sections.
  - Confirm no real audio files or generated cache artifacts were added to git.
  - Document any intentional exceptions under this task before marking complete.
  - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - Implementation note: added `autodj_repository_boundaries`, a CTest CMake
    script that checks repository source/CMake files for forbidden playback, DJ,
    desktop/JUCE, Python worker, analysis-tool, process-spawn, and audio-decoder
    references. The same test also scans the repository tree for committed audio
    files and generated cache artifacts while excluding build and local tool
    directories. No intentional boundary exceptions were found.

- [x] 12. Run full verification and update task status
  - Run `cmake --preset debug`.
  - Run `cmake --build --preset debug`.
  - Run `ctest --preset debug`.
  - Run existing Python worker tests if `.venv` is available, or document the
    blocker.
  - Run `python -m autodj_analysis --help` if `.venv` is available, or document
    the blocker.
  - Update this file's checkboxes only for verified completed tasks.
  - Document any blockers with command output summaries and affected
    requirements.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  - Verification note: `cmake --preset debug` configured successfully,
    `cmake --build --preset debug` built all targets, and `ctest --preset
    debug` passed 7/7 tests including `autodj_repository_boundaries`. The local
    `.venv` was available; `.\.venv\Scripts\python -m pytest
    .\analysis\worker-python` passed 5/5 tests, and `.\.venv\Scripts\python -m
    autodj_analysis --help` completed successfully. No blockers remain.
