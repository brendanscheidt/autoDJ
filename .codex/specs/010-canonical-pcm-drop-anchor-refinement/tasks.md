# Implementation Plan

## Execution Rules

- Before starting any task, read `kiro.json`, `requirements.md`, `design.md`,
  and the required steering docs listed in `kiro.json`.
- Treat Rekordbox XML cue labels as semantic/evaluation truth for this spec,
  not as an automatic production dependency.
- Do not train a final ML model on the current 48-track set.
- Do not overwrite the current working nudge path until the new path passes a
  manual audition gate.
- Do not independently snap every beat in a beatgrid.
- Keep all generated PCM, feature stores, datasets, audition WAVs, and debug
  exports under ignored local cache folders.
- Stop at manual gates and record the user's verdict before marking the gated
  tasks complete.

## Tasks

- [x] 1. Finalize research synthesis and reprioritization notes
  - Record the useful takeaways from both research reports in this spec folder.
  - Note that Spec 010 is now timing/drop-anchor refinement and key shifting is
    pushed later.
  - Add links to verified reference pages for all-in-one MP3 offsets, Raveform,
    librosa onset centering, HPSS, reassigned spectrogram, aubio onset methods,
    and madmom DBN beat tracking.
  - Update roadmap notes if needed.
  - Completion notes, 2026-05-22:
    - Added `research-synthesis.md` with selected and deferred techniques from
      the ML and classical DSP reports.
    - Verified and recorded public references for all-in-one MP3 decoder
      offsets, Raveform, librosa onset centering, HPSS, reassigned
      spectrograms, aubio onset modes, and madmom DBN beat tracking.
    - Reprioritized roadmap/tech-stack notes so Spec 010 is canonical
      PCM/drop-anchor timing refinement; pitch/key shifting moves behind this
      work.
    - The current 48-song set is recorded as regression/audition data, not a
      final ML training set.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 2. Audit current timing-sensitive audio loading paths
  - Identify every path that decodes audio for analysis, debug waveform, nudge,
    render, tempo stretch, key analysis, and audition.
  - Record current sample rates, decoder libraries, centering behavior, and
    provenance gaps.
  - Flag direct `librosa.load`, `soundfile.read`, or ffmpeg paths that need to
    prefer canonical PCM.
  - Add a short audit document under this spec folder.
  - Completion notes, 2026-05-22:
    - Added `timing-audit.md` covering batch analysis, current signal backend,
      debug waveform, semantic backend WAV export, All-In-One, SongFormer,
      CUE-DETR, nudge, renderer, tempo stretch, and key analysis paths.
    - Confirmed the main mismatch: incumbent signal analysis/debug paths often
      run at `22050 Hz`, while render/nudge paths use `44100 Hz` and may decode
      source MP3s independently.
    - Flagged `librosa.onset_strength` calls that do not explicitly set
      `center=False` for future timing-safe feature extraction.
    - Conclusion: canonical PCM must come before more nudge-constant tuning.
  - _Requirements: 2.3, 2.4, 3.1, 3.2_

- [x] 3. Implement canonical PCM cache artifacts
  - Add a Python module for canonical audio creation and metadata.
  - Decode sources with one canonical FFmpeg command.
  - Write `canonical-audio.json` metadata and `canonical.wav`.
  - Include source hash, decoder details, sample rate, channels, duration, and
    timeline policy.
  - Add tests for missing source, stale hash, unsupported extension, and stable
    output paths.
  - Completion notes, 2026-05-22:
    - Added `autodj_analysis.canonical_audio` with canonical per-track paths,
      `CanonicalAudioOptions`, `CanonicalAudioResult`, and structured
      `CanonicalAudioError`.
    - Canonical artifacts are written as mono PCM WAV plus
      `canonical-audio.json` metadata under `<out>/tracks/<track-id>/`.
    - Metadata includes source path/URI, actual source SHA-256, FFmpeg version
      and command, ffprobe metadata when available, sample rate, channel count,
      duration, parameters hash, and `shared-canonical-pcm` timeline policy.
    - Fresh artifacts are skipped by source hash and parameters hash; changed
      source content regenerates the canonical WAV.
    - Added manifest batch helper that writes `canonical-audio-summary.json`.
    - Focused verification:
      WSL `pytest analysis/worker-python/tests/test_canonical_audio.py -q`
      -> 5 passed.
  - _Requirements: 2.1, 2.2, 2.5, 2.6_

- [x] 4. Add canonical PCM CLI and cache integration
  - Add `autodj-analysis canonicalize-audio`.
  - Make batch analysis optionally use canonical PCM as the audio source.
  - Make debug waveform, nudge, and render report whether they used canonical
    PCM or a non-canonical fallback.
  - Stop for `canonical-pcm-verdict`.
  - Progress notes, 2026-05-22:
    - Added `autodj-analysis canonicalize-audio` with `--ffmpeg`,
      `--ffprobe`, `--force`, `--sample-rate`, `--fallback-sample-rate`, and
      `--json`.
    - Added opt-in `analyze-batch --canonical-audio-root`; signal analysis uses
      `<canonical-root>/tracks/<track-id>/canonical.wav` and fails loudly if
      the requested canonical PCM is missing.
    - `analyze-batch` artifacts now record canonical analysis-audio provenance
      under `source.providerMetadata.autodjAnalysisAudio` when that opt-in path
      is used.
    - Canonical analysis adds `+canonical-pcm-v1` to the effective parameters
      hash so older non-canonical artifacts are not accidentally treated as
      fresh.
    - Debug waveform artifacts now include `source.audioPath` and
      `source.timelinePolicy`; CLI JSON includes `sourceTimelinePolicy`.
    - `nudge-mixplan` summaries now include per-track audio source provenance
      and timeline policy.
    - `render-mixplan` summaries now include `audioSources` with source path,
      tempo-cache key, canonical/direct timeline policy, and tempo-stretch
      status.
    - Real gate run generated under
      `.autodj-cache/spec010-canonical-pcm-gate/run-20260522-234358`.
    - Gate subset: `alleycvt-strangers-spotisaver`,
      `ydg-let-s-go-back-spotisaver`, `whales-healing-spotisaver`, and
      `skrillex-voltage-spotisaver`.
    - `canonicalize-audio`, direct `analyze-batch`, canonical
      `analyze-batch`, and canonical debug waveform all completed with `ok`.
    - Comparison report:
      `.autodj-cache/spec010-canonical-pcm-gate/run-20260522-234358/canonical-pcm-comparison.json`.
    - BPM stayed stable on all four tracks; canonical beatgrid shifted earlier
      by a consistent per-track amount versus direct MP3 analysis
      (`-7 ms`, `-8 ms`, or `-13 ms` on the tested tracks).
    - Follow-up Rekordbox timing report:
      `.autodj-cache/spec010-canonical-pcm-gate/run-20260522-234358/canonical-vs-direct-rekordbox-timing.json`.
    - Rekordbox comparison quantified that canonical PCM is currently farther
      from Rekordbox beat/cue truth by the same offset amount (`+7 ms`,
      `+8 ms`, or `+13 ms` median/p95 error versus direct analysis on the
      tested tracks).
    - Verdict implication: canonical PCM artifact plumbing works, but the
      current FFmpeg canonical timeline should not be approved as more correct
      until we either preserve Rekordbox/source timeline offset or explicitly
      translate Rekordbox truth into canonical timeline.
    - Final verdict, 2026-05-24: canonical artifact plumbing is useful and can
      remain available, but canonical PCM is not the accepted timing source for
      the current drop-switch pipeline. The accepted audition path preserves
      the existing AutoDJ analysis timeline and uses raw transient nudge.
      Reopening canonical timing as a default requires a new manual gate.
  - _Requirements: 2.3, 2.4, 2.5_

- [x] 5. Build timing-safe feature extractor
  - Add `autodj_analysis.timing_features`.
  - Compute HPSS/percussive features.
  - Compute low, mid/body, high/noise, and broadband onset envelopes.
  - Explicitly set timing STFT/onset centering behavior.
  - Record hop length, FFT/window size, centering mode, smoothing, and band
    definitions.
  - Add tests with synthetic impulses proving frame timestamps are not silently
    shifted.
  - Completion notes, 2026-05-24:
    - Closed as deferred for the accepted POC path. The broader
      timing-feature extractor was not implemented because manual audition
      proved that the trusted path is Rekordbox semantic truth plus the
      existing AutoDJ BPM/beatgrid/key artifacts and raw transient nudge.
    - Future semantic/drop-anchor research should create this module before
      replacing the accepted raw nudge path, but it is no longer a blocker for
      this spec.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 6. Add optional advanced timing features behind flags
  - Add onset backtracking candidate support.
  - Add reassigned-time candidate correction if stable on synthetic fixtures.
  - Add local matched-filter or cross-correlation features around candidate
    windows.
  - Keep optional features non-fatal and report missing dependencies or unstable
    outputs.
  - Progress notes, 2026-05-23:
    - Added `autodj_analysis.drop_wall` as an exploratory drop-wall detector
      focused on the visible Rekordbox-style envelope edge: broadband jump,
      low-band jump, wall derivative, post-wall sustain, and proximity to the
      approximate beat/cue.
    - Added `autodj-analysis drop-wall-debug` to write both a JSON artifact
      and an SVG visual overlay.
    - Added a preferred-window selector so a strong candidate near the
      beat/cue can beat a farther pre-drop wall/fill.
    - Synthetic verification passed and real debug artifacts were generated
      under `.autodj-cache/spec010-drop-wall-debug/run-20260523-000618`.
    - First real outputs:
      `STRANGERS` drop 2 selected `172.135034s` (`-25.966 ms` from Rekordbox
      cue); `YDG - Let's Go Back` drop 1 selected `52.963107s` (`-52.893 ms`)
      while preserving the earlier stronger pre-drop walls as visible
      runner-up candidates for inspection.
    - Added a machine-readable `riskProfile` to drop-wall artifacts and the
      SVG debug table. The profile emits precision verdicts, risk flags,
      allowed transition families, and booleans such as `dropSwitchSafe` and
      `layeredDropSafe`.
    - Current policy treats far semantic offsets, ambiguous competing walls,
      weak wall edges, weak low-band arrivals, and weak post-wall sustain as
      reasons to route away from precision/layered drop transitions.
    - Final verdict, 2026-05-24: drop-wall/advanced timing features are
      research artifacts only. They are not used in the accepted transition
      pipeline because the manually auditioned refined-anchor path regressed
      several known-good transitions.
  - _Requirements: 3.6, 5.3_

- [x] 7. Export drop-anchor candidate dataset
  - Add `autodj-analysis export-drop-candidates`.
  - Parse Rekordbox XML drop cues and map each cue to nearest AutoDJ beatgrid
    beat.
  - Generate all transient candidates in a configurable window around each
    labeled drop.
  - Write JSONL rows and a human-readable summary.
  - Include selected/raw current nudge candidate where available for comparison.
  - Stop for `drop-candidate-feature-verdict`.
  - Completion notes, 2026-05-24:
    - Closed as deferred. The candidate-dataset path is still the right shape
      for future supervised semantic/drop-anchor work, but the current project
      decision is to use Rekordbox semantic cue labels for section truth and
      continue building transition intelligence around that modular boundary.
    - No final model-training dataset should be created from the current
      48-track set alone.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [x] 8. Implement deterministic drop-anchor scorer v1
  - Rank drop candidates using grid proximity, percussive onset, low-band jump,
    pre/post energy jump, bass persistence, and candidate ambiguity.
  - Emit selected candidate, runner-ups, score components, confidence, and risk
    flags.
  - Add config or named constants for score weights.
  - Add tests for synthetic candidate windows and known pathological cases.
  - Completion notes, 2026-05-24:
    - Closed as rejected for the current default path. The deterministic
      drop-wall/anchor scoring experiments were not reliable enough to replace
      raw nudge after manual listening.
    - If this is revisited, it should run as a shadow report with explicit
      risk flags and should not mutate MixPlans until a new audition gate
      approves it.
  - _Requirements: 5.1, 5.2, 5.4, 5.5_

- [x] 9. Benchmark scorer against current raw nudge behavior
  - Run the scorer on the 48-track Rekordbox-labeled set.
  - Compare selected anchors to current raw nudge candidates.
  - Report median, 95th-percentile, and worst-case anchor error in ms.
  - Identify improved, unchanged, and regressed tracks.
  - Do not change defaults if the scorer regresses known good pairs.
  - Completion notes, 2026-05-24:
    - Manual benchmark verdict selected current raw nudge over refined-anchor
      scoring. The refined path was materially worse or riskier on known-good
      pairs, so defaults were not changed.
    - The trusted regression evidence is the guarded Rekordbox-semantic batch
      plus the later 10-pair raw-nudge batch documented in Tasks 12-13.
  - _Requirements: 5.6, 8.1, 8.4_

- [x] 10. Produce shadow beatgrid phase refit artifacts
  - Use refined drop anchors to produce an experimental shadow beatgrid phase
    fit around drops.
  - Preserve BPM and global continuity.
  - Report deltas versus original beatgrid.
  - Keep this artifact experimental until accepted by metrics and audition.
  - Progress notes, 2026-05-23:
    - Added `autodj_analysis.beatgrid_phase` as an experimental post-pass
      that keeps the current BPM/beat spacing but shifts the whole beatgrid
      phase from accepted drop-wall anchors.
    - Added `autodj-analysis refine-beatgrid-phase` with explicit
      `--anchor-time` support plus automatic drop cuePoint fallback.
    - Reports include each anchor's semantic time, nearest original beat,
      selected wall, phase correction, score, and consensus status.
    - Refined artifacts preserve the original analyzed-track shape and add
      `beatGrid.phaseRefinement` metadata; semantic cue/section beat indices
      are recalculated against the shifted grid.
    - Generated smoke artifacts under
      `.autodj-cache/spec010-beatgrid-phase-refinement/smoke-20260523-111316`
      with metronome WAVs around STRANGERS, YDG, Shockwave,
      Lights Go Down, Dead Instinct, Alarma, Healing, and VOLTAGE anchors.
    - Current smoke run used one accepted drop anchor per artifact for manual
      listening; multi-anchor consensus remains available but should be
      auditioned before default use.
    - Phase-refinement reports now propagate each anchor's drop-wall
      `riskProfile` and emit aggregate `transitionRecommendations`. Refined
      analyzed-track artifacts store those recommendations under
      `beatGrid.phaseRefinement.transitionRecommendations` so downstream
      planners can avoid risky drop switches without re-running wall
      detection.
    - Final verdict, 2026-05-24: phase-refit artifacts are exploratory only
      and must not be used by the final drop-switch pipeline. The accepted
      path preserves the existing beatgrid and applies raw source-start nudge
      to the incoming track for the transition.
    - Focused verification:
      WSL `pytest analysis/worker-python/tests/test_drop_wall.py analysis/worker-python/tests/test_beatgrid_phase.py -q`
      -> 5 passed.
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 11. Integrate refined anchors into drop-switch nudge comparison mode
  - Allow `nudge-mixplan` to consume refined drop-anchor artifacts.
  - Preserve current nudge as fallback.
  - In comparison mode, emit old and refined nudge calculations side by side.
  - Ensure source-time adjustments are explained in `nudge-summary.json`.
  - Progress notes, 2026-05-23:
    - Added `nudge-mixplan --refined-anchor-report <report.json>` for
      consuming one or more beatgrid phase-refinement reports.
    - Added `--use-refined-anchors`; without this flag, raw transient nudge
      remains the selected/default path and refined anchors are emitted for
      comparison only.
    - Refined-anchor nudge math uses the refined selected wall as the actual
      transient offset relative to the existing MixPlan source anchor. It does
      not replace the MixPlan source anchor directly, which avoids canceling
      the timing correction.
    - `nudge-summary.json` now includes `selectedAnchorMode` plus a
      `refinedAnchorComparison` object with raw and refined anchor nudges side
      by side.
    - Nudge annotations now include the anchor mode used, e.g.
      `fromDropStart->toDropStart/raw=...ms`.
    - `tools/run-transition-audition-batch.ps1` now has
      `-CompareRefinedAnchors` to generate/pass phase-refinement reports into
      `nudge-mixplan`, and `-UseRefinedAnchors` to explicitly apply that path
      for audition batches. Default batch behavior remains raw nudge.
    - Focused verification:
      WSL `pytest analysis/worker-python/tests/test_drop_wall.py analysis/worker-python/tests/test_beatgrid_phase.py analysis/worker-python/tests/test_mixplan_nudge.py analysis/worker-python/tests/test_cli.py -q`
      -> 49 passed.
    - PowerShell syntax check passed for
      `tools/run-transition-audition-batch.ps1`.
    - Real comparison smoke batch generated under
      `.autodj-cache/transition-auditions/spec010-refined-anchor-comparison-20260523-211344`.
    - The smoke batch created 2 drop-switch renders and sessions while leaving
      `selectedAnchorMode=raw`; both `nudge-summary.json` files contain one raw
      and one refined anchor calculation for comparison.
    - First smoke results: the refined path was materially different from raw
      and carried risk flags on both transitions, so the current default should
      remain raw nudge until a larger audition proves otherwise.
    - Remaining gated decision is covered by Tasks 12-13 before switching any
      default transition path to refined anchors.
    - Final cleanup, 2026-05-24: after the larger audition verdict rejected
      refined anchors for the accepted path, the public `nudge-mixplan` CLI and
      transition-audition batch script stopped exposing refined-anchor switches.
      The accepted nudge command is raw transient nudge only.
  - _Requirements: 7.1, 7.2, 7.3_

- [x] 12. Generate same-BPM drop-switch audition batch
  - Generate auditions using same-native-BPM pairs first.
  - Include importable desktop app sessions, rendered WAVs, and reports.
  - Include regression pairs that previously sounded perfect and known failures.
  - Stop for `drop-anchor-audition-verdict`.
  - Progress notes, 2026-05-23:
    - Pre-task smoke batch for refined-anchor comparison was generated under
      `.autodj-cache/transition-auditions/spec010-refined-anchor-comparison-20260523-211344`.
    - This was intentionally small: 2 same-BPM drop switches, importable
      sessions, rendered WAVs, gain reports, and `nudge-summary.json` files
      with raw/refined comparisons.
    - Not enough for `drop-anchor-audition-verdict`; a larger regression batch
      still needs to include known-good and known-failure pairs.
    - Added
      `.codex/specs/010-canonical-pcm-drop-anchor-refinement/drop-switch-regression-pairs.json`
      with 10 intended same-BPM regression pairs covering the golden pair,
      prior clean generations, dense/stress tracks, and known bad-alignment
      pairs.
    - Added `-DropSwitchPairListPath` to
      `tools/run-transition-audition-batch.ps1` so fixed regression pairs can
      be generated deterministically from JSON or CSV.
    - Real regression batch generated under
      `.autodj-cache/transition-auditions/spec010-drop-switch-regression-20260523-212444`.
    - Batch result: 8/10 drop-switch auditions rendered with importable
      sessions. Two intended pairs were rejected by the planner because the
      semantic section confidence was too low for the drop-switch template.
    - All 8 rendered plans used `selectedAnchorMode=raw`; refined anchor
      comparisons were recorded in each `nudge-summary.json`.
    - Refined anchors were mostly worse or riskier in this batch. Examples:
      golden `STRANGERS -> YDG` raw `+49.549 ms` versus refined `-59.883 ms`
      with refined risk flags; `Calcium Chillin -> Jawbreaker` raw `-7.919 ms`
      versus refined `-121.729 ms` with far/unsafe refined-anchor flags.
    - Current evidence says the raw nudge path should remain the audition
      default; refined-anchor reports are useful as risk/debug evidence, not as
      the active path yet.
    - User verdict on the first regression batch was strongly negative. Root
      cause investigation found the batch used the older automatic-semantic
      analysis root, so the planner was aligning incorrect build/drop sections
      before transient nudge ran. Example: the STRANGERS/YDG plan used
      STRANGERS drop at about 92.7s instead of the hand-labeled drop 2 near
      172.1s.
    - Added `autodj-analysis apply-rekordbox-semantics` so future roots can
      apply only Rekordbox semantic labels while preserving AutoDJ BPM,
      beatgrid, and key analysis. This avoids accidentally using
      `apply-rekordbox-xml`, which intentionally replaces the timing grid too.
    - Added `-RequireRekordboxSemanticTruth` to
      `tools/run-transition-audition-batch.ps1` so fixed-pair truth auditions
      fail fast if analyzed-track artifacts do not carry
      `source.providerMetadata.rekordboxSemanticXml`.
    - Shortened transition folder names in
      `tools/run-transition-audition-batch.ps1` to avoid Windows path-length
      failures when long track IDs cause planner debug files to exceed the
      path limit.
    - Corrected semantic-truth analysis root generated under
      `.autodj-cache/transition-auditions/rekordbox-semantic-truth-20260523-214112`.
      It preserves AutoDJ BPM/beatgrid/key and replaces only
      `sections`/`cuePoints` from
      `C:\Users\Brendan\Desktop\dubstep_collection_rekordbox.xml`.
    - Guarded five-pair regression batch generated under
      `.autodj-cache/transition-auditions/s10-truth-fixed-final-20260523-215344`.
      It produced 5/5 drop-switch renders and importable desktop sessions using
      `-RequireRekordboxSemanticTruth`.
    - Corrected nudge summaries were materially different from the invalid
      batch: STRANGERS/YDG used the hand-labeled second build/drop and needed
      only `+0.7 ms` nudge with `risk=none`.
    - Stop here for `drop-anchor-audition-verdict`: user should import/listen
      to the sessions under the guarded corrected batch and decide whether raw
      nudge remains acceptable for drop switches.
  - _Requirements: 7.4, 8.2, 8.3_

- [x] 13. Decide default behavior from audition verdict
  - If refined anchors beat or equal the current path, switch the drop-switch
    batch path to use them by default.
  - If refined anchors are mixed, keep them as candidate reports and use risk
    flags for manual review.
  - If refined anchors are worse, document the dead end and keep current nudge.
  - Record the user's verdict and exact folders auditioned.
  - Progress notes, 2026-05-24:
    - User verdict on the guarded corrected five-pair batch was that the
      sessions "sound much better." This confirms the bad previous audition
      was caused by the wrong semantic source, not by raw transient nudge.
    - Final decision path for drop-switch auditions is:
      Rekordbox semantic labels only -> AutoDJ BPM/beatgrid/key preserved ->
      key/tempo-compatible pair selection -> raw transient nudge -> gain
      planning -> render/session export.
    - Refined anchors and beatgrid phase refit remain experimental only. They
      are not active unless `-CompareRefinedAnchors`/`-UseRefinedAnchors` are
      explicitly passed; neither switch should be used in the trusted
      drop-switch decision pipeline.
    - Generated a guarded 10-pair drop-switch batch under
      `.autodj-cache/transition-auditions/s10-truth-dropswitch-10-20260524-091330`
      using `-RequireRekordboxSemanticTruth` and no refined-anchor switches.
    - Batch result: 10/10 drop-switch renders and importable sessions. Run
      summary confirmed `requireRekordboxSemanticTruth=true`,
      `compareRefinedAnchors=false`, and `useRefinedAnchors=false`; every
      `nudge-summary.json` reported `selectedAnchorMode=raw`.
  - _Requirements: 5.6, 8.3, 8.4, 8.5_

- [x] 14. Update docs, steering, and runbooks
  - Update analysis steering with canonical PCM policy.
  - Update DJ strategy steering with drop-anchor refinement behavior.
  - Update transition audition runbooks with canonical/refined-anchor commands.
  - Record deferred ML/model-training path and dataset size requirements.
  - Completion notes, 2026-05-24:
    - Added
      `.codex/specs/010-canonical-pcm-drop-anchor-refinement/final-drop-switch-pipeline.md`
      documenting the accepted audition path:
      AutoDJ BPM/beatgrid/key, Rekordbox semantic labels only, exact-first
      SoundStretch-eligible BPM handling, Camelot-compatible drop-switch pair
      filtering, raw 80 ms transient nudge, gain planning, render/session
      export.
    - Updated steering docs so future agents do not reintroduce rejected
      failure paths:
      `.codex/steering/05-dubstep-dj-strategy.md`,
      `.codex/steering/07-analysis-pipeline.md`, and
      `.codex/steering/09-roadmap.md`.
    - `tools/run-transition-audition-batch.ps1` and the public
      `nudge-mixplan` CLI were cleaned so generated final-pipeline batches no
      longer expose the rejected refined-anchor switches. The script now
      defaults generated drop-switch pair selection to
      `-DropSwitchKeyPolicy compatible` and
      `-DropSwitchTempoPolicy exact-then-stretch`.
    - Deferred ML/model-training remains documented as a future semantic/drop
      recognition path; it should not be trained only on the current 48-track
      set.
  - _Requirements: 1.5, 8.5_

- [x] 15. Final verification
  - Run CMake configure/build/CTest.
  - Run Python worker tests.
  - Validate contract examples.
  - Confirm generated cache/audio/dataset artifacts remain ignored.
  - Record final verification results under this task.
  - Completion notes, 2026-05-24:
    - CMake build:
      `cmake --build --preset debug --target autodj_dj_tests autodj_playback_tests`
      -> passed.
    - CTest:
      `ctest --preset debug -R "autodj_(dj_tests|playback_tests|contract_examples)" --output-on-failure`
      -> 3/3 passed.
    - Python focused tests:
      WSL `pytest analysis/worker-python/tests/test_rekordbox_xml.py analysis/worker-python/tests/test_cli.py analysis/worker-python/tests/test_mixplan_nudge.py -q`
      -> 56 passed.
    - PowerShell parser check passed for
      `tools/run-transition-audition-batch.ps1`.
    - Final pipeline cleanup verified: no refined-anchor or
      beatgrid-phase flags remain in the transition audition batch script.
    - Additional stretch-path smoke on 2026-05-24:
      `tools/run-transition-audition-batch.ps1` with
      `-DropSwitchTempoPolicy stretch`, `-DropSwitchKeyPolicy compatible`, and
      `-TempoStretchBackend soundstretch` rendered 1/1 drop-switch audition from
      the 48-track keyed semantic-truth analysis root. The generated MixPlan
      included incoming `tempoPlan.backend = soundstretch`.
    - Generated cache/audio artifacts remain under `.autodj-cache`, which is
      ignored and not part of source control.
  - _Requirements: 2.6, 3.1, 4.5, 8.5_
