# Requirements Document

## Introduction

This spec improves the analysis foundation by researching, evaluating, and
selecting stronger MIR and AI/ML candidates for timing and semantic track
understanding. It is intentionally adaptive: the first tasks produce evidence,
then the requirements, design, and remaining tasks are refined around the best
candidates.

The spec is complete when BPM and beatgrid analysis remain excellent or improve
over the current AutoDJ analyzer, and semantic section analysis becomes
materially better than the current rough heuristic approach. Broader systems
such as stem-based transition rendering, set planning, transition techniques,
and hosted-provider production integration are documented for future specs but
not completed here.

Research gate outcome: the first implementation wave SHALL evaluate the current
AutoDJ signal backend, `essentia-rhythm`, `beat-this`, and `all-in-one` for
timing, and `all-in-one` plus `songformer` for semantic sections. BeatNet,
madmom-as-primary, Beat Transformer, BEAST, aubio, QM Vamp, Superpowered, stem
separation, set planning, hosted providers, cue-switch research, and
transition-generation systems remain deferred unless a later task records new
evidence and updates this spec.

## Requirement 1: Adaptive Research Gate

**User Story:** As a product owner, I want the next implementation steps to be
driven by research evidence, so the project does not lock into weak hand-rolled
algorithms prematurely.

### Acceptance Criteria

1. WHEN this spec begins THEN agents SHALL complete a thorough web research
   pass using primary sources where available.
2. WHEN research covers a candidate THEN the dossier SHALL record source links,
   claimed outputs, install path, license, platform constraints, compute cost,
   and expected AutoDJ value.
3. WHEN a candidate is rejected or deferred THEN the dossier SHALL record why.
4. WHEN research identifies future-spec candidates for set planning, transition
   techniques, stem extraction, or hosted providers THEN those candidates SHALL
   be documented even if not implemented.
5. WHEN research is incomplete THEN implementation-selection tasks SHALL remain
   unchecked and blocked rather than guessing final backends.
6. WHEN this research gate is converted into implementation work THEN the first
   wave SHALL include only `current-autodj-signal`, `essentia-rhythm`,
   `beat-this`, `all-in-one`, and `songformer` unless this document is amended
   with evidence for another candidate. Timing benchmarks SHALL include only
   candidates that emit real BPM or beatgrid outputs on real audio in the
   installed runtime.
7. WHEN a deferred candidate is mentioned by a future task THEN that task SHALL
   point back to the dossier rather than re-researching from scratch.

## Requirement 2: Candidate Backend Interfaces

**User Story:** As an analysis developer, I want BPM, beatgrid, and section
analysis behind interfaces, so candidate tools can be swapped without rewriting
batch orchestration.

### Acceptance Criteria

1. WHEN BPM candidates are implemented THEN they SHALL conform to a common
   backend contract.
2. WHEN beatgrid candidates are implemented THEN they SHALL conform to a common
   backend contract that reports beat times, confidence, provenance, and
   parameters.
3. WHEN section candidates are implemented THEN they SHALL conform to a common
   backend contract that reports section labels, boundaries, confidence,
   provenance, and parameters.
4. WHEN Rekordbox XML is used as a reference THEN it SHALL be exposed through
   the same evaluation pipeline rather than special-case scoring code.
5. WHEN batch orchestration consumes a selected backend THEN it SHALL not need
   feature-specific candidate code paths.
6. WHEN any backend emits results THEN the result SHALL include backend name,
   backend version where available, model name/version where available,
   dependency versions where practical, parameters, processing time, warnings,
   and structured failure information.
7. WHEN a backend depends on heavy optional packages or model downloads THEN
   importing the main analysis package SHALL still work without that dependency.
8. WHEN a backend requires a different audio representation THEN conversion
   SHALL be handled through a shared analysis context rather than hidden inside
   artifact composition.

## Requirement 3: Rekordbox Ground Truth Evaluation

**User Story:** As a user validating real DJ workflow behavior, I want
candidate outputs compared against Rekordbox exports, so accuracy can be judged
against known-good beatgrids and cues.

### Acceptance Criteria

1. WHEN a known song has a Rekordbox XML export THEN candidate BPM, beatgrid,
   and cue/section outputs SHALL be compared against it.
2. WHEN beatgrid comparison runs THEN it SHALL report at least BPM error,
   first-beat offset, median beat error, high-percentile beat error, and drift
   near cue points where data exists.
3. WHEN cue or section comparison runs THEN it SHALL report boundary error
   against Rekordbox memory/hot cues where a mapping is available.
4. WHEN a candidate is slower or heavier than the incumbent THEN benchmark
   output SHALL include processing time and operational notes.
5. WHEN metrics clearly show a winner THEN the result SHALL still be held for
   manual user verdict before final selection.
6. WHEN an MP3 source is benchmarked THEN the harness SHALL either normalize to
   a decoded WAV timeline or consistently apply decoder/start-time offset
   metadata so candidate and Rekordbox timelines are comparable.
7. WHEN a candidate emits downbeats or bars THEN the benchmark SHALL preserve
   those outputs for inspection even if final scoring focuses on beatgrid
   alignment.
8. WHEN a benchmark uses local user media or Rekordbox XML THEN outputs SHALL
   remain ignored local artifacts unless sanitized summary data is explicitly
   requested.

## Requirement 4: Manual Verdict Checkpoints

**User Story:** As the final judge of DJ usefulness, I want explicit pauses for
manual listening and waveform inspection, so numeric scores do not override
musical judgment.

### Acceptance Criteria

1. WHEN candidate artifacts are generated for known songs THEN the task SHALL
   stop and ask the user to inspect them in the HTML viewer or Rekordbox.
2. WHEN the user rejects a candidate despite strong numeric scores THEN the
   selection notes SHALL record that verdict and the reason if given.
3. WHEN the user approves a candidate THEN the task SHALL record the verdict,
   known caveats, and the songs inspected.
4. WHEN manual testing requires generated local artifacts THEN those artifacts
   SHALL remain outside git.

## Requirement 5: BPM And Beatgrid Outcome

**User Story:** As a DJ workflow user, I want BPM and beatgrid analysis to stay
excellent, so downstream mixing and transition planning have reliable musical
time.

### Acceptance Criteria

1. WHEN candidate BPM systems are evaluated THEN the current AutoDJ analyzer
   SHALL be included as the incumbent baseline.
2. WHEN a candidate BPM system produces worse results on known songs THEN it
   SHALL not replace the incumbent without a documented compensating benefit.
3. WHEN beatgrid candidates are evaluated THEN exact alignment and long-range
   drift SHALL be considered more important than novelty of algorithm.
4. WHEN the final BPM/beatgrid backend is selected THEN its parameters,
   provenance, confidence behavior, and limitations SHALL be documented.
5. WHEN the selected system is integrated THEN generated artifacts SHALL remain
   compatible with the current debug viewer.
6. WHEN `essentia-rhythm`, `beat-this`, or `all-in-one` fails to install or run
   in the WSL analysis environment THEN the task SHALL record a structured
   blocked/deferred reason rather than degrading the incumbent path. WHEN any
   candidate does not emit timing data on real audio, it SHALL be excluded from
   timing benchmarks instead of benchmarked as a known failure.
7. WHEN candidate grids disagree by only a few milliseconds THEN comparison
   SHALL use numeric alignment metrics and manual audio/viewer review rather
   than trusting canvas rendering alone.

## Requirement 6: Semantic Section Outcome

**User Story:** As a DJ strategy developer, I want reliable semantic sections,
so later transition planning can reason about intros, builds, drops, breaks,
and outros.

### Acceptance Criteria

1. WHEN section candidates are evaluated THEN the current heuristic section
   labeler SHALL be treated as a weak baseline, not as an architecture to
   preserve.
2. WHEN a section backend is selected THEN it SHALL support or map to labels
   useful for `intro`, `verse`, `build`, `drop`, `break`, and `outro`.
3. WHEN a candidate cannot directly emit DJ labels THEN the design SHALL define
   a defensible mapping layer or reject the candidate for this spec.
4. WHEN section confidence is weak THEN artifacts SHALL avoid fake
   high-confidence labels.
5. WHEN the selected section approach is documented THEN it SHALL include known
   failure cases and manual-test notes.
6. WHEN `all-in-one` emits pop-form labels such as chorus or bridge THEN the
   project SHALL map them to DJ labels only with supporting evidence such as
   energy, bass, onset, or phrase-boundary context.
7. WHEN `songformer` cannot be installed, loaded, or licensed clearly THEN the
   task SHALL document that blocker and continue with other section candidates.
8. WHEN a section backend cannot reliably distinguish drops from choruses or
   high-energy plateaus THEN it SHALL not emit high-confidence `drop` labels.

## Requirement 7: Documentation And Steering Updates

**User Story:** As a future agent, I want the chosen approach and deferred
research documented, so the project does not repeat the same exploration.

### Acceptance Criteria

1. WHEN the research gate completes THEN the spec dossier SHALL be updated with
   candidate decisions.
2. WHEN backend interfaces are implemented THEN relevant design docs SHALL
   explain their contracts and extension points.
3. WHEN final candidates are selected THEN README or steering docs SHALL be
   updated with the chosen analysis approach.
4. WHEN candidates are deferred to future specs THEN the roadmap or spec notes
   SHALL identify where they belong.
5. WHEN this spec completes THEN tasks.md SHALL show which adaptive gates were
   passed and which future work was intentionally deferred.

## Requirement 8: Verification

**User Story:** As a maintainer, I want repeatable validation across tests,
benchmarks, and manual checks, so analysis changes do not regress core
behavior.

### Acceptance Criteria

1. WHEN code changes are made THEN relevant Python tests SHALL pass in the WSL
   analysis environment.
2. WHEN viewer changes are made THEN the viewer script SHALL pass syntax
   verification.
3. WHEN native repository or contract behavior is touched THEN CMake configure,
   build, and CTest SHALL pass.
4. WHEN benchmark scripts are added THEN they SHALL be runnable without
   committing real music files.
5. WHEN manual verdict checkpoints are reached THEN verification notes SHALL
   include the exact artifacts the user inspected.
6. WHEN optional candidate dependencies are unavailable in CI or the local WSL
   environment THEN tests SHALL still cover contract behavior and structured
   failure paths.
7. WHEN code is not changed in a task THEN the task SHALL state that unit tests
   were not added because the change was documentation-only.
