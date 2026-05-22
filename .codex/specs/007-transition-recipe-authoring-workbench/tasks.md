# Implementation Plan

- [x] 1. Add Spec 007 docs and steering links
  - Add source spec, `kiro.json`, requirements, design, and this task list.
  - _Requirements: 8.4_

- [x] 2. Add recipe and authoring-session contracts
  - Add JSON schemas and stub examples for `transition-recipe.json` and
    `transition-authoring-session.json`.
  - Extend contract validation to include both new artifacts.
  - Added contract examples and verified with `autodj_contract_examples`.
  - _Requirements: 6.4, 7.1, 8.2_

- [x] 3. Add desktop authoring model utilities
  - Add bar/beat conversion, nearest-beat snapping, keyframe sorting, and
    authoring export helpers.
  - Add focused desktop tests for pure model behavior.
  - Added `autodj_desktop_transition_authoring_model_tests` for bar/beat labels,
    snapping, session/recipe export, and concrete MixPlan validation.
  - _Requirements: 2.4, 4.2, 4.3, 8.1_

- [x] 4. Load deck artifacts in the JUCE desktop app
  - Load audio, analyzed-track JSON, and debug-waveform JSON per deck.
  - Surface actionable errors for missing/invalid artifacts.
  - V1 uses explicit file pickers per deck and keeps debug-waveform JSON as the
    required visual source.
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 5. Replace placeholder app with native authoring UI
  - Add two stacked waveform views, fixed center playhead, scrub/zoom, semantic
    overlays, mixer controls, transport buttons, and status area.
  - Replaced the placeholder app with a JUCE authoring view; manual UX tuning is
    intentionally deferred to the acceptance checkpoint.
  - _Requirements: 2.1, 2.2, 2.3, 2.5, 3.1, 3.5_

- [x] 6. Implement realtime two-deck preview
  - Play each deck from its center source position.
  - Apply volume, EQ, and reverb-wet automation in preview.
  - Preview is implemented with two `AudioTransportSource`s and lightweight
    per-deck EQ/reverb processing for authoring feedback.
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 7. Implement automation lane editing
  - Right-click mixer controls to add keyframes.
  - Render lanes and allow beat-snapped keyframe dragging with modifier-based
    free micro-timing.
  - Shift-drag bypasses beat snapping for micro timing.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [x] 8. Implement exports
  - Load/export session JSON, concrete MixPlan JSON, and assisted-anchor recipe
    JSON.
  - Validate exports and surface warnings/errors.
  - Export helpers are covered by focused tests; concrete MixPlan export parses
    through the existing playback validator. The native app can reload exported
    authoring sessions by path.
  - _Requirements: 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3_

- [ ] 9. Manual acceptance checkpoint
  - Load two real analyzed songs, design a small automation move, preview it,
    export session/MixPlan/recipe, and ask the user to audition.
  - Record verdict before expanding transition families.
  - _Requirements: 8.4_
