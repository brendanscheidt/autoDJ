# Implementation Plan

## Execution Rules

- Before starting any task, read `kiro.json`, `requirements.md`, `design.md`,
  and the required steering docs listed in `kiro.json`.
- Treat `current-autodj-signal` BPM/beatgrid as fixed input. Prefer
  Rekordbox-labeled semantic cues when available, and keep automatic
  semantic-section backends behind the normalized analyzed-track contract.
- Keep real audio, rendered previews, Rekordbox exports, and generated audition
  artifacts out of git.
- Prefer deterministic contracts, scheduling, and tests before UI polish.
- Stop at manual audition checkpoints and ask the user to listen before
  expanding strategy behavior.
- If a task is blocked by a product decision, leave it unchecked and record the
  exact decision needed.

## Tasks

- [x] 1. Decision checkpoint: confirm audition target and effect scope
  - Ask the user to choose the first audition target:
    offline render harness, realtime desktop playback, or command-plan
    simulator first.
  - Confirm whether Spec 006 must implement audible reverb/EQ-low processing,
    or whether it can first emit/test automation commands with audio effects
    implemented in the next spec.
  - Confirm default transition parameters:
    - 4 beats per measure;
    - `song_a` silent 2 measures before aligned drop in the drop-switch
      template;
    - reverb-exit ramp begins 8 measures before drop end;
    - reverb reaches 100% at drop end;
    - `song_b` low EQ restores over 4 measures.
  - Record decisions under this task before implementation begins.
  - Decision notes, 2026-05-19:
    - First audition target: offline render harness. Realtime UI debugging is
      deferred unless listening/debugging problems require it.
    - The first renderer should be implemented in Python for speed of
      iteration, while the C++ side owns the `MixPlan` contract, validation,
      and deterministic scheduler.
    - Rendered audition output should be WAV, not MP3, to avoid encoder-delay
      confusion during beat-accurate listening checks.
    - Spec 006 must implement audible EQ-low and reverb behavior, not just
      command simulation, because the fallback transition depends on those
      effects musically.
    - Reverb behavior should match the concrete CDJ-style plan: outgoing dry
      volume can reach 0 while a post-fader reverb tail remains audible and is
      then faded out. A simple CDJ-style approximation is acceptable for the
      first POC.
    - `song_b` starts from the first beatgrid beat after initial silence in the
      drop-end reverb exit template.
    - Default transition parameters are accepted:
      4 beats per measure; `song_a` is silent 2 measures before the aligned
      drop in the drop-switch template; the reverb-exit ramp begins 8 measures
      before drop end; reverb reaches 100% at drop end; `song_b` low EQ
      restores over 4 measures.
    - Documentation/spec-only task; no runtime behavior changed, so no tests
      were run.
  - _Requirements: 3.1, 3.4, 4.1, 4.5, 6.1, 6.3_

- [x] 2. Review and refine MixPlan contract for POC commands
  - Audit `core/contracts/schemas/mix-plan.schema.json` against both MVP
    transition templates.
  - Add backward-compatible fields only if needed for source paths, technique
    metadata, reverb-tail behavior, or debug annotations.
  - Update `core/contracts/examples/mix-plan.stub.json`.
  - Add or update contract validation coverage.
  - Completion notes, 2026-05-19:
    - Audited the existing `MixPlan` schema against the two MVP templates. The
      existing command vocabulary already covered load/play/stop/seek and
      automation, so the task only needed backward-compatible additions.
    - Added optional `assets` entries for track audio references so the Python
      offline WAV renderer can resolve sanitized/source audio without putting
      real paths in committed examples.
    - Added `drop_end_reverb_exit` as an explicit transition technique while
      keeping `build_to_drop_swap` for the second-build drop switch template.
    - Added optional transition metadata fields:
      `templateId`, `measureCountToTarget`, `alignedDropTimelineSeconds`,
      `handoffTimelineSeconds`, and structured `sourceAnchors`.
    - Added `reverbTailGain` and `reverbDecaySeconds` automation controls plus
      optional `postFader` and `effectParameters` fields so the POC can express
      CDJ-style post-fader reverb tails without faking them through dry deck
      volume.
    - Expanded `core/contracts/examples/mix-plan.stub.json` to include both POC
      transition shapes: a second-build drop switch and a drop-end reverb exit.
      The example uses relative placeholder WAV source URIs and does not
      reference real music paths.
    - Updated `core/contracts/tests/validate_contract_examples.cmake` to require
      MixPlan assets, both transition techniques, and a `reverbTailGain`
      automation command in the fixture.
    - Corrected this spec's `kiro.json` contract validation command to the
      actual CTest contract example test, because no
      `autodj_contract_examples` build target exists.
    - Verified with:
      `node -e "const fs=require('fs'); for (const p of ['core/contracts/schemas/mix-plan.schema.json','core/contracts/examples/mix-plan.stub.json']) { JSON.parse(fs.readFileSync(p,'utf8')); console.log('valid json', p); }"`
      -> both files parsed as valid JSON.
    - Verified with:
      `cmake -DCONTRACTS_DIR="$PWD/core/contracts" -P core/contracts/tests/validate_contract_examples.cmake`
      -> passed.
    - Verified with:
      `ctest --preset debug -R autodj_contract_examples --output-on-failure`
      -> 1/1 tests passed.
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6, 7.1_

- [x] 3. Implement C++ MixPlan parsing and validation model
  - Add typed C++ structures for placements, transitions, commands,
    automation keyframes, and annotations.
  - Parse the existing JSON contract shape.
  - Validate references, timestamps, command ordering, and template-specific
    invariants needed by the POC.
  - Keep validation errors structured and testable.
  - Completion notes, 2026-05-19:
    - Added `core/playback/include/autodj/playback/mix_plan.hpp` with typed
      C++ structures for strategy provenance, assets, placements, transition
      edges, source anchors, commands, automation keyframes, annotations, and
      parse/validation results.
    - Added `core/playback/src/mix_plan.cpp` with an internal JSON parser and
      `parseMixPlan()` implementation. No third-party JSON dependency was
      added.
    - `PlaybackEngine::loadPlan()` now parses and validates actual `MixPlan`
      JSON instead of accepting any non-empty placeholder string. Invalid
      plans reset loaded playback state and return structured validation
      errors.
    - Validation now checks required root fields, array/object shapes,
      duplicate asset/placement/transition IDs, non-negative finite times,
      placement and transition time ordering, transition placement references,
      command track references, sorted top-level command times, sorted
      automation keyframes, valid command/control/technique enums, and POC
      template invariants for `second_build_drop_switch_v1` and
      `drop_end_reverb_exit_v1`.
    - Automation commands may omit a top-level `at`; the parser derives their
      command time from the first keyframe, matching the current schema shape.
    - Expanded `core/playback/tests/playback_tests.cpp` to cover valid fixture
      parsing, POC transition fields, post-fader `reverbTailGain`, malformed
      JSON, missing required fields, unknown placement references, unsorted
      commands, invalid template invariants, and `PlaybackEngine` state reset
      on invalid load.
    - Updated `core/playback/CMakeLists.txt` to compile the MixPlan parser and
      expose the contracts directory to playback tests.
    - Verified with:
      `cmake --build --preset debug --target autodj_playback_tests`
      -> passed.
    - Verified with:
      `ctest --preset debug -R autodj_playback_tests --output-on-failure`
      -> 1/1 tests passed.
    - Verified with:
      `ctest --preset debug -R "autodj_(playback_tests|contract_examples)" --output-on-failure`
      -> 2/2 tests passed.
    - Verified with:
      `cmake --build --preset debug`
      -> passed.
  - _Requirements: 1.1, 2.1, 2.5, 2.6, 7.2_

- [x] 4. Implement deterministic playback command scheduler
  - Store loaded plan commands sorted by timeline time and deterministic
    same-time priority.
  - Expose computed deck/control state at arbitrary timeline times.
  - Recompute state correctly after seek.
  - Add tests for load/play/seek/stop, automation interpolation, same-time
    ordering, and invalid plans.
  - Completion notes, 2026-05-19:
    - Added runtime execution state types to `PlaybackEngine`: per-deck loaded
      and playing state, current source position, loop state, deck-specific
      automation controls, and global automation controls.
    - `PlaybackEngine::loadPlan()` now compiles a deterministic command
      schedule from the parsed `MixPlan`. Commands are ordered by timeline time,
      then by explicit same-time priority, then original command index.
    - Same-time priority follows the Spec 006 design intent:
      stop/clear-loop first, then load, seek, automation/set-loop, and play.
      This lets a deck be stopped, loaded, and played at the same timestamp in
      a predictable final state.
    - Added `evaluateAt(timelineSeconds)` and `getExecutionState()` so tests,
      renderers, and future UI code can compute active deck/control state at
      any timeline time. State is recomputed from the immutable plan schedule
      rather than incrementally guessed.
    - Source position advances from load/play/seek commands using timeline
      elapsed time. Stop unloads the deck from the runtime state; load resets
      the deck's source position and control state.
    - Automation lanes are evaluated independently from keyframes. Deck-scoped
      controls land on the deck state; commands without a deck become global
      controls such as `crossfader`. Interpolation supports hold, linear,
      smoothstep, and exponential behavior.
    - Expanded `core/playback/tests/playback_tests.cpp` with coverage for
      source-position advancement, seek recomputation, deck/global automation
      interpolation, same-timestamp command priority, and invalid plans blocking
      playback.
    - Verified with:
      `cmake --build --preset debug --target autodj_playback_tests`
      -> passed.
    - Verified with:
      `ctest --preset debug -R autodj_playback_tests --output-on-failure`
      -> 1/1 tests passed.
    - Verified with:
      `ctest --preset debug -R "autodj_(playback_tests|contract_examples)" --output-on-failure`
      -> 2/2 tests passed.
    - Verified with:
      `cmake --build --preset debug`
      -> passed.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 7.2_

- [x] 5. Add analysis-artifact summary reader for strategy inputs
  - Read selected fields from `analyzed-track.json` without depending on
    Rekordbox XML.
  - Extract normalized BPM, beats, ordered builds, ordered drops, cue points,
    and confidence/warnings.
  - Add tests with sanitized fixture artifacts.
  - Completion notes, 2026-05-19:
    - Added `core/dj/include/autodj/dj/analyzed_track_summary.hpp` and
      `core/dj/src/analyzed_track_summary.cpp` as the C++ strategy-facing
      reader for selected `AnalyzedTrack` fields.
    - The reader consumes only `analyzed-track.json` shape: `trackId`,
      `source.sourceUri`, `durationSeconds`, `tempo.bpm`,
      `tempo.normalizedBpm`, tempo confidence, beat-grid confidence and beats,
      ordered build sections, ordered drop sections, cue points, quality
      confidence, and artifact warnings. It does not accept or inspect
      Rekordbox XML.
    - The summary model fixes `beatsPerMeasure` at 4 for this MVP, matching
      the Spec 006 transition math.
    - Low or medium confidence and missing build/drop sections are surfaced as
      `riskFlags` so later planner tasks can choose simpler templates or reject
      risky pairs.
    - Added `readTrackAnalysisSummary()` for file-based artifacts and
      `parseTrackAnalysisSummary()` for tests and future cache integration.
    - Updated `core/dj/tests/dj_tests.cpp` with sanitized fixture coverage for
      the contract example artifact, section/cue ordering, low-confidence risk
      flags, and invalid artifact rejection.
    - Updated `core/dj/CMakeLists.txt` to compile the reader and expose
      `core/contracts` to DJ tests.
    - Verified with:
      `cmake --build --preset debug --target autodj_dj_tests`
      -> passed.
    - Verified with:
      `ctest --preset debug -R autodj_dj_tests --output-on-failure`
      -> 1/1 tests passed.
    - Verified with:
      `ctest --preset debug -R "autodj_(dj_tests|playback_tests|contract_examples)" --output-on-failure`
      -> 3/3 tests passed.
    - Verified with:
      `cmake --build --preset debug`
      -> passed.
    - Also ran full `ctest --preset debug --output-on-failure`; all tests
      passed except the pre-existing `autodj_repository_boundaries` check,
      which still reports local generated `.autodj-cache` and `local-audio`
      artifacts in the workspace tree.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 6. Implement second-build drop switch template generator
  - Detect whether `song_a` has build 2 -> drop 2 and `song_b` has build 1 ->
    drop 1.
  - Require exact normalized BPM equality for `song_a` and `song_b`; do not
    allow a tolerance in the POC.
  - Calculate measure counts and aligned source/timeline starts.
  - Emit `MixPlan` placements, transition edge, load/play/automation commands,
    and debug annotations.
  - Add unit tests for normal alignment, clamped `song_b` source start,
    missing sections, low confidence, exact BPM mismatch rejection, and exact
    handoff timing.
  - Completion notes, 2026-05-19:
    - Added `core/dj/include/autodj/dj/second_build_drop_switch.hpp` and
      `core/dj/src/second_build_drop_switch.cpp`.
    - Implemented `buildSecondBuildDropSwitchTemplate()` as a narrow template
      generator that consumes two `TrackAnalysisSummary` values and returns a
      typed `MixPlan` fragment: outgoing/incoming placements, one
      `build_to_drop_swap` transition edge, load/play/stop commands, volume
      and crossfader automation commands, and debug annotations.
    - Enforced exact `tempo.normalizedBpm` equality. Any BPM difference rejects
      the template with `bpm_mismatch_for_drop_switch`; no tolerance is used.
    - Validated required section shape: outgoing build 2 -> drop 2, incoming
      build 1 -> drop 1, usable ordering, enough measures to complete the
      two-measure pre-drop handoff, and minimum section confidence.
    - Calculated `measureCountToTarget` from the outgoing build-to-drop span
      using 4 beats per measure, aligned the incoming drop to the outgoing drop
      2 boundary, and clamped `song_b` source start to 0 only when needed.
      Clamping is preserved as an `incoming_source_start_clamped` risk flag.
    - Emitted source anchors for `fromBuildStart`, `fromDropStart`,
      `toBuildStart`, and `toDropStart`, including beat and measure indexes
      when available from the analysis summary.
    - Updated `core/dj/CMakeLists.txt` so `autodj_dj` builds the new generator
      and links the typed `MixPlan` model from `autodj_playback`.
    - Expanded `core/dj/tests/dj_tests.cpp` for aligned normal timing,
      clamped incoming source start, missing sections, low confidence, exact
      BPM mismatch rejection, too-short handoff rejection, and emitted command
      timing.
    - Verified with:
      `cmake --build --preset debug --target autodj_dj_tests`
      -> passed.
    - Verified with:
      `ctest --preset debug -R autodj_dj_tests --output-on-failure`
      -> 1/1 tests passed.
    - Verified with:
      `ctest --preset debug -R "autodj_(dj_tests|playback_tests|contract_examples)" --output-on-failure`
      -> 3/3 tests passed.
    - Verified with:
      `cmake --build --preset debug`
      -> passed.
  - _Requirements: 1.2, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 5.2, 5.5_

- [x] 7. Implement drop-end reverb exit template generator
  - Detect when `song_a` lacks a second build/drop pair but has a usable drop
    end.
  - Start `song_b` from its first beat.
  - Emit low-EQ, reverb, volume, and incoming low-EQ automation.
  - Add unit tests for full 8-measure ramp, shortened/clamped ramp, missing
    drop end, and exact start/end timestamps.
  - Completion notes, 2026-05-19:
    - Added `core/dj/include/autodj/dj/drop_end_reverb_exit.hpp` and
      `core/dj/src/drop_end_reverb_exit.cpp` with
      `buildDropEndReverbExitTemplate()`.
    - The generator rejects invalid deck/options/BPM data, rejects tracks with
      a usable second build/drop pair by default, requires an outgoing drop end,
      and starts the incoming track from its first beatgrid beat.
    - The generated fragment emits outgoing low-EQ ramp, outgoing post-fader
      `reverbWet`, outgoing dry `volume` fade, post-fader `reverbTailGain`,
      incoming low-EQ restore, load/play/stop commands, transition anchors, and
      annotations for the drop-end handoff.
    - Full 8-measure reverb ramp uses the outgoing BPM; incoming low restore
      and outgoing reverb-tail drain use the incoming BPM over four measures.
    - Short drops clamp the reverb ramp to the drop start and add
      `reverb_exit_ramp_clamped` instead of inventing pre-drop automation.
    - Added DJ unit tests for full ramp timing, clamped ramp timing, missing
      drop-end rejection, and exact non-zero source/timeline timestamp
      calculations.
    - Wired the generator into `autodj_dj` and the aggregate DJ header.
    - Verified edited files remained NUL-free after patching.
    - Verified with:
      `cmake --build --preset debug --target autodj_dj_tests`
      -> passed.
    - Verified with:
      `ctest --preset debug -R autodj_dj_tests --output-on-failure`
      -> 1/1 tests passed.
    - Verified with:
      `ctest --preset debug -R "autodj_(dj_tests|playback_tests|contract_examples)" --output-on-failure`
      -> 3/3 tests passed.
    - Verified with:
      `cmake --build --preset debug`
      -> passed.
  - _Requirements: 1.3, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.2, 5.5_

- [x] 8. Add minimal DubstepDJStrategy POC planner
  - Replace or supplement `generatePlanPlaceholder()` with a deterministic POC
    plan-generation path.
  - Scan candidate incoming songs for an exact-normalized-BPM second-build drop
    switch candidate before falling back.
  - Choose second-build drop switch when valid.
  - Otherwise choose drop-end reverb exit when valid.
  - Otherwise reject the pair with structured reasons.
  - Ensure `song_b` becomes the outgoing/primary track after each transition in
    planner state.
  - Completion notes, 2026-05-19:
    - Added a typed `DubstepDJStrategy::generatePocPlan()` path while keeping
      the legacy `generatePlanPlaceholder()` method intact for existing
      callers.
    - Added `DubstepPocPlanResult` with structured fatal errors, candidate
      rejections, debug notes, selected incoming track, selected template, and
      `nextOutgoingTrackId` / `nextOutgoingDeck` planner-state output so the
      chosen incoming song becomes the next outgoing song.
    - The planner first scans incoming candidates for an exact-normalized-BPM
      `second_build_drop_switch_v1` candidate. BPM mismatches are recorded as
      `bpm_mismatch_for_drop_switch` candidate rejections and do not stop the
      scan.
    - If no exact-BPM drop-switch candidate is selected, the planner tries the
      `drop_end_reverb_exit_v1` fallback. This fallback is allowed after the
      exact-BPM scan fails, matching the POC decision that type 1 requires exact
      BPM and type 2 is the safe non-time-stretched fallback.
    - Added `serializeMixPlanJson()` so generated typed plans can be written as
      contract-shaped JSON and round-tripped through the playback parser.
    - Generated plans include deterministic strategy provenance, assets,
      placements, transition edge, commands, annotations, and selected-template
      debug annotation.
    - Added DJ unit tests for exact-BPM candidate scanning, drop-end reverb
      fallback when no exact-BPM candidate exists, structured no-template
      rejection, JSON serialization, parser validation, and next-outgoing
      planner state.
    - Verified edited files remained NUL-free after patching.
    - Verified with:
      `cmake --build --preset debug --target autodj_dj_tests`
      -> passed.
    - Verified with:
      `ctest --preset debug -R autodj_dj_tests --output-on-failure`
      -> 1/1 tests passed.
    - Verified with:
      `ctest --preset debug -R "autodj_(dj_tests|playback_tests|contract_examples)" --output-on-failure`
      -> 3/3 tests passed.
    - Verified with:
      `cmake --build --preset debug`
      -> passed.
  - _Requirements: 3.1, 4.1, 5.5, 6.5_

- [x] 9. Build chosen audition path
  - Create a Python offline render harness that can render enough two-deck WAV
    audio to hear volume, low-EQ, and simple CDJ-style post-fader reverb-tail
    behavior.
  - If realtime desktop is selected: add minimal desktop playback controls for
    loading and playing a `MixPlan`.
  - If simulator-first is selected: emit state traces and defer audible effects
    to the next task before manual signoff.
  - Write all generated audition artifacts under ignored local paths.
  - Completion notes, 2026-05-19:
    - Added `analysis/worker-python/src/autodj_analysis/mixplan_renderer.py`
      with a deterministic offline MixPlan audition renderer.
    - The renderer reads contract-shaped `MixPlan` JSON, resolves asset
      `sourceUri` paths relative to the plan directory or an explicit
      `--asset-root`, renders mono PCM WAV previews, and writes
      `audition.wav`, `render-summary.json`, and `state-trace.json` under the
      caller-provided output directory.
    - WAV input is supported without optional dependencies for tests and
      generated fixtures. Non-WAV input goes through the existing
      `load_audio()` boundary so real MP3/FLAC/etc. audition rendering can use
      the installed analysis audio dependencies.
    - Implemented enough audible playback behavior for the POC: two-deck
      placement rendering, deck volume automation, low-EQ approximation via a
      simple low/high split, optional crossfader automation, and simple
      CDJ-style post-fader reverb-tail approximation using `reverbWet` and
      `reverbTailGain`.
    - Added `autodj-analysis render-mixplan <mix-plan.json> --out <dir>` with
      `--asset-root`, `--sample-rate`, and `--json` options.
    - Added Python tests for WAV/summary/trace output, post-fader reverb tail
      after dry handoff, incoming low-EQ restoration, missing asset rejection,
      and CLI help coverage.
    - Generated audition artifacts are intended for ignored paths such as
      `.autodj-cache/mixplan-poc/<run-name>/`; no generated audio artifacts were
      committed.
    - Verified edited files remained NUL-free after patching.
    - Windows `python` lacked `pytest`, so focused Python tests were run with
      the WSL analysis environment.
    - Verified with:
      `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj/analysis/worker-python && ../../.venv-analysis/bin/python -m pytest tests/test_mixplan_renderer.py tests/test_cli.py -q"`
      -> 18 tests passed.
    - Verified with:
      `ctest --preset debug -R "autodj_(dj_tests|playback_tests|contract_examples)" --output-on-failure`
      -> 3/3 tests passed.
  - _Requirements: 2.2, 6.1, 6.2, 7.4_

- [x] 10. Generate first real-song transition artifacts
  - Use local analyzed-track artifacts from Spec 005 output or a fresh
    `analyze-batch` run.
  - Generate at least one Situation 1 transition and one Situation 2 transition
    if suitable song pairs exist.
  - Write `mix-plan.json`, debug summaries, and audition outputs under
    `.autodj-cache/mixplan-poc/<run-name>/`.
  - Do not commit generated artifacts.
  - Completion notes, 2026-05-19:
    - Added `core/dj/tools/mixplan_poc.cpp` and CMake target
      `autodj_mixplan_poc` so real-song artifacts are generated through the C++
      `DubstepDJStrategy::generatePocPlan()` path instead of a duplicated
      Python planner.
    - The tool reads one outgoing `analyzed-track.json` and one or more
      incoming candidate artifacts, writes `mix-plan.json`,
      `planner-summary.json`, and `transition-debug-summary.md`, and returns a
      non-zero exit code when no valid template is selected.
    - Generated Situation 1 / second-build drop switch artifact:
      - Outgoing: `ahee---wubcraft-spotisaver`
      - Incoming: `bella-hue-kumera---marked-spotisaver`
      - Output folder:
        `.autodj-cache/mixplan-poc/task10-first-real-song-20260519/drop-switch/`
      - Rendered WAV:
        `.autodj-cache/mixplan-poc/task10-first-real-song-20260519/drop-switch/render/audition.wav`
      - Selected template: `second_build_drop_switch_v1`
    - Generated Situation 2 / drop-end reverb exit artifact:
      - Outgoing: `skrillex---voltage-spotisaver`
      - Incoming: `ahee---wubcraft-spotisaver`
      - Output folder:
        `.autodj-cache/mixplan-poc/task10-first-real-song-20260519/reverb-exit/`
      - Rendered WAV:
        `.autodj-cache/mixplan-poc/task10-first-real-song-20260519/reverb-exit/render/audition.wav`
      - Selected template: `drop_end_reverb_exit_v1`
      - Candidate rejection recorded:
        `bpm_mismatch_for_drop_switch`, then type 2 fallback was selected.
    - Both artifacts also include `render-summary.json` and `state-trace.json`
      from `autodj-analysis render-mixplan`.
    - Real audio was loaded from the Spec 005 large semantic benchmark artifact
      `sourceUri` paths. No Rekordbox XML was used for runtime plan generation.
    - Confirmed generated files are ignored via `.gitignore` `.autodj-cache/`.
    - Verified edited files remained NUL-free after patching.
    - Verified with:
      `cmake --build --preset debug --target autodj_mixplan_poc autodj_dj_tests`
      -> passed.
    - Verified with:
      `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj/analysis/worker-python && PYTHONPATH=src ../../.venv-analysis/bin/python -m pytest tests/test_mixplan_renderer.py tests/test_cli.py -q"`
      -> 18 tests passed.
    - Verified with:
      `ctest --preset debug -R "autodj_(dj_tests|playback_tests|contract_examples)" --output-on-failure`
      -> 3/3 tests passed.
    - Verified with:
      `cmake --build --preset debug`
      -> passed.
  - _Requirements: 3.1, 4.1, 5.1, 6.1, 6.2, 7.4_

- [x] 11. Manual audition checkpoint
  - STOP: ask the user to listen to generated transition artifacts.
  - Record inspected songs, artifact paths, accepted/rejected transition
    behavior, timing issues, effect issues, and next changes.
  - Do not expand to full set generation until this verdict is recorded.
  - Completion notes, 2026-05-19:
    - User auditioned the first task 10 artifacts:
      - Drop switch: `ahee---wubcraft-spotisaver` ->
        `bella-hue-kumera---marked-spotisaver`
      - Reverb exit: `skrillex---voltage-spotisaver` ->
        `ahee---wubcraft-spotisaver`
    - Verdict: timing/beat matching was broadly usable, but the transitions
      were not musically acceptable.
    - Recorded issues:
      - Fades were too abrupt.
      - The generated drop switch sounded like one song faded out before the
        second song faded in; there was not enough audible simultaneous overlap.
      - Crossfade behavior was wrong for the POC intent.
      - Reverb character was promising, but wet level/tail strength were too
        weak and the tail decayed too quickly.
      - The audible transition felt like one or two measures even when the plan
        metadata said eight measures.
      - The user requested the next generation use different songs.
    - Root cause identified in the first drop-switch `mix-plan.json`: outgoing
      volume reached 0 before the incoming volume reached 1, and the renderer
      also multiplied both decks by a moving crossfader, causing audible
      double-attenuation.
  - _Requirements: 6.3, 6.4, 6.5_

- [x] 12. Tighten POC behavior after manual verdict
  - Fix only issues required to make the two MVP templates audibly coherent.
  - Avoid adding stems, layered drop variants, loop tightening, or broad set planning.
  - Update debug annotations for any newly discovered failure modes.
  - Completion notes, 2026-05-19:
    - Updated the second-build drop switch template to make the incoming deck
      fade from 0 to full volume first while the outgoing deck remains full
      volume.
    - Outgoing deck now fades out only after the incoming deck is full, ending
      at the aligned drop. This creates intentional overlap and avoids the
      previous empty-sounding gap.
    - Removed generated `crossfader` automation from the drop-switch template
      so volume automation is not double-multiplied by the offline renderer.
    - Updated drop-switch annotations/reasons to describe the new overlap-first
      behavior.
    - Strengthened reverb-exit defaults:
      - `midReverbWet`: `0.75`
      - `reverbDecaySeconds`: `8.0`
    - Strengthened the offline renderer's CDJ-style reverb approximation:
      - longer delay line;
      - higher feedback;
      - explicit `reverb_return_gain`.
    - Generated a second artifact set with different songs:
      - Drop switch:
        `.autodj-cache/mixplan-poc/task12-overlap-reverb-20260519/drop-switch/`
        using `blanke-eddie---like-this-spotisaver` ->
        `calcium---dead-instinct-spotisaver`.
      - Reverb exit:
        `.autodj-cache/mixplan-poc/task12-overlap-reverb-20260519/reverb-exit/`
        using `dion-timmer---alarma-spotisaver` ->
        `kai-wachi---drown-spotisaver`.
      - Rendered WAVs live in each folder's `render/audition.wav`.
    - Verified the new drop-switch plan has overlap: incoming reaches full
      volume at `145.614s` while outgoing remains full, then outgoing fades to
      zero at the aligned drop `148.814s`.
    - Confirmed generated artifacts remain ignored under `.autodj-cache/`.
    - Verified edited files remained NUL-free after patching.
    - Verified with:
      `cmake --build --preset debug --target autodj_mixplan_poc autodj_dj_tests`
      -> passed.
    - Verified with:
      `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj/analysis/worker-python && PYTHONPATH=src ../../.venv-analysis/bin/python -m pytest tests/test_mixplan_renderer.py tests/test_cli.py -q"`
      -> 18 tests passed.
    - Verified with:
      `ctest --preset debug -R "autodj_(dj_tests|playback_tests|contract_examples)" --output-on-failure`
      -> 3/3 tests passed.
    - Verified with:
      `cmake --build --preset debug`
      -> passed.
    - Additional manual-audition tuning, 2026-05-19:
      - Drop switch now follows the stricter formula: `song_b` starts the same
        number of beats before its first drop as `song_a` has between second
        build and second drop; `song_b` fades from 0 to full volume by the
        build midpoint; low EQ is handed from `song_a` to `song_b` instantly at
        that midpoint; and `song_a` is hard-cut one measure / four beats before
        the aligned drops.
      - Drop switch no longer performs a late smooth fade-out into the drop.
        It intentionally leaves both builds playing together after the midpoint
        and then cuts `song_a` before the pre-drop bar.
      - Reverb exit now applies reverb only during the final two measures /
        eight beats of the outgoing drop. The offline renderer feeds only the
        mid/high band into the reverb path, leaving the outgoing low band out
        of the tail.
      - Reverb exit now starts `song_b` at full volume and full band exactly at
        the outgoing drop end, while `song_a` dry volume cuts to 0 and the
        post-fader reverb tail decays for 10 seconds.
      - Reduced renderer reverb return strength after the second audition
        showed the prior tail was too heavy.
      - Generated updated audition artifacts under
        `.autodj-cache/mixplan-poc/task12-formula-v2-20260519/`.
        Drop switch uses `ooph---succulent-spotisaver` ->
        `layz---shockwave-spotisaver`; reverb exit uses `vertigo` ->
        `levity---postman-spotisaver`.
      - Rendered WAVs live at each transition folder's `render/audition.wav`.
      - User then supplied exact source timestamps and bar positions for a
        known-good drop switch and reverb exit. Added manual golden fixture
        `MixPlan` files under
        `.autodj-cache/mixplan-poc/golden-user-timestamps-20260519/` so the
        renderer can be tested without semantic detection or planner choices.
      - Fixed the Python renderer to accept UTF-8 BOM `MixPlan` JSON written
        by PowerShell, use per-plan `reverbDecaySeconds` to compute feedback
        instead of a fixed short decay, and high-pass the reverb input so the
        tail is mid/high focused.
      - Added an experimental `autodj-analysis nudge-mixplan` helper that
        compares outgoing/incoming transient-envelope peaks around
        drop-switch build/drop anchors and writes a nudged MixPlan copy by
        shifting only the incoming placement source start and load cue.
      - On the user-provided ALLEYCVT -> YDG golden pair, both build-start and
        drop-start anchor pairs estimated the incoming track was early by about
        `72.7ms`. Rendered comparison WAVs for the original plan, a `50ms`
        capped nudge, and the full `80ms`-capped nudge under the golden
        fixture folder.
      - Also confirmed a section-analysis issue for this pair: the semantic
        backend labels the user's intended ALLEYCVT `2:25.6 -> 2:52.1`
        build/drop as build/drop 3, while the current POC strategy blindly
        selects build/drop 2. That explains why the automatic plan can be
        musically wrong even when the lower-level renderer is behaving.
  - _Requirements: 3.6, 4.6, 6.5_

- [x] 13. Update README and steering docs
  - Document how to generate and audition a POC `MixPlan`.
  - Update roadmap/strategy notes with the selected audition path and remaining
    limitations.
  - Completion notes, 2026-05-22:
    - Updated `README.md` to reflect the current POC direction: use
      `current-autodj-signal` for BPM/beatgrid, use Rekordbox XML hot-cue
      labels as the trusted semantic oracle, and keep `dubstep-phrase-hybrid`,
      CUE-DETR, and EDM-98 as experimental/fallback providers.
    - Documented the canonical Rekordbox cue naming convention and the
      `apply-rekordbox-xml` / `export-rekordbox-xml` workflows.
    - Updated steering docs for the semantic provider boundary: DJ strategies
      consume canonical `AnalyzedTrack.sections` and `cuePoints`, not
      provider-specific XML or raw ML outputs.
    - Updated strategy/playback notes for exact-BPM drop switches, transient
      nudge, energy-aware overlap gain planning, and post-fader reverb-tail
      behavior.
    - Updated the roadmap to make trained semantic drop detection a future
      replacement for the Rekordbox oracle, not the current blocker.
  - _Requirements: 6.2, 7.5_

- [x] 14. Run final verification
  - Run CMake configure/build/CTest.
  - Run focused Python tests if Python helper code was added.
  - Confirm contract examples validate.
  - Confirm generated local artifacts remain ignored and outside git.
  - Record final verification results under this task.
  - Completion notes, 2026-05-22:
    - Verified the native build with `cmake --build --preset debug`.
    - Updated repository-boundary verification so it checks tracked and
      non-ignored files via `git ls-files -c -o --exclude-standard` instead of
      scanning ignored local `.autodj-cache` and `local-audio` artifacts.
      This keeps the test focused on what could be committed.
    - Verified all native tests with `ctest --preset debug --output-on-failure`
      -> 8/8 tests passed, including contract examples.
    - Verified focused Python Rekordbox/semantic-provider/optional benchmark
      tests with WSL pytest -> 43 tests passed.
    - Verified the full Python worker test suite with WSL pytest -> 260 tests
      passed, with only third-party deprecation/runtime warnings from optional
      MIR dependencies.
    - Confirmed generated real audio, local analysis cache, and audition outputs
      remain ignored by `.gitignore` and are not staged.
  - Follow-up verification, 2026-05-27:
    - Added a full-set POC generator at
      `tools/scripts/generate_full_set_poc.py` that chains pairwise
      drop-switch and wash-out plans across the 48-track dubstep test folder.
    - Fixed wash-out FX state leakage by resetting incoming-deck
      `reverbWet`, `reverbTailGain`, and `echoWet`, and by returning
      wash-out `reverbWet` to `0` at handoff while `reverbTailGain` carries
      the post-fader tail.
    - Fixed full-set rendering bleed by truncating each outgoing placement to
      its actual stop command. The offline renderer is placement-driven, so a
      stop command alone is not enough to prevent an old track from continuing
      under later transitions.
    - Hardened the full-set generator with validation that rejects plans where
      outgoing placements overrun their stop time or drop-switch windows contain
      positive reverb/tail/echo automation.
    - Verified with:
      `python -m py_compile tools/scripts/generate_full_set_poc.py`;
      `cmake --build --preset debug --target autodj_dj_tests autodj_mixplan_poc`;
      `ctest --preset debug -R "autodj_dj_tests" --output-on-failure`;
      WSL `pytest analysis/worker-python/tests/test_mixplan_renderer.py -q`;
      and a no-render full-set validation smoke run.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
