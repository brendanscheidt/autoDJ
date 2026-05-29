# Implementation Plan

- [x] 1. Confirm scope and current baseline
  - Read `kiro.json`, requirements, design, tasks, and required steering docs.
  - Record the latest accepted full-set artifacts and known failure modes:
    reverb state leaks, placement overruns, repeated pair fatigue, and high cost
    of full WAV review.
  - Completed baseline notes:
    - Current accepted direction is a QA-first full-set workflow: generate
      transition previews before another full WAV.
    - Current semantic source is Rekordbox-labeled `AnalyzedTrack` artifacts;
      automatic semantic detection remains replaceable and not trusted for
      high-risk drop switches.
    - Current full-set POC lives under ignored `.autodj-cache/full-set-poc/`
      runs; known reference runs include
      `full-set-poc-reverb-fixed-20260525-125606`,
      `full-set-stop-truncate-smoke-20260527-131708`, and
      `full-set-validation-smoke-20260527-134718`.
    - Known failure modes to preserve in validation/reporting: wash-out reverb
      or tail state leaking into later dry drop switches, outgoing placements
      continuing quietly after stop/handoff, repeated candidate fatigue from
      hearing the same pairs, bad semantic labels selecting awkward sections,
      and full-set WAV review costing too much time compared with short
      transition previews.
  - _Requirements: 1.1, 7.3_

- [x] 2. Move reusable full-set logic into a package module
  - Extract planner models, sequence selection, pair generation, merge, and
    validation from `tools/scripts/generate_full_set_poc.py` into
    `analysis/worker-python/src/autodj_analysis/full_set_planner.py`.
  - Keep the script as a thin wrapper or compatibility entry point.
  - Completed implementation notes:
    - Moved the existing reusable POC implementation into
      `autodj_analysis.full_set_planner`.
    - Recreated `tools/scripts/generate_full_set_poc.py` as a compatibility
      wrapper that imports and calls the package module.
    - Verified both `python -m autodj_analysis.full_set_planner --help` and the
      legacy wrapper `--help` path work.
  - _Requirements: 1.1, 6.1, 6.3_

- [x] 3. Add full-set planner CLI
  - Add an `autodj-analysis plan-set` or equivalent command.
  - Support plan-only, preview-only, render-only-from-existing-plan, and full
    plan-preview-render modes.
  - Add help text and CLI tests.
  - Completed implementation notes:
    - Added `autodj-analysis plan-set` as a supported entry point for the
      extracted planner.
    - Added `autodj-analysis preview-mixplan` as the preview-only/render
      existing full-set MixPlan entry point. The existing
      `autodj-analysis render-mixplan` remains the full render from existing
      plan command.
    - `plan-set --mode` now supports `plan-only`, `plan-preview`,
      `full-render`, and `full-plan-preview-render`.
    - Added CLI help coverage for `plan-set` and `preview-mixplan`.
  - _Requirements: 6.1, 6.2, 6.5_

- [x] 4. Implement candidate scoring and policy report
  - Add structured candidate records, scoring components, and rejection reasons.
  - Include key compatibility, BPM/stretch cost, nudge confidence, energy/gain
    verdict, semantic confidence, and recent transition history.
  - Write `candidate-report.json`.
  - Completed implementation notes:
    - Added per-step candidate records for both `drop-switch` and `wash-out`
      families without changing the existing selection order.
    - Candidate records now include key compatibility, BPM/stretch cost,
      section-count semantic proxy, recent transition history, pre-filter
      rejection reasons, attempt status, nudge summary, and gain verdict.
    - Full-set runs now write `candidate-report.json` and link it from
      `full-set-summary.json`.
    - Added focused tests for scoring, rejection reasons, report summaries,
      and selected-candidate post-pass metadata.
  - _Requirements: 2.1, 2.2, 2.5, 5.3_

- [x] 5. Add set-level policy controls
  - Add configurable limits for maximum consecutive wash-outs, stretch budget,
    candidate search width, repeated artist/title avoidance, and emergency
    fallback behavior.
  - Add tests for deterministic seeded selection.
  - Completed implementation notes:
    - Added `plan-set`/planner options for candidate search width, cumulative
      stretch budget, maximum consecutive wash-outs, immediate same-artist
      avoidance, and emergency repeated-artist fallback.
    - Candidate selection now enforces stretch budget, rough same-artist
      avoidance, candidate attempt limits, and repeated wash-out policy while
      preserving deterministic seeded ordering.
    - Candidate records include the active policy values and recent transition
      history so selection decisions are auditable.
    - Added focused tests for candidate search width, stretch budget, artist
      repeat filtering, and CLI help coverage.
  - _Requirements: 2.2, 2.3, 2.4, 2.6_

- [x] 6. Expand MixPlan validation
  - Validate placement stop truncation, wet drop-switch FX, incoming dry resets,
    supported tempo plans, unique ids, and resolvable assets.
  - Make validation mandatory before preview or full render.
  - Write `validation-report.json`.
  - Completed implementation notes:
    - Expanded full-set validation for duplicate asset/placement/transition ids,
      missing placement assets, optional asset-root resolution, unsupported
      tempo plans, tempo automation ramps, incoming dry/wet resets, outgoing
      stop truncation, and wet FX during drop-switch windows.
    - Validation now runs before render and writes `validation-report.json`;
      `full-set-summary.json` links the report.
    - Added focused validation tests covering a valid drop-switch, wet FX
      rejection, duplicate ids, and unsupported pitch-changing tempo plans.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 7. Implement transition preview plan extraction
  - Add code to crop a full-set MixPlan around each transition while preserving
    relevant placements, automation, assets, and enough FX pre-roll.
  - Add unit tests for timeline shifting and automation preservation.
  - Completed implementation notes:
    - Added `autodj_analysis.transition_preview.extract_transition_preview_plan`.
    - Preview extraction clips placements to the preview window, adjusts
      `sourceStartSeconds`/`sourceEndSeconds` using effective tempo ratio
      including `targetBpmBias`, shifts transition/annotation timeline fields,
      and injects preview-local load/play/stop commands.
    - Automation extraction preserves the control value active at preview start
      and shifts in-window keyframes while keeping effect parameters.
    - Added tests for tempo-aware placement clipping, automation preservation,
      synthetic transport commands, FX pre-roll window extension, and missing
      transition errors.
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 8. Render preview packs and write preview index
  - Add preview rendering mode.
  - Write `previews/index.json` with one row per transition and artifact paths.
  - Keep preview failures isolated from the rest of the run.
  - Completed implementation notes:
    - Added `autodj_analysis.transition_preview.write_transition_preview_pack`.
    - Added `autodj-analysis preview-mixplan <mix-plan> --out <dir>` for
      preview MixPlan extraction and `--render` for per-transition WAV renders.
    - Preview rows record status, transition/template metadata, window timing,
      output paths, and isolated errors; failures do not abort other previews.
    - Added CLI help coverage and preview-pack index tests.
  - _Requirements: 4.1, 4.3, 4.4, 4.5_

- [x] 9. Improve full-set summary report
  - Add sequence, transition counts, wash-out run lengths, stretch counts, key
    classes, nudge ranges, energy verdicts, validation status, and artifact
    links.
  - Add a place for later user verdict metadata.
  - Completed implementation notes:
    - Expanded `full-set-summary.json` with per-transition key classes, tempo
      deltas, stretch flags, gain verdicts, artifact links, statistics, and an
      empty `manualVerdicts` extension point.
    - Added set-level stats for transition counts, max wash-out run length,
      stretched drop-switch count, total stretch delta, key compatibility
      classes, nudge ranges, gain verdicts, and validation status.
    - Added focused statistics coverage in the full-set planner tests.
  - _Requirements: 5.1, 5.2, 5.4, 5.5_

- [x] 10. Generate 48-track preview pack checkpoint
  - Use the existing 48-song dubstep analysis root and audio folder.
  - Generate preview WAVs and reports without a full-set render.
  - Stop for user audition verdict before continuing.
  - Completed checkpoint:
    - Run root:
      `.autodj-cache/full-set-poc/spec011-48-preview-checkpoint-20260527-152619`.
    - Generated 47 transitions from 48 analyzed tracks: 21 drop-switch and 26
      wash-out transitions.
    - Validation passed; preview rendering produced 47/47 preview WAVs with
      zero preview failures.
    - User audition is the next gate before policy tuning or full-set render.
  - _Requirements: 4.1, 7.1, 7.3_

- [x] 11. Tune planner policy after preview verdict
  - Adjust scoring/policy only from concrete preview failures.
  - Avoid overfitting to one pair when the failure is semantic-label quality.
  - Regenerate a smaller preview pack for changed policy.
  - Completed tuning notes:
    - The initial 48-track checkpoint surfaced a concrete high-risk
      drop-switch failure mode: stretched or large-nudge drop switches could
      pass validation even when audition showed poor transient alignment.
    - Added safe-mode drop-switch policy controls:
      `--allow-drop-switch-tempo-stretch`/`--no-allow-drop-switch-tempo-stretch`
      and `--max-drop-switch-nudge-ms`.
    - The default full-set policy now rejects tempo-stretched drop switches and
      rejects drop switches whose absolute nudge exceeds 18 ms. Stretching can
      still be explicitly enabled for later experiments, but it is no longer
      part of the safe preview path.
    - Regenerated a smaller smoke pack at
      `.autodj-cache/full-set-poc/spec011-safe-drop-switch-smoke-20260527-155815`;
      user audition reported the safe pack sounded better.
    - Regenerated the 48-track safe preview checkpoint at
      `.autodj-cache/full-set-poc/spec011-48-safe-preview-checkpoint-20260527-160730`.
      It produced 47/47 rendered previews, validation passed, and selected 9
      exact-BPM drop switches plus 38 wash-outs. The full checkpoint is ready
      for manual audition before any full WAV render.
    - Known tradeoff: rejecting risky drop switches can create long wash-out
      runs when no safe exact-BPM/key-compatible drop switch is available.
      Treat that as a set-planning quality issue for the next policy pass, not
      a reason to re-admit unsafe drop switches.
  - _Requirements: 2.1, 2.3, 7.3_

- [x] 12. Render full-set checkpoint
  - Render one full-set WAV only after preview pack acceptance.
  - Stop for user verdict on song order, transition quality, wash-out frequency,
    and energy continuity.
  - Completed checkpoint:
    - Rendered from accepted preview MixPlan:
      `.autodj-cache/full-set-poc/spec011-drop-lookahead-gainv2-smoke-20260527-190044/mix-plan-full-set.json`.
    - Full-render output:
      `.autodj-cache/full-set-poc/spec011-full-render-checkpoint-20260527-2118/render/audition.wav`.
    - Render summary:
      `.autodj-cache/full-set-poc/spec011-full-render-checkpoint-20260527-2118/render/render-summary.json`.
    - Duration: 1280.4746 seconds, about 21 minutes 20 seconds.
    - Transition shape: 15 transitions, 9 drop switches, 6 wash-outs, including
      2 stretched drop switches from the accepted preview plan.
    - Manual full-set verdict is still the next listening gate; do not treat
      this as product-grade set acceptance until auditioned.
    - Follow-up correction: that full-render checkpoint exposed a planner merge
      bug that rewrote the accepted user-rendered wash-out sweep to the
      renderer's generated sweep URI. Future `plan-set` runs now use the
      configured sweep asset (`C:/Users/Brendan/Desktop/sweep.wav`) instead;
      do not use this checkpoint to judge final wash-out tone.
  - _Requirements: 7.2, 7.3_

- [x] 13. Update docs, runbooks, and steering
  - Document the accepted full-set planning workflow.
  - Update roadmap status and any PowerShell/WSL run commands.
  - Record known limitations and deferred next features.
  - Completed documentation updates:
    - Added `.codex/specs/011-full-set-planner-transition-qa/full-set-planner-runbook.md`
      with preview-first commands, render-from-accepted-MixPlan commands,
      latest checkpoint paths, accepted policy notes, and limitations.
    - Updated `.codex/specs/011-full-set-planner-transition-qa.md` with the
      accepted workflow and current checkpoint paths.
    - Updated `.codex/steering/05-dubstep-dj-strategy.md`,
      `.codex/steering/06-playback-engine.md`, and
      `.codex/steering/09-roadmap.md` with Spec 011 status, preview-first QA,
      SoundStretch/nudge/gain policy, and the remaining loudness limitation.
    - Updated the runbook and steering notes to require the user-rendered
      wash-out sweep asset for future full-set planning.
    - Post-completion performance update: routine batch analysis now uses the
      fast current-signal section backend, KeyFinder key backend, ffmpeg decode,
      2 workers, and inline `debug-waveform.json` generation. The
      `AutoDJTestDubstep` 48-track timing smoke measured 379.96 seconds; 3 and
      8 worker attempts were slower on the current Windows/WSL machine.
    - Post-completion full-set checkpoint update: rendered-domain drop-switch
      proof is now opt-in via `--prove-rendered-drop-switch-alignment` because
      the accepted audition path uses raw transient nudge and rendered proof can
      stall on individual candidates. Generated latest checkpoint at
      `.autodj-cache/full-set-poc/spec011-accepted-policy-full-checkpoint-20260529-092924`
      with 15 transitions: 12 drop switches and 3 wash-outs.
    - Post-completion transition-family cleanup: a same-key layered-drop
      variant was auditioned and rejected by ear. Its CLI/post-pass support,
      template fixture, schema enum entries, parser support, and generated
      smoke artifacts were removed so the accepted POC remains focused on
      drop switches and wash-outs.
  - _Requirements: 6.1, 7.4_

- [x] 14. Final verification
  - Run C++ build/tests if C++ planner/contract code changed.
  - Run focused Python tests and CLI tests.
  - Confirm generated cache/audio artifacts remain ignored.
  - Record verification results under this task.
  - Verification results:
    - Full Python suite:
      `python -m pytest analysis/worker-python/tests -q`
      passed with `354 passed, 9 warnings`.
    - Earlier focused Spec 011 test set passed with `68 passed`.
    - `git diff --check` passed.
    - `git check-ignore -v` confirmed generated `.autodj-cache/full-set-poc`
      WAV/preview artifacts are ignored by `.gitignore`.
    - C++ build/tests were not rerun because this final Spec 011 pass changed
      Python planner/renderer/docs only; no C++ source or schema files changed.
    - Post-completion performance verification:
      PowerShell syntax for `tools/run-transition-audition-batch.ps1` passed,
      and focused analysis/CLI tests passed with `79 passed`.
    - Post-completion planner verification:
      focused CLI/full-set planner tests passed with `60 passed`, and the
      latest 16-track full-set checkpoint rendered successfully.
    - Post-cleanup verification:
      focused CLI/full-set planner/transition preview/gain-planner tests
      passed with `72 passed`, and `git diff --check` passed with line-ending
      warnings only.
    - Final cleanup verification:
      full worker suite passed with `360 passed`; `autodj_playback_tests.exe`
      passed after rebuilding `autodj_playback_tests`; `git diff --check`
      passed with line-ending warnings only.
  - _Requirements: 3.6, 6.5, 7.4_
