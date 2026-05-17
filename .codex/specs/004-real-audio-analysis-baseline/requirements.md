# Requirements Document

## Introduction

This spec continues Phase 3 by replacing low-confidence musical placeholders
with the first real, library-based analysis outputs. The Python worker will run
inside a WSL/Linux Python 3.11 analysis environment for MIR dependencies while
the native Windows C++/JUCE build remains the app verification environment.
Python is a POC/reference analysis runtime, not the assumed final offline mobile
runtime.

The implementation should rely heavily on best-in-class Python/MIR libraries to
find accurate algorithms and backend combinations. It should produce waveform,
energy, onset, tempo, beat-grid, rough section, and cue candidate data that are
useful for future DJ strategy work, but it must keep confidence values honest,
compare candidate outputs, and document the path toward a future C++ or
mobile-safe native implementation.

## Requirement 1: WSL/Linux Analysis Runtime

**User Story:** As a developer, I want a repeatable Linux Python 3.11 analysis
environment, so MIR libraries can be evaluated and used without native Windows
compatibility blocking the worker.

### Acceptance Criteria

1. WHEN implementation begins THEN setup instructions SHALL verify WSL is
   installed and an Ubuntu distribution is available.
2. WHEN the analysis environment is created THEN it SHALL use Python 3.11.
3. WHEN Python 3.11 is unavailable in WSL THEN the task SHALL document the
   blocker and the exact command output before proceeding to library work.
4. WHEN the WSL analysis environment is verified THEN it SHALL not replace or
   invalidate the native Windows C++/JUCE verification path.
5. WHEN environment artifacts such as WSL virtualenvs are created THEN they
   SHALL be ignored by git.

## Requirement 2: Analysis Dependency Extras And Library Survey

**User Story:** As an analysis developer, I want MIR dependencies installed
through explicit optional extras, so base worker tests remain lightweight while
advanced analysis is reproducible.

### Acceptance Criteria

1. WHEN analysis extras are installed THEN NumPy, SciPy, librosa, SoundFile, and
   any required audio loading support SHALL be importable.
2. WHEN the WSL analysis extras are installed THEN Essentia SHALL be importable
   or the task SHALL be marked blocked with exact install output.
3. WHEN native Windows runs the base worker tests THEN it SHALL not require
   Essentia to be installed.
4. WHEN an optional analysis dependency is unavailable at runtime THEN the
   worker SHALL return an actionable structured error instead of an import stack
   trace for expected failures.
5. WHEN dependency policy tests are updated THEN they SHALL allow only the
   approved analysis dependencies and continue to reject unrelated heavy
   dependencies such as Demucs unless a future spec permits them.
6. WHEN this spec evaluates candidate libraries THEN it SHALL record each
   candidate's feature role, installability, license, platform constraints, and
   expected POC value.
7. WHEN a candidate library is promising for BPM, beat grid, downbeats,
   structure, key, or cue extraction THEN it SHALL be smoke-tested or explicitly
   deferred with a reason.
8. WHEN multiple libraries can produce the same feature THEN tests or reports
   SHALL compare their outputs on generated fixtures where practical.
9. WHEN a candidate has licensing or mobile-portability risk THEN that risk
   SHALL be documented before the backend is treated as product-critical.

## Requirement 3: Generated Audio Fixtures

**User Story:** As a maintainer, I want deterministic synthetic audio fixtures,
so baseline analysis can be tested without committing commercial music.

### Acceptance Criteria

1. WHEN tests need audio inputs THEN they SHALL generate temporary WAV fixtures
   at test time.
2. WHEN fixture helpers generate click tracks THEN they SHALL support known 70
   BPM and 140 BPM patterns.
3. WHEN fixture helpers generate energy ramps THEN they SHALL create known
   low-energy and high-energy regions suitable for section/cue tests.
4. WHEN generated audio files are produced THEN they SHALL remain in temporary
   directories or ignored manual-test locations.
5. WHEN git candidate paths are scanned THEN no real audio, generated cache, or
   fixture output files SHALL be committable by accident.

## Requirement 4: Library-Based Audio Loading

**User Story:** As an analysis worker, I want a library-based audio decoding
boundary, so later analysis algorithms do not depend directly on ffprobe
container metadata.

### Acceptance Criteria

1. WHEN a supported local WAV file is loaded THEN the worker SHALL produce mono
   floating-point PCM samples and a sample rate.
2. WHEN a supported local MP3 file is loaded and dependencies support it THEN
   the worker SHALL produce mono floating-point PCM samples and a sample rate.
3. WHEN a source cannot be decoded THEN the worker SHALL return a per-track
   `audio_decode_error` or similarly structured error.
4. WHEN loading succeeds THEN duration seconds SHALL be derived from decoded
   samples or trusted metadata and remain consistent with the analyzed artifact.
5. WHEN the audio loading implementation changes THEN batch orchestration SHALL
   continue to depend on a small internal interface rather than specific library
   calls spread through the codebase.

## Requirement 5: Waveform Artifact

**User Story:** As a future UI and debugging surface, I want a cached waveform
overview, so track shape can be inspected without re-decoding audio.

### Acceptance Criteria

1. WHEN a track is analyzed successfully THEN the worker SHALL write
   `<cache-root>/tracks/<track-id>/waveform.json`.
2. WHEN waveform generation runs THEN the artifact SHALL include track ID,
   analyzer provenance, source content hash, duration seconds, analysis sample
   rate, and parameters.
3. WHEN waveform overview points are written THEN they SHALL be signal-derived
   and bounded to a stable, documented point count or time resolution.
4. WHEN the waveform artifact is stale or missing THEN the batch worker SHALL
   rewrite it.
5. WHEN the analyzed-track artifact is fresh but the waveform artifact is stale
   THEN the batch worker SHALL not falsely report the whole track as skipped.

## Requirement 6: Energy And Onset Analysis

**User Story:** As a DJ strategy developer, I want energy and onset curves, so
future section and transition logic has real signal features.

### Acceptance Criteria

1. WHEN a track is analyzed successfully THEN `AnalyzedTrack.energy.globalEnergy`
   SHALL be signal-derived.
2. WHEN a track is analyzed successfully THEN `energy.curve` SHALL contain
   time/value points derived from RMS or comparable frame energy.
3. WHEN bass energy can be estimated from the decoded signal THEN
   `energy.bassEnergyCurve` SHALL contain low-frequency energy points.
4. WHEN onset strength can be estimated THEN `energy.onsetDensityCurve` SHALL
   contain time/value points derived from onset strength or onset density.
5. WHEN confidence is weak or an estimate is coarse THEN quality warnings SHALL
   describe the limitation.

## Requirement 7: Tempo And Beat Grid Baseline

**User Story:** As a future dubstep strategy, I want baseline BPM and beat
markers, so transition logic can start reasoning in musical time.

### Acceptance Criteria

1. WHEN a generated 140 BPM click fixture is analyzed THEN the worker SHALL
   produce a plausible BPM near 140 and beat markers near expected click times.
2. WHEN a generated 70 BPM halftime fixture is analyzed THEN the worker SHALL
   normalize tempo consistently for dubstep-style 70/140 reasoning.
3. WHEN BPM confidence is weak THEN `tempo.confidence` and
   `beatGrid.confidence` SHALL remain low and quality warnings SHALL explain
   the weakness.
4. WHEN beat markers are emitted THEN they SHALL include stable indexes,
   `timeSeconds`, and confidence where available.
5. WHEN downbeats are not defensible THEN the worker SHALL leave downbeats empty
   or low-confidence rather than fabricating phrase structure.

## Requirement 8: Rough Section And Cue Candidate Baseline

**User Story:** As a future transition planner, I want conservative section and
cue candidates, so generated plans can later choose safer mix points.

### Acceptance Criteria

1. WHEN a synthetic energy-ramp fixture is analyzed THEN the worker SHALL
   identify at least one defensible rough section or cue candidate.
2. WHEN section candidates are emitted THEN they SHALL include type, start/end
   seconds, and confidence.
3. WHEN cue candidates are emitted THEN they SHALL include type, time seconds,
   and confidence.
4. WHEN section or cue evidence is weak THEN the worker SHALL prefer empty
   arrays or low-confidence `unknown` sections over fake high-confidence labels.
5. WHEN quality warnings are inspected THEN they SHALL distinguish rough
   heuristic section/cue analysis from production-grade structure detection.

## Requirement 9: Batch Integration And Cache Invalidation

**User Story:** As a user, I want the existing batch command to produce richer
analysis without losing skip/rewrite behavior.

### Acceptance Criteria

1. WHEN `analyze-batch` runs on a repository manifest THEN it SHALL still
   process every possible track and report analyzed, skipped, failed, and total
   counts.
2. WHEN the analyzer version or parameters hash changes for real analysis THEN
   existing ffprobe-only artifacts SHALL be rewritten.
3. WHEN `--force` is passed THEN analyzed-track and waveform artifacts SHALL be
   rewritten.
4. WHEN one track fails decode or analysis THEN other tracks in the same batch
   SHALL still be analyzed or skipped.
5. WHEN `--json` is provided THEN the summary SHALL remain parseable and include
   enough information to diagnose dependency/decode/analysis failures.

## Requirement 10: Documentation And Manual Checkpoints

**User Story:** As a developer testing real songs, I want clear manual
checkpoints, so I can report whether baseline analysis is musically plausible.

### Acceptance Criteria

1. WHEN this spec is implemented THEN README SHALL describe spec 003 as complete
   and spec 004 as the current real-analysis baseline.
2. WHEN this spec is implemented THEN README or spec docs SHALL include WSL
   setup and Python 3.11 analysis environment commands.
3. WHEN this spec is implemented THEN docs SHALL include a generated-fixture
   verification command.
4. WHEN this spec is implemented THEN docs SHALL include a manual known-song
   checklist for BPM, energy curve, and cue/section plausibility.
5. WHEN docs mention generated artifacts THEN they SHALL continue to warn not to
   commit local media or generated cache artifacts.

## Requirement 11: Verification

**User Story:** As a future task executor, I want repeatable verification across
Windows and WSL, so analysis improvements do not regress existing foundations.

### Acceptance Criteria

1. WHEN implementation completes THEN native Windows Python worker tests SHALL
   pass for the supported base test set.
2. WHEN implementation completes THEN WSL Python analysis tests SHALL pass with
   analysis dependencies installed.
3. WHEN implementation completes THEN `python -m autodj_analysis --help` SHALL
   pass.
4. WHEN implementation completes THEN `python -m autodj_analysis analyze-batch
   --help` SHALL pass.
5. WHEN implementation completes THEN `cmake --preset debug` SHALL configure.
6. WHEN implementation completes THEN `cmake --build --preset debug` SHALL build
   all C++ targets.
7. WHEN implementation completes THEN `ctest --preset debug` SHALL pass all C++
   tests.
8. WHEN a task is completed THEN `tasks.md` SHALL be updated to mark only the
   completed verified work.

## Requirement 12: POC Reference Analyzer And Future Native Portability

**User Story:** As a future mobile implementer, I want the Python analysis POC
to capture portable behavior and not just opaque library calls, so the winning
analysis approach can later be ported, licensed, or replaced for full offline
mobile use.

### Acceptance Criteria

1. WHEN Python libraries are used for POC analysis THEN the implementation SHALL
   record backend identity, version, parameters, and relevant model names in
   provenance or developer documentation.
2. WHEN a feature family is implemented THEN docs or task notes SHALL classify
   its future native portability as easy, moderate, hard, or licensing-dependent.
3. WHEN a library output becomes part of `AnalyzedTrack` THEN generated fixture
   tests SHALL define expected behavior that a future native implementation can
   compare against.
4. WHEN a library is copyleft, model-restricted, or commercially licensed THEN
   the spec SHALL avoid copying its implementation into closed-source native
   code without a future licensing decision.
5. WHEN the POC produces strong real-song results THEN the selected algorithm
   combination SHALL be documented as a candidate for either C++ reimplementation
   or native/commercial licensing.
