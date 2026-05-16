# Requirements Document

## Introduction

This spec initializes the AutoDJ repository foundation. It converts the project
from documentation-only steering files into an executable scaffold with C++
module boundaries, a minimal desktop app target, JSON contract surfaces, a
Python analysis-worker package, and tests.

The implementation should create durable architecture surfaces without solving
the hard audio problems yet. Real DJ intelligence, real audio analysis, stem
separation, mobile UI, and streaming integrations are intentionally deferred.

## Requirement 1: Repository Foundation

**User Story:** As a project maintainer, I want a predictable repository
structure and root documentation, so future agents can start implementation from
a shared foundation.

### Acceptance Criteria

1. WHEN the spec is implemented THEN the repository SHALL contain root
   `README.md`, `.gitignore`, `CMakeLists.txt`, and `CMakePresets.json` files.
2. WHEN a future agent reads `README.md` THEN it SHALL find the MVP purpose,
   current desktop-first platform direction, C++ build commands, Python worker
   commands, and links to steering/spec documents.
3. WHEN generated artifacts are created THEN `.gitignore` SHALL exclude CMake
   build directories, Python virtual environments, Python cache files,
   `.autodj-cache/`, generated stems/waveforms, local media folders, and common
   editor/OS noise.
4. WHEN project folders are created THEN they SHALL match the target structure
   in `.codex/steering/04-project-structure.md`.

## Requirement 2: C++ Build Skeleton

**User Story:** As a C++ implementation agent, I want buildable core modules, so
domain, repository, playback, and DJ code can evolve independently.

### Acceptance Criteria

1. WHEN `cmake --preset debug` is run THEN CMake SHALL configure the project.
2. WHEN `cmake --build --preset debug` is run THEN all foundation C++ targets
   SHALL build.
3. WHEN `ctest --preset debug` is run THEN all foundation C++ tests SHALL run.
4. WHEN the C++ build is inspected THEN it SHALL expose at least these targets:
   `autodj_domain`, `autodj_repository`, `autodj_playback`, `autodj_dj`, and
   `autodj_desktop`.
5. WHEN a module depends on another module THEN dependencies SHALL follow the
   direction documented in `.codex/steering/04-project-structure.md`.

## Requirement 3: Domain Contracts In C++

**User Story:** As a core engine developer, I want basic domain types and
interfaces in place, so future modules can share stable identifiers and time
values.

### Acceptance Criteria

1. WHEN `autodj_domain` is built THEN it SHALL provide `TrackId`, `PlanId`,
   `TimelineSeconds`, and `TrackSeconds` types or equivalent strongly named
   wrappers.
2. WHEN domain tests run THEN they SHALL verify basic construction/comparison or
   value access for these types.
3. WHEN a module needs shared IDs or time values THEN it SHALL import them from
   `core/domain` rather than redefining local equivalents.

## Requirement 4: Repository Skeleton

**User Story:** As an ingestion developer, I want the local repository boundary
defined, so local file importing can be implemented without coupling to the
playback or DJ strategy layers.

### Acceptance Criteria

1. WHEN `autodj_repository` is built THEN it SHALL expose an `IAudioRepository`
   interface or equivalent abstract contract.
2. WHEN `LocalAudioRepository` is constructed THEN it SHALL not require real
   scanning behavior yet.
3. WHEN repository code is inspected THEN it SHALL not contain playback, genre,
   or DJ strategy logic.
4. WHEN repository tests run THEN they SHALL verify the skeleton can be
   constructed and queried for basic placeholder state.

## Requirement 5: Playback Skeleton

**User Story:** As a playback developer, I want a dumb playback engine surface,
so future work can execute `MixPlan` timelines without genre-specific logic.

### Acceptance Criteria

1. WHEN `autodj_playback` is built THEN it SHALL expose a `PlaybackEngine`
   skeleton.
2. WHEN the playback API is inspected THEN it SHALL include `loadPlan`, `play`,
   `pause`, `stop`, `seek`, and `getState` methods or equivalent.
3. WHEN `loadPlan` is called with a trivial placeholder plan THEN it SHALL
   return a structured validation result.
4. WHEN playback code is inspected THEN it SHALL not contain dubstep-specific
   rules, audio-analysis code, or repository scanning logic.

## Requirement 6: DJ Strategy Skeleton

**User Story:** As a strategy developer, I want a DJ strategy interface and
dubstep placeholder, so the real Dubstep DJ can be implemented behind a stable
contract.

### Acceptance Criteria

1. WHEN `autodj_dj` is built THEN it SHALL expose an `IDJStrategy` interface or
   equivalent abstract contract.
2. WHEN `DubstepDJStrategy` is constructed THEN it SHALL report support for the
   `dubstep` genre.
3. WHEN the placeholder strategy generates a plan THEN it SHALL return an empty
   or fixture-backed `MixPlan` placeholder without trying to analyze audio.
4. WHEN DJ code is inspected THEN it SHALL not render audio or access local
   files directly.

## Requirement 7: Desktop App Placeholder

**User Story:** As a user or developer, I want a minimal desktop app shell, so
future UI work has a visible workbench target.

### Acceptance Criteria

1. WHEN `autodj_desktop` is built THEN it SHALL produce a desktop app target.
2. WHEN the app launches THEN it SHALL open a window.
3. WHEN the window is viewed THEN it SHALL show a basic app title and
   placeholders for repository, analysis, mix plan, and playback areas.
4. WHEN app code is inspected THEN core business logic SHALL remain in core
   modules, not in UI components.

## Requirement 8: Contract Schemas And Fixtures

**User Story:** As a cross-language implementation agent, I want JSON schemas
and examples, so C++ and Python modules can share artifact shapes.

### Acceptance Criteria

1. WHEN contract files are inspected THEN the repository SHALL contain schemas
   for analyzed tracks, mix plans, and repository manifests.
2. WHEN examples are inspected THEN each schema SHALL have at least one stub
   example JSON artifact.
3. WHEN schema top-level fields are inspected THEN they SHALL include the
   relevant IDs, `schemaVersion`, source/provenance, and placeholder arrays
   documented in `.codex/steering/02-core-contracts.md`.
4. WHEN the schemas are extended later THEN they SHALL remain versioned and
   compatible with the documented contract-first workflow.

## Requirement 9: Python Analysis Worker Stub

**User Story:** As an analysis developer, I want a Python CLI package scaffold,
so real analysis libraries can be added later behind a stable process boundary.

### Acceptance Criteria

1. WHEN the Python package is installed in editable mode THEN import
   `autodj_analysis` SHALL succeed.
2. WHEN `python -m autodj_analysis --help` is run THEN the CLI SHALL print usage
   information.
3. WHEN `python -m autodj_analysis classify <audio-path>` is run THEN it SHALL
   emit a JSON `GenreVerdict` with `primaryGenre` equal to `dubstep`.
4. WHEN `python -m autodj_analysis analyze <audio-path> --out <output-dir>` is
   run THEN it SHALL write `analyzed-track.json` with stub provenance and
   placeholder confidence values.
5. WHEN Python tests run THEN they SHALL verify genre classification, CLI
   analyze output, and expected top-level JSON keys.
6. WHEN analysis code is inspected THEN it SHALL not include heavy Essentia,
   librosa, madmom, Demucs, or FFmpeg integration in this spec.

## Requirement 10: Verification And Documentation

**User Story:** As a future task executor, I want clear verification commands,
so each completed task can be checked consistently.

### Acceptance Criteria

1. WHEN implementation completes THEN the documented C++ configure/build/test
   commands SHALL either pass or have an explicit blocker documented.
2. WHEN implementation completes THEN the documented Python install/test/CLI
   commands SHALL either pass or have an explicit blocker documented.
3. WHEN a task is completed THEN `tasks.md` SHALL be updated to mark only the
   completed verified work.
4. WHEN a blocker occurs THEN the implementation notes SHALL identify the
   command, error, affected requirement, and recommended next action.

