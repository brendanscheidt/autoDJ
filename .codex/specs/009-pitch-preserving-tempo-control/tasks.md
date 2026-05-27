# Implementation Plan

## Execution Rules

- Before starting any task, read `kiro.json`, `requirements.md`, `design.md`,
  and the required steering docs listed in `kiro.json`.
- Treat Rekordbox/CDJ Master Tempo as the quality reference, not a public
  implementation recipe.
- Keep backend candidates real: install/build/smoke-test before benchmarking.
- Keep tempo-stretch behavior modular and backend-swappable.
- Do not implement planner key shifting in this spec; preserve the boundary for
  Spec 010.
- Write generated audio, SDK downloads, and audition artifacts only under
  ignored local paths.
- Stop at manual audition checkpoints and record the user's verdict before
  broadening planner behavior.

## Tasks

- [x] 1. Decision checkpoint: confirm tempo-control scope and defaults
  - Confirm the default automatic planner gate:
    `maxTempoAdjustmentBpmPerDeck = 10.0`.
  - Confirm that engine/manual MixPlans may request larger stretches with
    warnings or backend errors, while the automatic planner stays gated.
  - Confirm that outgoing set-tempo ramps may be used to meet incoming tracks in
    the middle when both decks remain within the per-deck gate.
  - Confirm that Spec 010 will handle key shifting without BPM changes.
  - Record final decisions under this task before implementation begins.
  - Completion notes, 2026-05-22:
    - Default automatic planner gate is accepted:
      `maxTempoAdjustmentBpmPerDeck = 10.0`, allowing a total `20 BPM` bridge
      when two decks can meet at a shared transition BPM.
    - Engine/manual/authored MixPlans may request larger tempo stretches, but
      renderers/backends must emit explicit warnings or structured errors when
      quality/capability is risky.
    - Outgoing set-tempo ramps are in scope for this spec when they let the
      currently playing deck meet an incoming track in the middle while both
      remain inside the configured per-deck gate.
    - Drop-switch overlap still requires exact effective BPM equality at the
      transition anchor after tempo planning is applied.
    - Spec 010 is reserved for the inverse tool: key/pitch shifting without
      changing BPM.
    - The user will manually audition generated stretched audio whenever this
      implementation produces candidate renders.
  - _Requirements: 5.1, 5.2, 8.1, 8.4_

- [x] 2. Complete backend research and install plan
  - Record practical findings for Rubber Band, SoundTouch, Signalsmith Stretch,
    Superpowered, zplane elastique, and Zynaptiq ZTX.
  - Classify each as runnable-now, commercial-evaluation, future-native, or
    comparison-only.
  - Choose the first two runnable local candidates for smoke testing.
  - Record license/productization implications.
  - Completion notes, 2026-05-22:
    - Public Rekordbox/CDJ documentation confirms Master Tempo changes playback
      speed while preserving pitch, but no public source found discloses the
      internal algorithm. Rekordbox remains a listening-quality reference, not
      an implementation source.
    - First runnable local candidates selected for immediate smoke testing:
      `rubberband` and `soundstretch`.
    - `rubberband-cli` is the preferred first POC candidate because it exposes
      high-quality offline time-stretching, has C++/CLI paths, and supports
      independent tempo/pitch behavior. Productization risk:
      GPL/commercial licensing.
    - `soundstretch` / SoundTouch is the baseline comparison candidate because
      it is lightweight, easy to install, and LGPL 2.1, but it may be lower
      quality on dense dubstep.
    - Signalsmith Stretch remains a future-native candidate because it is
      MIT/header-only C++ and attractive for product integration, but it needs
      direct implementation work before smoke testing.
    - Superpowered, zplane elastique, and Zynaptiq ZTX are classified as
      commercial-evaluation candidates. They may be needed if local/open
      candidates do not meet the listening bar.
  - _Requirements: 1.1, 1.2, 1.4, 1.6_

- [x] 3. Install and smoke-test first runnable stretch candidates
  - Install/build the chosen local candidates in the WSL analysis environment.
  - Smoke-test each on generated WAV and one real local MP3/WAV.
  - Emit playable stretched WAV output and structured reports.
  - Fail loudly if a selected candidate cannot run.
  - Stop for `stretch-backend-smoke-verdict`.
  - Completion notes, 2026-05-22:
    - Installed WSL packages: `rubberband-cli` `3.3.0+dfsg-2build1`,
      `soundstretch` `2.3.2+ds1-1build1`, and `libsoundtouch1`.
    - Verified executables:
      `rubberband --version` -> `3.3.0`;
      `soundstretch` -> `SoundStretch v2.3.2`.
    - Added `autodj_analysis.tempo_stretch` with a backend-swappable
      command-runner boundary, structured `TempoStretchOptions`,
      `TempoStretchResult`, and `TempoStretchError`.
    - Added CLI commands:
      `autodj-analysis tempo-stretch-smoke` and
      `autodj-analysis stretch-audio`.
    - Focused tests passed:
      `pytest analysis/worker-python/tests/test_tempo_stretch.py analysis/worker-python/tests/test_cli.py -q`
      -> 37 passed.
    - Synthetic generated-WAV smoke passed for both backends:
      `.autodj-cache/tempo-stretch-smoke/generated-fixture-20260522/smoke/`.
    - Real local MP3 smoke passed for both backends using
      `ALLEYCVT - STRANGERS (SPOTISAVER).mp3`, stretched from `160 BPM` to
      `150 BPM`:
      `.autodj-cache/tempo-stretch-smoke/first-stretch-smoke-20260522/`.
    - Rubber Band real-song render time was about `20.98s`; SoundStretch was
      about `2.40s`. Both output durations changed from about `218.50s` to
      `233.07s`, matching a `0.9375` tempo ratio.
    - Manual gate: user should audition the real-song outputs before selecting
      a default backend or expanding renderer/planner behavior.
    - First user smoke verdict:
      both backends avoided obvious stretch artifacts on the `160 -> 150 BPM`
      test. Rubber Band sounded quieter and less full in the bass. SoundStretch
      sounded better on this first sample. More songs and stronger stretch
      directions are needed before choosing a default.
    - Second user verdict after importing the multi-song batch into Rekordbox:
      SoundStretch clearly preserved the audio better. Rubber Band still
      sounded quieter/less full after removing `--centre-focus`. Use
      SoundStretch as the selected POC backend unless a future commercial SDK
      beats it.
    - Corrected a benchmark-label error: the first Strangers comparison used
      guessed `160 BPM` source metadata even though AutoDJ/Rekordbox analysis
      says Strangers is `145 BPM`. The resulting Rekordbox `154.05 BPM` read on
      the old `160 -> 170` file is explained by applying a `170/160` ratio to a
      `145 BPM` source.
    - Rekordbox calibration verdict on corrected Strangers excerpts:
      SoundStretch requested `155.00` displayed as `154.98`,
      `155.02` displayed as `155.01`, and `155.05` displayed as `155.04`;
      requested `135.00` displayed as `134.95`, `135.03` as `135.07`, and
      `135.05` as `135.03`.
    - Duration checks show the SoundStretch WAV outputs are within roughly
      `0.06-0.07ms` of the mathematically expected duration for each requested
      BPM. The Rekordbox readings are therefore treated as analysis/display
      variance on short excerpts, not a stable SoundStretch timing error.
      Do not apply a hidden global BPM bias. Keep `--target-bpm-bias` as an
      explicit audition/export diagnostic knob only.
    - Planning note from user verdict: after SoundStretch renders a tempo
      matched derived asset, run a lightweight BPM/beat-spacing validation or
      reanalysis pass on that rendered asset before using it for transitions
      that need long beat-locked overlap. The engine math remains primary, but
      rendered-asset validation should catch any backend or export drift before
      a planner assumes it will stay in sync.
  - _Requirements: 1.3, 1.5, 2.2, 2.3_

- [x] 4. Add tempo-stretch backend interface and CLI
  - Add Python backend protocol/result types.
  - Add backend registry selection for tempo stretching.
  - Add `tempo-stretch-smoke` and `stretch-audio` CLI entry points.
  - Include backend, version, source BPM, target BPM, ratio, runtime, and
    warnings in reports.
  - Add tests for success, unavailable backend, invalid BPM, and report output.
  - Completion notes, 2026-05-22:
    - Added backend-swappable Python interface in
      `analysis/worker-python/src/autodj_analysis/tempo_stretch.py`.
    - Added runnable CLI commands:
      `autodj-analysis tempo-stretch-smoke` and
      `autodj-analysis stretch-audio`.
    - Reports include backend name/version, source BPM, requested target BPM,
      effective target BPM, tempo ratio, quality mode, sample rate, runtime,
      command provenance, duration, and warnings.
    - Added explicit `--target-bpm-bias` for tiny calibration tests. It is not
      a hidden global correction; it is recorded in each report so audition
      assets remain honest.
    - Focused verification:
      `pytest analysis/worker-python/tests/test_tempo_stretch.py analysis/worker-python/tests/test_cli.py -q`
      -> 38 passed.
    - Generated Rekordbox calibration folder:
      `C:\Users\Brendan\Desktop\TempoStretchRekordboxCompare-SoundStretchCalibration-20260522`.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 5. Extend MixPlan contract for tempo targets and preserve-pitch intent
  - Add backward-compatible fields for source BPM, target BPM, tempo ratio,
    preserve-pitch, and tempo backend provenance where needed.
  - Add tempo-ramp automation shape if the existing control model is
    insufficient.
  - Update contract examples with one tempo-matched drop switch.
  - Add validation coverage proving old MixPlans remain valid.
  - Completion notes, 2026-05-22:
    - Added an explicit `tempoPlan` contract object for source BPM, target BPM,
      tempo ratio, preserve-pitch intent, stretch backend provenance, rendered
      asset provenance, validation status, and rendered BPM validation
      requirements.
    - Added optional `sourceBpm` and `normalizedBpm` fields to MixPlan assets.
    - Added `tempoPlan` support to track placements and transition edges in the
      C++ MixPlan parser.
    - Kept backward compatibility: old MixPlans without tempo fields still
      parse, and validation only applies when tempo fields are present.
    - Updated the stub MixPlan with a SoundStretch tempo-matched drop switch and
      a `tempo` automation command that records preserve-pitch/stretch
      provenance.
    - Recorded the user decision that SoundStretch-derived tempo assets should
      be BPM/beat-spacing revalidated after render before long beat-locked
      transition use.
    - Focused verification:
      `cmake --build --preset debug --target autodj_playback_tests` passed;
      `ctest --preset debug -R "autodj_(playback_tests|contract_examples)" --output-on-failure`
      passed; WSL
      `pytest analysis/worker-python/tests/test_tempo_stretch.py analysis/worker-python/tests/test_cli.py -q`
      -> 38 passed.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 6. Add offline renderer tempo-stretch support
  - Apply the selected stretch backend before existing EQ/effects/volume
    automation.
  - Support constant target BPM for incoming decks.
  - Support outgoing tempo ramp if feasible; otherwise stop and record the
    exact blocker.
  - Write stretch provenance into `render-summary.json`.
  - Add synthetic click/impulse tests for stretched timing.
  - Completion notes, 2026-05-22:
    - Added constant `tempoPlan` support to the Python offline MixPlan renderer.
      Placements with `sourceBpm`, `targetBpm`, and `tempoRatio` now pre-render a
      pitch-preserved WAV through the selected stretch backend before the
      existing band split, EQ, effects, volume, crossfader, and output render
      path.
    - Default render backend is `soundstretch`, with `--tempo-backend` and
      `--tempo-quality` available on `autodj-analysis render-mixplan`.
    - Source timestamps are mapped through the constant tempo ratio before
      reading from the stretched asset, so original-source anchor seconds still
      land at the correct rendered source position.
    - `render-summary.json` now includes `tempoStretchReports`, including the
      backend report and the `requiresRenderedBpmValidation` flag.
    - Dynamic tempo ramps are not implemented in the offline renderer yet. The
      renderer now fails loudly with `tempo_ramp_unsupported` when a `tempo`
      automation command changes value over time. Constant one-keyframe tempo
      commands remain accepted as provenance/control hints.
    - Added tests proving constant tempo stretch runs before existing automation
      and that unsupported dynamic tempo ramps fail explicitly.
    - Focused verification:
      WSL
      `pytest analysis/worker-python/tests/test_mixplan_renderer.py analysis/worker-python/tests/test_cli.py -q`
      -> 40 passed.
  - _Requirements: 4.1, 4.2, 4.3, 4.5, 6.1, 6.3_

- [x] 7. Update beatgrid mapping and transient nudge for stretched decks
  - Implement deterministic source-to-output beatgrid mapping.
  - Ensure `nudge-mixplan` can operate after tempo stretching.
  - Add tests proving aligned anchors land at the same output sample within
    tolerance after stretch plus nudge.
  - Add warnings for low beatgrid confidence or high nudge uncertainty.
  - Completion notes, 2026-05-22:
    - Added `autodj_analysis.tempo_mapping` as the shared constant-tempo mapping
      helper for source seconds, stretched seconds, beatgrid timeline mapping,
      and rendered transient-alignment nudge math.
    - Updated the offline renderer to use the shared source-to-stretched mapping
      when reading pre-rendered tempo-stretched assets.
    - Updated `nudge-mixplan` to account for outgoing and incoming tempo ratios.
      Incoming source-start nudges are still written in original source seconds,
      but the nudge decision now aligns rendered/timeline transient positions.
    - Added tests for beatgrid mapping, source/stretched round trips, stretched
      transient nudge math, and stretched incoming MixPlan nudge behavior.
    - Existing nudge confidence and anchor-disagreement reporting remains in
      place for low-certainty transitions.
    - Focused verification:
      WSL
      `pytest analysis/worker-python/tests/test_tempo_mapping.py analysis/worker-python/tests/test_mixplan_nudge.py analysis/worker-python/tests/test_mixplan_renderer.py analysis/worker-python/tests/test_cli.py -q`
      -> 46 passed.
  - _Requirements: 4.4, 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 8. Add planner tempo-eligibility and stretched drop-switch generation
  - Add configurable `maxTempoAdjustmentBpmPerDeck`.
  - Generate shared transition BPM targets for candidate pairs.
  - Emit outgoing tempo ramps when needed and allowed.
  - Keep exact effective BPM equality at drop-switch overlap.
  - Emit structured rejection reasons for out-of-range candidates.
  - Add C++ planner tests for exact native match, one-sided stretch, midpoint
    bridge, over-gate rejection, and disabled tempo backend fallback.
  - Completion notes, 2026-05-22 through 2026-05-24:
    - Added planner options:
      `allowTempoStretch`, `maxTempoAdjustmentBpmPerDeck`, `tempoBackend`,
      `tempoBackendVersion`, `tempoQuality`, and
      `requiresRenderedBpmValidation`.
    - Added one-sided incoming tempo-stretched drop-switch eligibility. If the
      incoming track is within the configured BPM gate, the planner can target
      the outgoing track's current effective BPM and emit an incoming
      `tempoPlan`.
    - The drop-switch template now adjusts incoming source-window math by
      `tempoRatio`, emits a constant `tempo` automation command, marks
      preserve-pitch backend provenance, and risk-flags the transition with
      `incoming_tempo_stretch_requires_validation`.
    - Native exact-BPM candidates are still preferred over stretched candidates
      because stretched candidates carry validation risk.
    - Added structured rejection for one-sided candidates outside the gate:
      `tempo_adjustment_over_gate`.
    - Added disabled-backend fallback coverage:
      `allowTempoStretch=false` preserves the prior exact-BPM-only behavior.
    - Midpoint bridge planning still requires outgoing tempo ramps. The offline
      renderer currently fails dynamic tempo ramps with
      `tempo_ramp_unsupported`, so the planner does not emit midpoint bridge
      plans yet. This is explicitly deferred; the accepted POC scope is
      one-sided incoming SoundStretch matching plus exact effective BPM at the
      drop-switch overlap.
    - Focused verification:
      `cmake --build --preset debug --target autodj_dj_tests autodj_playback_tests`
      passed;
      `ctest --preset debug -R "autodj_(dj_tests|playback_tests|contract_examples)" --output-on-failure`
      passed; WSL
      `pytest analysis/worker-python/tests/test_tempo_mapping.py analysis/worker-python/tests/test_mixplan_nudge.py analysis/worker-python/tests/test_mixplan_renderer.py analysis/worker-python/tests/test_cli.py -q`
      -> 46 passed.
    - 2026-05-24 pipeline update:
      `autodj_mixplan_poc` now exposes tempo-stretch options on the CLI, and
      `tools/run-transition-audition-batch.ps1` can generate drop-switch
      candidates with `-DropSwitchTempoPolicy exact-then-stretch`, `exact`, or
      `stretch`. The generated audition path uses one-sided incoming
      SoundStretch matching inside `-MaxTempoAdjustmentBpmPerDeck`, keeps exact
      native BPM matches first by default, and filters drop-switch candidates by
      in-house Camelot compatibility. Midpoint bridge planning is still
      deferred.
    - A stretch-only smoke batch generated 1/1 key-compatible stretched
      drop-switch audition from the 48-track keyed semantic-truth analysis root.
      The final MixPlan included incoming `tempoPlan.backend = soundstretch`.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 9. Generate tempo-stretch audition batch
  - Use the 48-track dubstep analysis set if available.
  - Generate small/medium/near-gate BPM delta examples.
  - Include unstretched/fallback and stretched comparison artifacts when useful.
  - Write importable AutoDJ sessions and rendered WAVs under ignored cache.
  - Stop for `stretch-quality-verdict`.
  - Completion notes, 2026-05-24:
    - Generated exact-BPM/key-compatible drop-switch auditions under
      `.autodj-cache/transition-auditions/final-exact-keyed-dropswitch-20260524-095834`.
    - Generated BPM-stretched/key-compatible drop-switch auditions under
      `.autodj-cache/transition-auditions/final-stretched-keyed-dropswitch-20260524-100347`.
    - Stretched examples covered small, medium, and near-gate one-sided
      incoming deltas: `138 -> 140`, `150 -> 145`, `140 -> 145`, and
      `140 -> 150`.
    - Each stretched MixPlan emitted `tempoPlan.backend = soundstretch` and
      passed through tempo-aware transient nudge, gain planning, WAV render, and
      importable AutoDJ session export.
    - Manual verdict: the generated exact and stretched drop-switch auditions
      sounded great, including the SoundStretch examples.
  - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 10. Tune selected backend and planner gate after manual verdict
  - Record which backend sounds best on dense dubstep.
  - Tune default quality mode and warning thresholds.
  - Adjust `maxTempoAdjustmentBpmPerDeck` if 10 BPM is too aggressive or too
    conservative.
  - Stop for `tempo-planner-verdict` before enabling broad generation.
  - Completion notes, 2026-05-24:
    - Selected default POC backend remains `soundstretch`; Rubber Band stays as
      a comparison backend because it reduced perceived loudness and bass
      fullness in the audition material.
    - Default generated-audition gate remains `10 BPM` one-sided incoming
      adjustment. The current automatic batch policy is exact-first, then
      SoundStretch-eligible candidates when more drop switches are needed.
    - Broad midpoint bridge behavior remains deferred until dynamic tempo ramps
      can be rendered and auditioned.
  - _Requirements: 7.4, 7.5_

- [x] 11. Update steering docs and roadmap
  - Record selected/default stretch backend and deferred candidates.
  - Update playback-engine notes with tempo source-time mapping behavior.
  - Update DJ strategy notes with configurable tempo-matched drop-switch
    eligibility.
  - Record Spec 010 as the next pitch/key-shift work.
  - Completion notes, 2026-05-24:
    - Updated steering docs to describe exact-first, key-compatible
      drop-switch candidate selection with SoundStretch-eligible incoming tempo
      matching.
    - Documented that the accepted generated-audition path still avoids the
      rejected refined-anchor/drop-wall/beatgrid-phase branches unless a future
      spec explicitly reopens them.
    - Recorded midpoint bridge tempo ramps as deferred.
  - _Requirements: 8.2, 8.3, 8.4_

- [x] 12. Final verification
  - Run CMake configure/build/CTest.
  - Run Python worker tests.
  - Validate contract examples.
  - Confirm generated audio/cache/SDK artifacts remain ignored.
  - Record final verification results under this task.
  - Completion notes, 2026-05-24:
    - CMake configure:
      `cmake --preset debug` -> passed.
    - CMake build:
      `cmake --build --preset debug` -> passed.
    - CTest:
      `ctest --preset debug --output-on-failure` -> 8/8 passed, including
      `autodj_contract_examples`.
    - Python worker suite:
      WSL `pytest analysis/worker-python/tests -q` -> 327 passed, 9 warnings.
    - PowerShell parser check passed for
      `tools/run-transition-audition-batch.ps1`.
    - `git diff --check` passed.
    - Generated audition/cache artifacts remain ignored by
      `.gitignore:44:.autodj-cache/`, verified against the stretch smoke render
      and final stretched audition transition folder.
  - _Requirements: 1.6, 2.5, 3.5, 7.5_
