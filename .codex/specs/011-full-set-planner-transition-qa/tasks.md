# Implementation Plan

- [ ] 1. Confirm scope and current baseline
  - Read `kiro.json`, requirements, design, tasks, and required steering docs.
  - Record the latest accepted full-set artifacts and known failure modes:
    reverb state leaks, placement overruns, repeated pair fatigue, and high cost
    of full WAV review.
  - _Requirements: 1.1, 7.3_

- [ ] 2. Move reusable full-set logic into a package module
  - Extract planner models, sequence selection, pair generation, merge, and
    validation from `tools/scripts/generate_full_set_poc.py` into
    `analysis/worker-python/src/autodj_analysis/full_set_planner.py`.
  - Keep the script as a thin wrapper or compatibility entry point.
  - _Requirements: 1.1, 6.1, 6.3_

- [ ] 3. Add full-set planner CLI
  - Add an `autodj-analysis plan-set` or equivalent command.
  - Support plan-only, preview-only, render-only-from-existing-plan, and full
    plan-preview-render modes.
  - Add help text and CLI tests.
  - _Requirements: 6.1, 6.2, 6.5_

- [ ] 4. Implement candidate scoring and policy report
  - Add structured candidate records, scoring components, and rejection reasons.
  - Include key compatibility, BPM/stretch cost, nudge confidence, energy/gain
    verdict, semantic confidence, and recent transition history.
  - Write `candidate-report.json`.
  - _Requirements: 2.1, 2.2, 2.5, 5.3_

- [ ] 5. Add set-level policy controls
  - Add configurable limits for maximum consecutive wash-outs, stretch budget,
    candidate search width, repeated artist/title avoidance, and emergency
    fallback behavior.
  - Add tests for deterministic seeded selection.
  - _Requirements: 2.2, 2.3, 2.4, 2.6_

- [ ] 6. Expand MixPlan validation
  - Validate placement stop truncation, wet drop-switch FX, incoming dry resets,
    supported tempo plans, unique ids, and resolvable assets.
  - Make validation mandatory before preview or full render.
  - Write `validation-report.json`.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [ ] 7. Implement transition preview plan extraction
  - Add code to crop a full-set MixPlan around each transition while preserving
    relevant placements, automation, assets, and enough FX pre-roll.
  - Add unit tests for timeline shifting and automation preservation.
  - _Requirements: 4.1, 4.2, 4.3_

- [ ] 8. Render preview packs and write preview index
  - Add preview rendering mode.
  - Write `previews/index.json` with one row per transition and artifact paths.
  - Keep preview failures isolated from the rest of the run.
  - _Requirements: 4.1, 4.3, 4.4, 4.5_

- [ ] 9. Improve full-set summary report
  - Add sequence, transition counts, wash-out run lengths, stretch counts, key
    classes, nudge ranges, energy verdicts, validation status, and artifact
    links.
  - Add a place for later user verdict metadata.
  - _Requirements: 5.1, 5.2, 5.4, 5.5_

- [ ] 10. Generate 48-track preview pack checkpoint
  - Use the existing 48-song dubstep analysis root and audio folder.
  - Generate preview WAVs and reports without a full-set render.
  - Stop for user audition verdict before continuing.
  - _Requirements: 4.1, 7.1, 7.3_

- [ ] 11. Tune planner policy after preview verdict
  - Adjust scoring/policy only from concrete preview failures.
  - Avoid overfitting to one pair when the failure is semantic-label quality.
  - Regenerate a smaller preview pack for changed policy.
  - _Requirements: 2.1, 2.3, 7.3_

- [ ] 12. Render full-set checkpoint
  - Render one full-set WAV only after preview pack acceptance.
  - Stop for user verdict on song order, transition quality, wash-out frequency,
    and energy continuity.
  - _Requirements: 7.2, 7.3_

- [ ] 13. Update docs, runbooks, and steering
  - Document the accepted full-set planning workflow.
  - Update roadmap status and any PowerShell/WSL run commands.
  - Record known limitations and deferred next features.
  - _Requirements: 6.1, 7.4_

- [ ] 14. Final verification
  - Run C++ build/tests if C++ planner/contract code changed.
  - Run focused Python tests and CLI tests.
  - Confirm generated cache/audio artifacts remain ignored.
  - Record verification results under this task.
  - _Requirements: 3.6, 6.5, 7.4_

