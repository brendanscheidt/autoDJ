# Requirements Document

## Introduction

This spec builds the first barebones AutoDJ mixing proof of concept. It uses
the selected Spec 005 analysis metadata to generate and execute a deterministic
`MixPlan` for two core dubstep transition situations:

- second-build drop switch;
- drop-end reverb exit.

The spec is successful when the project can produce an audible or otherwise
auditionable transition artifact that the user can judge, and when failures are
traceable to either analysis metadata, transition strategy, or playback
execution.

## Requirement 1: MixPlan Contract Supports POC Transitions

**User Story:** As a playback developer, I want the `MixPlan` contract to
represent the planned transitions precisely, so generated plans can be
validated and executed deterministically.

### Acceptance Criteria

1. WHEN a plan represents a two-track transition THEN it SHALL include track
   placements, transition edges, deck commands, automation commands, and debug
   annotations.
2. WHEN a second-build drop switch is represented THEN the plan SHALL include
   aligned source/timeline starts for both tracks, the calculated measure count
   to the aligned drop, and volume/crossfade automation that leaves the incoming
   track alone at the drop.
3. WHEN a drop-end reverb exit is represented THEN the plan SHALL include
   low-EQ reduction, reverb wet automation, outgoing dry-volume fade to 0,
   incoming low-EQ restoration, and CDJ-style post-fader reverb-tail fadeout
   commands.
4. WHEN automation is emitted THEN all keyframes SHALL be timeline-based and
   deck-specific unless the control is intentionally global.
5. WHEN a generated plan cannot express required playback behavior using the
   current schema THEN the schema SHALL be extended in a backward-compatible
   way and the example fixture SHALL be updated.
6. WHEN schema changes are made THEN contract examples and validation tests
   SHALL be updated.

## Requirement 2: Deterministic Playback Scheduling

**User Story:** As a listener, I want the engine to execute plan timing exactly,
so transitions land on beat and phrase boundaries.

### Acceptance Criteria

1. WHEN a valid `MixPlan` is loaded THEN the playback engine SHALL parse,
   validate, and store ordered deck commands.
2. WHEN transport is playing THEN the engine SHALL expose the active command
   state at any timeline time.
3. WHEN seeking occurs THEN deck state and automation state SHALL be recomputed
   from the plan instead of incrementally guessed.
4. WHEN multiple commands share a timestamp THEN execution order SHALL be
   deterministic.
5. WHEN a command references an unknown placement, track, deck, or invalid time
   THEN plan validation SHALL return structured errors.
6. WHEN a plan is invalid THEN playback SHALL not start.

## Requirement 3: Second-Build Drop Switch Planner

**User Story:** As the AutoDJ strategy, I want to switch from song A's second
build into song B's first drop, so the listener hears a natural build blend
followed by song B's drop at the expected song A drop moment.

### Acceptance Criteria

1. WHEN `song_a` has at least two ordered build/drop pairs, `song_b` has a
   first build/drop pair, and both tracks have exactly equal normalized BPM
   values THEN the planner SHOULD choose the second-build drop switch template.
2. WHEN the template is chosen THEN the planner SHALL calculate the number of
   measures between `song_a` build 2 start and `song_a` drop 2 start.
3. WHEN `song_b` is started THEN its source start SHOULD be the same measure
   count before `song_b` drop 1 start, clamped only when the source would be
   before the track start.
4. WHEN the transition reaches two measures before the aligned drop THEN
   `song_a` volume SHALL be 0 or effectively silent.
5. WHEN the aligned drop arrives THEN `song_b` SHALL be the only full-volume
   dry signal unless a later task explicitly enables doubles.
6. WHEN required sections have low confidence or impossible timing THEN the
   planner SHALL reject this template and record why.
7. WHEN multiple incoming candidates are available THEN the planner SHALL scan
   for a valid exact-normalized-BPM drop-switch candidate before falling back
   to the drop-end reverb exit template.
8. WHEN normalized BPM values differ by any amount THEN the planner SHALL
   reject the second-build drop switch template for that pair and record a
   `bpm_mismatch_for_drop_switch` reason.

## Requirement 4: Drop-End Reverb Exit Planner

**User Story:** As the AutoDJ strategy, I want a safe fallback when song A lacks
a second build/drop pair, so the system can exit the current drop musically and
restart from song B.

### Acceptance Criteria

1. WHEN `song_a` lacks a usable second build/drop pair but has a usable drop
   end THEN the planner SHOULD choose the drop-end reverb exit template.
2. WHEN the template is chosen THEN low-EQ reduction and reverb ramp on
   `song_a` SHALL begin eight measures before the outgoing drop end whenever
   enough drop duration exists.
3. WHEN the final measure begins THEN `song_a` dry volume SHALL fade to 0 and
   reverb wet SHALL ramp to 100%.
4. WHEN the drop-end beat arrives THEN `song_b` SHALL start from the first
   beatgrid beat after initial silence with low EQ at 0.
5. WHEN four measures after `song_b` start have elapsed THEN `song_b` low EQ
   SHALL be restored to 100% and `song_a` reverb tail SHALL be 0.
6. WHEN the drop is too short for the full eight-measure ramp THEN the planner
   SHALL clamp the ramp safely and record a risk flag.

## Requirement 5: Analysis Metadata Consumption

**User Story:** As the strategy, I want to consume selected analysis artifacts
without hidden Rekordbox truth, so POC plans reflect real runtime behavior.

### Acceptance Criteria

1. WHEN the planner reads analysis data THEN it SHALL consume
   `analyzed-track.json` artifacts produced by the selected Spec 005 stack.
2. WHEN measuring bars or measures THEN the planner SHALL use the beatgrid and
   assume 4 beats per measure for the MVP.
3. WHEN drop/build sections are missing THEN cue points may be used as fallback
   only if they came from the analyzer artifact, not Rekordbox XML.
4. WHEN Rekordbox XML is used during this spec THEN it SHALL be used only for
   manual comparison or optional evaluation, never for runtime plan generation.
5. WHEN analysis confidence is low THEN generated plans SHALL use simpler
   templates or include risk flags.

## Requirement 6: Audition And Debug Review

**User Story:** As the product owner, I want to hear and inspect generated
transitions, so I can decide whether the POC behavior is musically useful.

### Acceptance Criteria

1. WHEN a transition plan is generated THEN local audition artifacts SHALL be
   written under ignored paths.
2. WHEN an audition artifact is generated THEN it SHALL include the input
   `MixPlan`, a readable debug summary, and an offline rendered WAV preview
   with audible volume, low-EQ, and simple CDJ-style post-fader reverb-tail
   behavior.
3. WHEN the first transition artifacts are ready THEN development SHALL stop
   for manual user audition before expanding templates.
4. WHEN the user gives a verdict THEN the verdict SHALL be recorded in
   `tasks.md` with exact artifact paths and inspected songs.
5. WHEN a transition sounds wrong THEN debug notes SHALL make it clear whether
   the problem came from analysis metadata, plan generation, command
   scheduling, or audio rendering.

## Requirement 7: Verification

**User Story:** As a maintainer, I want repeatable tests across contracts,
planner logic, and playback scheduling, so the POC remains deterministic.

### Acceptance Criteria

1. WHEN contract schema changes are made THEN contract examples SHALL validate.
2. WHEN C++ playback or DJ strategy code changes THEN CMake configure, build,
   and CTest SHALL pass.
3. WHEN Python helper scripts are added THEN focused WSL Python tests SHALL
   pass.
4. WHEN generated local artifacts are created THEN they SHALL remain ignored
   and out of git.
5. WHEN a task is documentation-only THEN the task SHALL state that no tests
   were added because no runtime behavior changed.
