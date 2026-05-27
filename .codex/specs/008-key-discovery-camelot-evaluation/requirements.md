# Requirements Document

## Introduction

This spec builds AutoDJ's own key detection pipeline. Rekordbox XML
`TRACK Tonality` values are used as ground truth for evaluation, not as the
production key source. The spec is successful when local detector candidates can
be run, compared honestly against Rekordbox-labeled dubstep tracks, and the
best detector or ensemble can populate `AnalyzedTrack.key` for downstream
planning.

## Requirement 1: Rekordbox Truth Table Import

**User Story:** As an evaluator, I want to load Rekordbox Camelot labels as
truth data, so AutoDJ can score its own key detector outputs.

### Acceptance Criteria

1. WHEN a Rekordbox XML `TRACK` has a non-empty `Tonality` attribute THEN the
   benchmark importer SHALL parse it as ground-truth Camelot metadata.
2. WHEN `Tonality` is missing or malformed THEN the benchmark importer SHALL
   mark that track as unscored for key and record a structured warning.
3. WHEN truth data is imported THEN it SHALL be stored separately from
   production `AnalyzedTrack.key` detector output.
4. WHEN an analyzed artifact is produced without key detection THEN Rekordbox
   truth SHALL NOT be copied into the artifact as if AutoDJ detected it.
5. WHEN a benchmark report is written THEN it SHALL include the truth source XML
   path or digest and the number of scored/unscored tracks.

## Requirement 2: Candidate Key Detector Interface

**User Story:** As an engineer, I want all key detector backends behind one
interface, so we can compare libraries and ML models without changing the
analysis pipeline each time.

### Acceptance Criteria

1. WHEN a detector backend runs THEN it SHALL emit normalized tonic, mode,
   Camelot, confidence, backend name, backend version when available, and
   processing time.
2. WHEN a detector cannot run THEN the benchmark SHALL fail that candidate
   explicitly rather than silently counting it as a graceful empty result.
3. WHEN multiple detectors are configured THEN they SHALL run through the same
   input audio decode path unless a backend requires its own loader.
4. WHEN a detector emits only tonic/mode THEN AutoDJ SHALL map it to Camelot
   before evaluation.
5. WHEN a detector emits only Camelot THEN AutoDJ SHALL map it to tonic/mode
   before artifact export.
6. WHEN detector output is low confidence or ambiguous THEN that uncertainty
   SHALL be preserved in candidates and reports.

## Requirement 3: Runnable Candidate Backends

**User Story:** As the project owner, I want each selected candidate to be fully
installed and smoke-tested before benchmarking, so we do not waste time on fake
comparisons.

### Acceptance Criteria

1. WHEN Essentia is selected THEN its key extractor backend SHALL run on at
   least one local MP3/WAV and produce key, scale, and confidence/strength.
2. WHEN madmom CNN key recognition is selected THEN its model files and runtime
   SHALL be installed or the candidate SHALL be removed from the benchmark with
   documented reason.
3. WHEN libkeyfinder or keyfinder CLI is selected THEN the binary/library SHALL
   run locally and produce a key on a smoke-test track.
4. WHEN librosa chroma/profile detection is selected THEN the project-owned
   implementation SHALL run with at least two profile families.
5. WHEN a candidate has license, platform, or install constraints THEN the
   benchmark report SHALL record those constraints.
6. WHEN a candidate cannot realistically ship or be ported later THEN it MAY
   still be benchmarked as a reference, but it SHALL be labeled comparison-only.

## Requirement 4: Project-Owned Baseline Detector

**User Story:** As a future mobile/native engineer, I want at least one
project-owned chroma/profile key detector, so AutoDJ has a portable fallback
even if third-party libraries are not viable.

### Acceptance Criteria

1. WHEN the baseline detector runs THEN it SHALL compute chroma or HPCP-style
   pitch-class energy from decoded audio.
2. WHEN evaluating key profiles THEN it SHALL support at least Krumhansl and one
   EDM/DJ-oriented profile family such as Shaath or Faraldo.
3. WHEN beatgrid metadata is available THEN the detector SHOULD support
   beat-weighted or section-weighted aggregation as an experimental option.
4. WHEN drop/build/verse sections are available THEN the detector SHOULD allow
   excluding noisy intros/outros or overweighting stable harmonic regions.
5. WHEN the baseline outputs confidence THEN it SHALL be calibrated from score
   separation between top candidates, not a hard-coded constant.
6. WHEN results are benchmarked THEN baseline variants SHALL be listed
   separately so tuning choices are visible.

## Requirement 5: Benchmark Metrics And Reports

**User Story:** As the user, I want a clear report showing which detector agrees
with Rekordbox and where it fails, so we can decide whether it is good enough
for harmonic planning.

### Acceptance Criteria

1. WHEN a detector is benchmarked THEN the report SHALL include exact accuracy.
2. WHEN a detector is benchmarked THEN the report SHALL include Camelot
   adjacent, relative, parallel, and other/miss categories.
3. WHEN a detector is benchmarked THEN the report SHALL include DJ-usable
   compatibility accuracy separately from strict exact accuracy.
4. WHEN a detector predicts enharmonic spellings differently THEN evaluation
   SHALL normalize spellings before scoring.
5. WHEN a detector is slow THEN the report SHALL include median and p95
   processing time per track.
6. WHEN tracks fail detection THEN the report SHALL list track IDs, reasons,
   and whether the failure came from decode, runtime, or detector output.
7. WHEN a benchmark completes THEN it SHALL write per-track rows with truth,
   predicted key, confidence, error class, and candidate rankings.

## Requirement 6: Detector Selection And Artifact Population

**User Story:** As the planner, I want `AnalyzedTrack.key` populated by the
selected AutoDJ detector or ensemble, so transition decisions use our own
metadata rather than Rekordbox truth.

### Acceptance Criteria

1. WHEN candidate benchmarks are reviewed THEN a selected detector or ensemble
   SHALL be recorded in documentation before becoming the default.
2. WHEN the selected detector runs during normal analysis THEN it SHALL populate
   `AnalyzedTrack.key` from AutoDJ output only.
3. WHEN Rekordbox truth exists during benchmarking THEN it MAY be stored in
   benchmark reports, but SHALL NOT overwrite selected detector output.
4. WHEN multiple detector candidates agree THEN the selected ensemble MAY raise
   confidence.
5. WHEN top candidates disagree by distant Camelot keys THEN the selected
   ensemble SHALL lower confidence or emit an ambiguity warning.
6. WHEN confidence is below the planning threshold THEN key compatibility SHALL
   be a soft preference or warning, not a hard rejection.

## Requirement 7: Planning Integration

**User Story:** As the DJ strategy, I want detected key compatibility to guide
transition choice, so musically clashing blends are downranked when the detector
is trustworthy.

### Acceptance Criteria

1. WHEN C++ loads an analyzed-track artifact THEN it SHALL read detected
   Camelot key, tonic, mode, confidence, and backend provenance.
2. WHEN two detected keys are compared THEN the compatibility class SHALL be one
   of perfect, relative, adjacent, parallel, clash, or unknown.
3. WHEN a second-build drop switch has harmonic overlap THEN the planner SHOULD
   prefer compatible detected-key candidates over clashes when exact BPM and
   semantic requirements are otherwise valid.
4. WHEN the selected transition is a reverb exit or hard cut THEN a key clash
   SHALL warn but not block by default.
5. WHEN detector confidence is low THEN the planner SHALL annotate
   `low_key_confidence` and avoid hard rejection.
6. WHEN MixPlan annotations are emitted THEN they SHOULD include detected keys,
   compatibility class, score, and whether key affected selection.

## Requirement 8: Manual Review Gates

**User Story:** As the project owner, I want to approve detector accuracy and
planning behavior before it becomes a hard gate, so the system does not reject
good mixes based on bad key analysis.

### Acceptance Criteria

1. WHEN candidate install smoke tests finish THEN execution SHALL pause for a
   candidate-install verdict.
2. WHEN the first full benchmark finishes THEN execution SHALL pause for a
   key-benchmark verdict.
3. WHEN key-scored transition reports are generated THEN execution SHALL pause
   for user audition before strict key rejections are enabled.
4. WHEN the user rejects a detector selection THEN the default SHALL remain
   unknown/soft-key mode until another candidate is approved.
5. WHEN manual verdicts are recorded THEN tasks and steering docs SHALL capture
   the selected path and remaining risks.

## Requirement 9: Tests And Regression Coverage

**User Story:** As an engineer, I want key detection and scoring behavior tested
at the Python, contract, and C++ layers, so changes do not silently corrupt
planning decisions.

### Acceptance Criteria

1. WHEN Camelot parser tests run THEN they SHALL cover valid, lowercase,
   whitespace-padded, malformed, and out-of-range values.
2. WHEN benchmark scoring tests run THEN they SHALL cover exact, adjacent,
   relative, parallel, clash, unknown, and enharmonic cases.
3. WHEN baseline detector tests run THEN they SHALL verify deterministic output
   on generated synthetic tonal fixtures.
4. WHEN candidate smoke tests run THEN they SHALL fail loudly if an enabled
   backend is not installed.
5. WHEN C++ summary tests run THEN they SHALL verify detected-key loading and
   missing-key states.
6. WHEN planner tests run THEN they SHALL verify that key can downrank but not
   hard reject when confidence is low.
7. WHEN contract validation runs THEN existing analyzed-track fixtures SHALL
   remain valid.
