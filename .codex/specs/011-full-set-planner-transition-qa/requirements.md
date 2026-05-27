# Requirements Document

## Introduction

This spec turns the current full-set POC into an explainable planning and QA
workflow. The system should plan sets from existing analyzed tracks, generate
transition previews, validate plan safety, and only then render a full WAV.

## Requirement 1: Planner Inputs And Configuration

**User Story:** As the project owner, I want set generation controlled by clear
inputs and knobs, so I can run repeatable auditions without editing scripts.

### Acceptance Criteria

1. WHEN planning a set THEN the tool SHALL accept an analysis root, audio root,
   output root/run name, track count, random seed, and candidate count limits.
2. WHEN planning drop switches THEN the tool SHALL use Rekordbox-derived
   semantic sections, selected key output, BPM/beatgrid artifacts, and the
   selected nudge path.
3. WHEN tempo stretching is allowed THEN the tool SHALL enforce a configurable
   maximum BPM adjustment and record every stretched placement.
4. WHEN no compatible drop switch exists THEN the tool SHALL consider wash-out
   fallback candidates.
5. WHEN configuration is omitted THEN defaults SHALL match the current accepted
   POC behavior.

## Requirement 2: Candidate Scoring And Set-Level Policy

**User Story:** As a listener, I want the planner to choose songs that make a
musical set, not just the first valid transition.

### Acceptance Criteria

1. WHEN candidate transitions are scored THEN the score SHALL include transition
   type, Camelot compatibility, BPM/stretch cost, nudge confidence, energy/gain
   compatibility, semantic confidence, and recent transition history.
2. WHEN multiple candidates are valid THEN the planner SHALL prefer higher
   scores but retain deterministic behavior for a given seed.
3. WHEN wash-outs are used THEN the planner SHALL avoid long runs of wash-outs
   when drop-switch alternatives exist.
4. WHEN artist/title metadata is available THEN the planner SHOULD avoid
   immediate repeated artists or near-duplicate tracks.
5. WHEN a candidate is rejected THEN the report SHALL include a structured
   rejection code and message.
6. WHEN no candidate can satisfy normal policy THEN the tool SHALL fail or use a
   clearly marked emergency fallback, depending on configuration.

## Requirement 3: MixPlan State Validation

**User Story:** As a renderer user, I want bad deck state caught before a long
render, so stale tracks or FX cannot leak into the output.

### Acceptance Criteria

1. WHEN a full-set MixPlan is generated THEN validation SHALL confirm outgoing
   placements do not extend past their stop command.
2. WHEN a drop-switch transition is generated THEN validation SHALL confirm the
   drop-switch window contains no positive reverb, reverb-tail, or echo
   automation on active decks.
3. WHEN a wash-out transition is generated THEN validation SHALL confirm incoming
   deck volume/EQ starts at full-band defaults and outgoing reverb wet/tail
   behavior is bounded.
4. WHEN a deck is reused THEN validation SHALL confirm relevant controls are
   reset before the new placement starts.
5. WHEN a plan includes tempo stretching THEN validation SHALL confirm the
   offline renderer supports the tempo plan shape.
6. WHEN validation fails THEN full rendering SHALL not run.

## Requirement 4: Transition Preview Pack

**User Story:** As a reviewer, I want short WAVs around each transition, so I
can judge transition quality without listening through a full set.

### Acceptance Criteria

1. WHEN a set plan is generated THEN the tool SHALL optionally render one preview
   WAV per transition.
2. WHEN rendering previews THEN each preview SHALL include configurable seconds
   or bars before and after the transition.
3. WHEN preview WAVs are written THEN each SHALL have a matching JSON summary
   with source tracks, transition type, timing anchors, nudge values, tempo
   stretch details, key compatibility, and warnings.
4. WHEN a preview cannot be rendered THEN the report SHALL keep planning results
   and mark only that preview as failed.
5. WHEN previews are generated THEN an index file SHALL list all previews in set
   order for manual listening.

## Requirement 5: Full-Set Report

**User Story:** As a planner debugger, I want one report that explains the set,
so I can tell whether a bad transition came from analysis, scoring, or rendering.

### Acceptance Criteria

1. WHEN planning completes THEN the tool SHALL write a full-set summary JSON.
2. WHEN writing the summary THEN it SHALL include set sequence, transition type
   counts, wash-out run lengths, stretched transition counts, key classes,
   nudge/confidence ranges, energy verdicts, validation results, and artifact
   paths.
3. WHEN candidate searches are performed THEN the report SHALL include accepted
   candidate details and top rejection reasons.
4. WHEN rendering completes THEN the report SHALL link render summary and trace
   artifacts.
5. WHEN a manual verdict is recorded later THEN the report format SHALL support
   adding user verdict metadata without changing generated plan data.

## Requirement 6: CLI Or Tool Promotion

**User Story:** As a developer, I want the full-set generator to be a supported
entry point, so it is not a fragile one-off script.

### Acceptance Criteria

1. WHEN this spec completes THEN there SHALL be a documented command for full-set
   planning.
2. WHEN the command runs THEN it SHALL support plan-only, preview-only,
   render-only-from-existing-plan, and full plan-preview-render modes.
3. WHEN an existing analysis root is provided THEN the command SHALL not rerun
   analysis.
4. WHEN artifacts are generated THEN all outputs SHALL be under a run-specific
   ignored cache folder.
5. WHEN command help is printed THEN it SHALL explain required folders and common
   options.

## Requirement 7: Manual Gates And Documentation

**User Story:** As the project owner, I want the workflow documented and gated by
listening verdicts, so development does not drift away from audible quality.

### Acceptance Criteria

1. WHEN a preview pack is generated THEN the task SHALL stop for user audition
   before marking preview acceptance complete.
2. WHEN a full WAV is generated THEN the task SHALL stop for user verdict before
   marking full-set acceptance complete.
3. WHEN the user rejects a transition pattern THEN the tasks SHALL record the
   concrete failure and artifact path.
4. WHEN the accepted workflow changes THEN steering docs and runbooks SHALL be
   updated.

