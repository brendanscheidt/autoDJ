# Requirements Document

## Introduction

This spec adds pitch-preserving tempo control to AutoDJ. The engine and offline
renderer should be able to play a track at a target BPM while preserving pitch,
and the Dubstep DJ planner should use that capability to consider more
transition candidates than exact native-BPM pairs.

Rekordbox Master Tempo is a quality reference, not an implementation dependency.

## Requirement 1: Time-Stretch Candidate Research And Smoke Tests

**User Story:** As an evaluator, I want realistic time-stretch libraries tested
honestly, so AutoDJ chooses a backend based on audible quality and integration
risk.

### Acceptance Criteria

1. WHEN candidate research is recorded THEN it SHALL include Rubber Band,
   SoundTouch, Signalsmith Stretch, Superpowered, zplane elastique, and any
   other serious candidate considered.
2. WHEN public Rekordbox behavior is documented THEN it SHALL state that Master
   Tempo changes playback speed while preserving pitch, but the internal
   algorithm is not publicly disclosed.
3. WHEN a candidate is selected for local testing THEN it SHALL be installed or
   built before benchmarking, not left as a placeholder.
4. WHEN a candidate cannot be run because of licensing, SDK access, or platform
   constraints THEN the report SHALL mark it deferred or comparison-only.
5. WHEN smoke tests run THEN each runnable backend SHALL stretch at least one
   real or generated WAV and produce a playable output.
6. WHEN candidate results are reported THEN they SHALL include quality notes,
   processing time, license constraints, and future mobile/native viability.

## Requirement 2: Tempo-Stretch Backend Interface

**User Story:** As an engineer, I want tempo stretching behind a stable
interface, so the selected backend can be swapped without rewriting planner or
renderer logic.

### Acceptance Criteria

1. WHEN a backend runs THEN it SHALL accept source audio, source BPM, target
   BPM or stretch ratio, sample rate, and preserve-pitch intent.
2. WHEN a backend completes THEN it SHALL emit stretched audio plus provenance:
   backend name, version when available, ratio, source BPM, target BPM, runtime,
   and warnings.
3. WHEN a backend cannot satisfy a requested ratio THEN it SHALL fail loudly
   with a structured error instead of silently rendering wrong-speed audio.
4. WHEN a backend has quality modes THEN the selected mode SHALL be recorded in
   output metadata.
5. WHEN multiple backends exist THEN the CLI SHALL be able to select the backend
   explicitly for benchmarking.
6. WHEN no backend is available THEN planner/rendering SHALL report that tempo
   matching is unavailable and fall back to existing non-stretched behavior.

## Requirement 3: MixPlan Tempo Contract

**User Story:** As a planner, I want MixPlans to express target BPM and tempo
ramps, so playback can align different native BPM tracks deterministically.

### Acceptance Criteria

1. WHEN a deck is tempo-stretched THEN the MixPlan SHALL express the deck's
   source/native BPM and target effective BPM or ratio.
2. WHEN tempo changes over time THEN the MixPlan SHALL express tempo automation
   with deterministic keyframes.
3. WHEN pitch should be preserved THEN the MixPlan SHALL explicitly carry a
   preserve-pitch or Master-Tempo-style flag.
4. WHEN a tempo control is unsupported by a renderer/backend THEN validation
   SHALL warn or reject before rendering.
5. WHEN an existing non-stretched MixPlan is loaded THEN it SHALL remain valid.
6. WHEN transition annotations are emitted THEN they SHALL include source BPM,
   target BPM, BPM delta, stretch ratio, and backend.

## Requirement 4: Offline Renderer Tempo Support

**User Story:** As the user, I want rendered WAV auditions to reflect tempo
matched playback, so I can hear whether stretched drop switches are usable.

### Acceptance Criteria

1. WHEN the renderer sees a deck target BPM different from source BPM THEN it
   SHALL tempo-stretch audio before existing EQ/effects/volume automation.
2. WHEN tempo-stretching changes source timeline mapping THEN deck source-time
   calculations SHALL stay deterministic.
3. WHEN rendered audio is stretched THEN beat markers used for alignment SHALL
   map to their effective stretched timeline positions.
4. WHEN transient nudge runs after stretching THEN it SHALL compare the
   stretched incoming transient against the outgoing transition anchor.
5. WHEN rendering completes THEN the summary SHALL include stretch provenance
   and any quality warnings.
6. WHEN rendering is compared to a no-stretch fallback THEN output folders SHALL
   make it obvious which backend/ratio produced each WAV.

## Requirement 5: Planner BPM Eligibility Gate

**User Story:** As a DJ strategy, I want tempo matching to expand candidate
choices without allowing absurd stretch decisions, so generated transitions
sound intentional.

### Acceptance Criteria

1. WHEN planner candidate generation runs THEN `maxTempoAdjustmentBpmPerDeck`
   SHALL default to `10.0` and be configurable.
2. WHEN two tracks differ by no more than twice the per-deck adjustment window
   THEN the planner MAY choose a shared transition BPM between them.
3. WHEN a track would need more than the per-deck adjustment window THEN that
   candidate SHALL be rejected for automatic planning unless the user overrides
   the gate.
4. WHEN a drop switch is selected THEN both decks SHALL have exact equal
   effective BPM at the overlap/drop anchor.
5. WHEN the currently playing outgoing deck changes BPM before a transition
   THEN the plan SHALL use an explicit tempo ramp and annotate the set-tempo
   drift.
6. WHEN the planner rejects a candidate due to tempo range THEN the rejection
   reason SHALL include source BPMs, requested target BPM, and configured gate.

## Requirement 6: Beatgrid And Nudge Integrity

**User Story:** As a listener, I want stretched transitions to stay beat-locked,
so tempo matching does not reintroduce drift or transient flams.

### Acceptance Criteria

1. WHEN a beatgrid is stretched to a target BPM THEN beat intervals SHALL match
   the effective target BPM within test tolerance.
2. WHEN the incoming track is stretched and nudged THEN the nudge SHALL shift
   source/placement timing consistently with the stretched timeline.
3. WHEN a stretched drop switch is rendered THEN the aligned drop anchors SHALL
   occur at the same output timeline sample within tolerance.
4. WHEN beatgrid confidence is low THEN tempo-matched drop switches SHALL be
   downranked or rejected.
5. WHEN stretch quality appears poor through diagnostics THEN the planner SHALL
   warn or fall back to a simpler transition.

## Requirement 7: Audition And Quality Reports

**User Story:** As the project owner, I want to hear and inspect stretched
transitions before enabling them broadly, so bad DSP quality does not poison the
planner.

### Acceptance Criteria

1. WHEN audition batches are generated THEN they SHALL include multiple BPM
   deltas, including small, medium, and near-gate cases.
2. WHEN possible THEN each tested pair SHALL include unstretched and stretched
   comparison renders.
3. WHEN a report is written THEN it SHALL include runtime, ratio, transient
   alignment diagnostics, clipping/headroom notes, and user-audition verdict
   fields.
4. WHEN a backend sounds bad on dense dubstep THEN it SHALL not become the
   default even if it passes synthetic tests.
5. WHEN user verdicts are recorded THEN tasks and steering docs SHALL capture
   the selected backend and acceptable BPM window.

## Requirement 8: Spec 010 Boundary For Key Shifting

**User Story:** As a product planner, I want key shifting separated from tempo
stretching, so each fundamental DJ tool can be tested and accepted on its own.

### Acceptance Criteria

1. WHEN Spec 009 is implemented THEN it SHALL not add planner-side key shifting.
2. WHEN a chosen backend also supports pitch shifting THEN the design SHALL
   record that capability for Spec 010.
3. WHEN MixPlan fields are added for tempo control THEN they SHOULD avoid
   blocking future pitch-shift fields.
4. WHEN the roadmap is updated THEN the immediate follow-on SHALL be a
   pitch/key-shift spec that changes key without changing BPM.

