# Implementation Plan

- [x] 1. Build Rekordbox key truth importer
  - Parse `TRACK Tonality` into a separate benchmark truth table.
  - Keep truth data out of production `AnalyzedTrack.key`.
  - Add generated XML snippet tests for present, missing, and malformed
    `Tonality`.
  - Added `load_rekordbox_key_truth()` and tests proving Rekordbox Tonality is
    benchmark truth only; `apply_rekordbox_overrides()` does not copy Tonality
    into `AnalyzedTrack.key`.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 2. Add Camelot parser, mapping, and scoring utilities
  - Normalize Camelot values and map tonic/mode both directions.
  - Add exact, adjacent, relative, parallel, clash, and unknown scoring classes.
  - Cover enharmonic spelling and wheel wraparound in tests.
  - Added `key_camelot.py` with Camelot parsing, tonic/mode mapping,
    analyzed-track key artifact helper, and compatibility classification.
  - _Requirements: 2.4, 2.5, 5.2, 9.1, 9.2_

- [x] 3. Add key detector interface and result schema
  - Define detector protocol, result object, candidates, confidence, runtime,
    backend name/version, warnings, and failure behavior.
  - Ensure enabled candidates fail loudly if not installed.
  - Added `KeyDetectorBackend`, `KeyCandidate`, `KeyCandidateResult`, and key
    backend registry hooks. Non-ok key results now require a structured error,
    matching the existing timing/section backend behavior.
  - _Requirements: 2.1, 2.2, 2.3, 2.6, 9.4_

- [x] 4. Implement project-owned chroma/profile baseline
  - Compute chroma/CQT/CENS or HPCP-style pitch-class energy.
  - Add Krumhansl and at least one DJ/EDM-oriented profile family.
  - Add optional beat/section weighting hooks.
  - Test with synthetic tonal fixtures.
  - Added `autodj-chroma-profile` with Krumhansl and `edm-weighted` profiles,
    weighted time-window hooks for future section-aware analysis, and synthetic
    C-major regression coverage.
  - _Requirements: 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 9.3_

- [x] 5. Install and smoke-test Essentia key backend
  - Wire Essentia `KeyExtractor` into the detector interface.
  - Confirm it runs on at least one local MP3/WAV.
  - Record install, runtime, license, and portability notes.
  - Added `essentia-key` backend using `essentia.standard.KeyExtractor`, with
    structured unavailable/failure states, AGPL/commercial licensing note in
    provenance, and WSL smoke coverage on a generated C-major fixture.
  - _Requirements: 3.1, 3.5, 3.6_

- [x] 6. Install and smoke-test libkeyfinder/keyfinder candidate
  - Add CLI or library wrapper.
  - Confirm it runs on at least one local MP3/WAV.
  - Record GPL/commercial viability implications.
  - Built libKeyFinder `2.2.8` from source into `.venv-analysis`, installed
    the `keyfinder==1.1.0` Python binding against those headers/libs, and
    rebuilt the wheel with a venv runtime path so `keyfinder.key(...)` runs
    without extra `LD_LIBRARY_PATH` setup.
  - Added `keyfinder` backend using the Python binding, Camelot normalization,
    fixed-confidence provenance because the wrapper does not expose
    probabilities, GPL-family licensing warnings, unit coverage, and WSL smoke
    coverage on a generated WAV.
  - Real-file smoke: `autodj-chroma-profile`, `essentia-key`,
    `madmom-cnn-key`, and `keyfinder` all returned E minor / `9A` for the
    golden `ALLEYCVT - STRANGERS` MP3.
  - _Requirements: 3.3, 3.5, 3.6_

- [x] 7. Evaluate madmom CNN key recognition viability
  - Attempt a clean install in the WSL analysis environment.
  - If successful, wire it into the detector interface and smoke-test a track.
  - If not successful, document the blocker and remove it from active benchmark
    rather than leaving a placeholder.
  - Confirmed `madmom.features.key.CNNKeyRecognitionProcessor` is installed and
    runnable in WSL. Added `madmom-cnn-key` backend with 24-class probability
    parsing, Camelot normalization, and smoke coverage on a generated WAV.
  - _Requirements: 3.2, 3.5, 3.6_

- [x] 8. Stop for candidate-install verdict
  - Report which candidates are fully runnable and which are deferred.
  - Ask the user whether to proceed with benchmarking the runnable set.
  - Candidate-install verdict: all planned candidates are now fully runnable in
    WSL: `autodj-chroma-profile`, `essentia-key`, `madmom-cnn-key`, and
    `keyfinder`.
  - Key-specific subset passed: 32 tests.
  - Full worker suite passed after keyfinder wiring: 278 tests, 9 existing
    dependency/model warnings. After the benchmark CLI landed, the suite is
    281 tests with the same 9 existing warnings.
  - Next task is benchmarking these runnable candidates against Rekordbox
    `Tonality` truth only; Rekordbox key values remain excluded from production
    `AnalyzedTrack.key`.
  - _Requirements: 8.1_

- [x] 9. Implement key benchmark CLI and report writer
  - Add `benchmark-keys` or equivalent.
  - Compare candidate output against Rekordbox truth.
  - Emit aggregate metrics, per-track rows, failures, runtimes, and warnings.
  - Added `autodj-analysis benchmark-keys`, `run_key_benchmark()`,
    `load_key_benchmark_cases()`, per-track `key-candidate.json` outputs, and
    `key-benchmark-summary.json`.
  - Reports exact Camelot accuracy, compatible-key accuracy, average
    compatibility score, median confidence, processing time, and per-candidate
    mismatch lists. Rekordbox `Tonality` remains benchmark truth only.
  - Added CLI/report tests covering help output, JSON command dispatch, exact
    matches, adjacent compatible mismatches, and artifact writing.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

- [x] 10. Run first key benchmark on the labeled dubstep set
  - Benchmark all runnable candidates and baseline variants.
  - Identify common failures and whether section/beat-weighting improves EDM
    tracks.
  - Stop for the key-benchmark verdict.
  - Ran all four candidates on 48/48 scored tracks from
    `C:\Users\Brendan\Desktop\dubstep_collection_rekordbox.xml`.
  - Output:
    `.autodj-cache/key-benchmark/key-benchmark-20260522-131405/key-benchmark-summary.json`.
  - Exact Camelot results:
    `autodj-chroma-profile` 31/48 (64.6%),
    `essentia-key` 34/48 (70.8%),
    `madmom-cnn-key` 43/48 (89.6%),
    `keyfinder` 43/48 (89.6%).
  - Compatible-key results:
    `autodj-chroma-profile` 41/48 (85.4%),
    `essentia-key` 46/48 (95.8%),
    `madmom-cnn-key` 47/48 (97.9%),
    `keyfinder` 47/48 (97.9%).
  - After manual adjudication of disputed Rekordbox labels, a
    madmom/keyfinder confidence gate reached 46/48 (95.8%) and was selected in
    task 11.
  - Full worker suite after the benchmark CLI landed: 281 passed, 9 existing
    dependency/model warnings.
  - _Requirements: 8.2_

- [x] 11. Add selected detector or ensemble path
  - Record selected detector decision after user verdict.
  - Populate `AnalyzedTrack.key` from selected AutoDJ output only.
  - Preserve candidate list and ambiguity warnings.
  - Selected `selected-madmom-keyfinder` as the production AutoDJ key path for
    now: use `madmom-cnn-key` when its top-class confidence is at least `0.30`,
    otherwise fall back to `keyfinder`.
  - This matches the manually adjudicated 48-track dubstep benchmark at
    46/48 exact Camelot keys (95.8%). Known misses after manual correction are
    `They Shot To Kill` and `Lights Go Down`.
  - Normal `analyze-batch` now writes this AutoDJ-selected output into
    `AnalyzedTrack.key` with candidate list, provenance, selection parameters,
    warnings, and structured failure fallback. Rekordbox `Tonality` remains
    benchmark truth only and is not copied into production key output.
  - Added selected-backend tests plus artifact population coverage. Focused
    Python verification passed: 36 tests, 9 existing dependency/model warnings.
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [x] 12. Expose detected keys to C++ planning
  - Extend C++ track summaries with detected Camelot, tonic, mode, confidence,
    and backend provenance.
  - Add missing/known/low-confidence tests.
  - Added `AnalyzedKey` to `TrackAnalysisSummary`; the C++ artifact reader now
    parses `AnalyzedTrack.key.tonic`, `mode`, `camelot`, `confidence`, and
    `provenance.backendName/modelName`.
  - Missing key metadata is a reader warning plus `missing_key` risk flag.
    Known high-confidence keys remain clean; low-confidence keys set
    `low_key_confidence`.
  - Added C++ tests for known key parsing, backend provenance, missing key, and
    low-confidence key risk behavior.
  - _Requirements: 7.1, 9.5_

- [x] 13. Add key compatibility scoring to planning reports
  - Use detected keys to classify candidate pair compatibility.
  - Downrank clashes for drop-switch build blends when confidence is adequate.
  - Warn but do not block for reverb exits and hard cuts.
  - Add planner tests proving low-confidence keys do not hard reject.
  - Added planner-side Camelot classification for `perfect`, `relative`,
    `adjacent`, `clash`, and `unknown` compatibility.
  - Drop-switch candidates now include key compatibility reasons, downrank
    confident clashes with `camelot_key_clash_downranked`, and can prefer a
    later compatible same-BPM candidate over an earlier clash.
  - Reverb-exit candidates add `camelot_key_clash_warning` for confident
    clashes but remain eligible.
  - Low-confidence or missing keys emit `key_compatibility_unknown` and do not
    hard reject transition generation.
  - _Requirements: 7.2, 7.3, 7.4, 7.5, 7.6, 9.6_

- [x] 14. Stop for key-scored transition verdict
  - Generate a small transition candidate report using AutoDJ-detected keys.
  - Ask the user whether key scoring matches DJ intuition and which transition
    families may use hard rejection.
  - Planner output now carries the key-scored transition report inline in
    `TransitionEdge.reasons`, `riskFlags`, and `score`. The C++ tests cover
    the key-scored cases that need user audition verdicts:
    compatible drop switch, confident drop-switch clash downrank,
    compatible-over-clash candidate selection, reverb-exit clash warning, and
    low-confidence no-hard-reject behavior.
  - Current product decision: use key as a preference/scoring signal only.
    Do not hard reject drop switches on key until real audition batches confirm
    the scoring matches DJ intuition.
  - _Requirements: 8.3, 8.4_

- [x] 15. Final verification and documentation
  - Run Python tests, C++ tests, and contract validation.
  - Update steering docs with the selected detector, benchmark metrics, and
    remaining risks.
  - Document deferred candidates and future local/section-key work.
  - Updated steering/spec notes with selected detector:
    `selected-madmom-keyfinder`, madmom confidence gate `0.30`, keyfinder
    fallback, 46/48 manually adjudicated exact Camelot benchmark, and known
    misses.
  - Verification:
    `pytest analysis/worker-python/tests` passed: 287 tests, 9 existing
    dependency/model warnings.
  - Verification:
    `ctest --test-dir build/debug -C Debug --output-on-failure` passed:
    8/8 C++ tests, including contract example validation.
  - Remaining risk: libKeyFinder/keyfinder licensing still needs productization
    review before distribution; key should stay soft-scored until real
    transition auditions confirm the behavior.
  - _Requirements: 8.5, 9.7_
