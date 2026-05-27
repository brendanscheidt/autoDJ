# Requirements Document

## Introduction

This spec adds a DJ-grade timing branch focused on exact drop-start anchors.
The system should keep Rekordbox XML cue labels as semantic truth for now, but
AutoDJ must refine those cue timestamps onto a canonical PCM timeline and choose
the correct transient for drop-switch alignment.

The work is deliberately split into measurable stages so we can prove whether
each research-backed transform improves the audible result.

## Requirement 1: Research Synthesis And Scope Control

**User Story:** As the project owner, I want the two research reports translated
into an actionable implementation plan, so the next attempt is evidence-driven
instead of another heuristic pile.

### Acceptance Criteria

1. WHEN the spec starts THEN it SHALL summarize the useful ML and non-ML report
   findings in implementation terms.
2. WHEN a cited technique is selected THEN the design SHALL state whether it is
   used for coarse structure, local timing, feature export, or future ML.
3. WHEN a technique is deferred THEN the design SHALL state why it is not part
   of the first implementation pass.
4. WHEN Raveform or other public datasets/models are referenced THEN the design
   SHALL treat them as future training/validation sources unless locally
   installed and verified.
5. WHEN this spec conflicts with earlier roadmap sequencing THEN the tasks SHALL
   update notes to reflect that drop-anchor timing takes priority over key
   shifting.

## Requirement 2: Canonical PCM Timing Source

**User Story:** As a timing-sensitive renderer, I want every analysis and
audition path to use one decoded audio timeline, so MP3 decoder offsets do not
create hidden millisecond drift.

### Acceptance Criteria

1. WHEN a track is analyzed for timing THEN the source audio SHALL be decoded
   once into a canonical PCM artifact.
2. WHEN canonical PCM is written THEN metadata SHALL include source path,
   content hash, decoder command/backend, sample rate, channel count, duration,
   and any detected ffprobe start-time/delay metadata.
3. WHEN analysis, debug waveform, nudge, render, or audition loads audio THEN it
   SHALL prefer the canonical PCM artifact when available.
4. WHEN a path cannot use canonical PCM THEN it SHALL emit a structured warning
   identifying the non-canonical decoder path.
5. WHEN canonical PCM is used for timing THEN artifacts SHALL record the exact
   canonical audio path or artifact id.
6. WHEN canonical PCM is regenerated after source changes THEN stale artifacts
   SHALL be invalidated through content hash or parameter hash checks.

## Requirement 3: Timing-Safe Feature Extraction

**User Story:** As a beatgrid developer, I want timing features with explicit
frame alignment and sample-rate provenance, so the system does not silently shift
onsets by STFT centering or resampling.

### Acceptance Criteria

1. WHEN timing STFT or onset features are computed THEN the feature extractor
   SHALL explicitly set timing alignment behavior such as `center=False` where
   supported.
2. WHEN feature artifacts are written THEN they SHALL include sample rate,
   hop length, FFT/window size, centering mode, band definitions, and smoothing
   parameters.
3. WHEN timing features are computed THEN the default timing branch SHALL use
   at least one percussive/HPSS representation and one multiband onset
   representation.
4. WHEN low-band drop cues are scored THEN the extractor SHALL include a kick
   or low-band envelope in an EDM-relevant range.
5. WHEN onset candidates are ranked THEN the ranker SHALL be able to use
   broadband, low-band, mid/body, high/noise, and percussive evidence.
6. WHEN feature extraction fails for an optional transform THEN the report SHALL
   preserve the remaining usable features and record the missing transform.

## Requirement 4: Drop Candidate Dataset

**User Story:** As an evaluator, I want every possible drop transient candidate
exported with features and labels, so we can debug wrong picks and later train a
small ranker if needed.

### Acceptance Criteria

1. WHEN a Rekordbox XML with drop cues is provided THEN the tool SHALL generate
   drop-candidate rows around each labeled drop cue.
2. WHEN candidate rows are generated THEN each row SHALL include track id, source
   path, cue label, cue time, nearest AutoDJ beat index/time, candidate time,
   candidate offset from beatgrid, and feature values.
3. WHEN candidate rows are generated THEN they SHALL include enough candidates
   to inspect competing nearby transients, not just the selected one.
4. WHEN ground-truth labels are available THEN the report SHALL mark the nearest
   candidate to the cue/transient target separately from automatic selection.
5. WHEN exports are written THEN JSONL and a human-readable summary SHALL be
   produced.
6. WHEN the dataset is used for training later THEN the spec SHALL warn that the
   current 48 songs are too small for final model training.

## Requirement 5: Drop-Anchor Candidate Scorer

**User Story:** As the transition planner, I want a better drop transient
selector than raw nearest-peak nudge, so drop-switch transitions line up on the
true first impact of the drop.

### Acceptance Criteria

1. WHEN scoring a drop anchor THEN the scorer SHALL search around the nearest
   beatgrid beat to the semantic drop cue.
2. WHEN candidates are scored THEN score components SHALL include at least
   distance from beatgrid, percussive onset strength, low-band impact,
   pre/post energy jump, and post-candidate bass persistence.
3. WHEN optional phase/reassigned-time/correlation features are available THEN
   they SHALL be included in the report and may be included in the score after
   comparison.
4. WHEN a candidate is selected THEN the report SHALL show the selected
   candidate, runner-up candidates, component scores, confidence, and risk flags.
5. WHEN confidence is low THEN the transition planner SHALL warn, downrank, or
   require audition instead of silently trusting the anchor.
6. WHEN the new scorer performs worse than the current path THEN the default
   behavior SHALL not be changed.

## Requirement 6: Global Phase Refit Experiment

**User Story:** As a beatgrid consumer, I want any refinement to preserve a
stable grid, so fixing one drop does not break every other beat.

### Acceptance Criteria

1. WHEN a refined drop anchor is proposed THEN the system MAY produce a shadow
   beatgrid phase refit for evaluation.
2. WHEN refitting a beatgrid THEN the method SHALL preserve BPM and global phase
   continuity unless explicitly running an experimental piecewise map.
3. WHEN refitting around a drop THEN nearby strong beat candidates SHALL be used
   as support evidence, not independent snap targets.
4. WHEN the refit changes beat times THEN the report SHALL include median,
   max, and drop-anchor deltas versus the original beatgrid.
5. WHEN the refit is not clearly better in strict metrics and audition THEN it
   SHALL remain an experimental artifact, not the default analyzed-track output.

## Requirement 7: Drop-Switch Nudge Integration

**User Story:** As a listener, I want drop-switch auditions generated from
refined drop anchors, so I can tell whether this actually sounds better.

### Acceptance Criteria

1. WHEN a drop-switch MixPlan has semantic drop anchors THEN nudge post-pass
   SHALL be able to use the refined drop-anchor artifact.
2. WHEN no refined anchor exists THEN the current nudge behavior SHALL remain
   available as fallback.
3. WHEN a refined anchor changes incoming source start THEN the output report
   SHALL explain the source-time adjustment and rendered timeline effect.
4. WHEN same-BPM auditions are generated THEN they SHALL isolate anchor/nudge
   quality without tempo-stretch variables.
5. WHEN stretched auditions are generated later THEN the report SHALL verify
   that canonical PCM and tempo mapping were used consistently.

## Requirement 8: Strict Evaluation And Manual Gates

**User Story:** As the final judge of mix quality, I want strict numeric reports
and listening gates, so the system only moves forward when transitions actually
sound better.

### Acceptance Criteria

1. WHEN anchor evaluation runs THEN metrics SHALL include absolute anchor error
   in ms, drop beat offset from selected transient, candidate-rank position, and
   risk flags.
2. WHEN transition auditions are generated THEN output folders SHALL include
   importable sessions, rendered WAVs, nudge/refinement reports, and user-verdict
   placeholders.
3. WHEN a manual gate is reached THEN the task list SHALL stop and record the
   verdict before changing defaults.
4. WHEN a technique is rejected THEN notes SHALL record why, so the same dead end
   is not repeated.
5. WHEN a technique is accepted THEN steering docs SHALL record how it affects
   the analysis and DJ strategy.

