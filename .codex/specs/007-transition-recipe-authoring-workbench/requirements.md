# Requirements Document

## Introduction

This spec adds a native desktop workbench for designing transition recipes with
two analyzed tracks, realtime playback preview, beat-snapped automation lanes,
and exports for concrete MixPlans, generic recipes, and authoring sessions.

## Requirement 1: Two-Deck Artifact Loading

**User Story:** As a transition author, I want to load audio and AutoDJ
analysis artifacts onto two decks, so I can build transitions from the same
metadata the planner will use.

### Acceptance Criteria

1. WHEN loading a deck THEN the UI SHALL require an audio file,
   `analyzed-track.json`, and `debug-waveform.json`.
2. WHEN the debug waveform artifact is missing or invalid THEN the UI SHALL
   show an actionable error and not fake a substitute waveform.
3. WHEN artifacts load successfully THEN the UI SHALL display track title,
   normalized BPM, current bar/beat, beat count, section count, and cue count.
4. WHEN track IDs differ between loaded artifacts THEN the UI SHALL warn the
   user before export.

## Requirement 2: Rekordbox-Like Waveform Navigation

**User Story:** As a DJ, I want two stacked waveforms with a fixed center play
bar, so I can align transition points visually.

### Acceptance Criteria

1. WHEN a deck is loaded THEN the UI SHALL render its RGB debug waveform.
2. WHEN the user drags a waveform THEN the deck SHALL scrub under the fixed
   center playhead.
3. WHEN the user scrolls over a waveform THEN the deck SHALL zoom around the
   center playhead.
4. WHEN the center line crosses the beatgrid THEN the UI SHALL show bar/beat
   labels where the first beatgrid beat is `1.1`.
5. WHEN sections and cue points exist THEN the waveform SHALL show semantic
   markers for them.

## Requirement 3: Realtime Preview And Mixer Controls

**User Story:** As a transition author, I want to hear control changes live, so
I can judge whether a transition actually sounds good.

### Acceptance Criteria

1. WHEN the user presses play A, play B, or play both THEN audio SHALL start
   from each deck's current center-line source position.
2. WHEN playback runs THEN the UI SHALL update playheads and bar/beat labels.
3. WHEN automation exists THEN volume, EQ, and reverb-wet controls SHALL be
   applied during preview.
4. WHEN controls are adjusted manually THEN the realtime preview SHALL reflect
   the current values unless an active automation keyframe overrides them.
5. WHEN stop is pressed THEN both decks SHALL stop without changing loaded
   artifacts or keyframes.

## Requirement 4: Automation Lane Editing

**User Story:** As a transition author, I want beat-snapped keyframes for deck
controls, so I can design repeatable transition moves.

### Acceptance Criteria

1. WHEN the user right-clicks a volume, EQ, or reverb control and selects
   `Add keyframe` THEN a lane SHALL appear for that deck/control if needed.
2. WHEN a keyframe is created THEN its time SHALL snap to the nearest beatgrid
   beat for that deck.
3. WHEN editing a lane THEN keyframes SHALL be draggable in time and value.
4. WHEN dragging without the free-move modifier THEN keyframe time SHALL snap
   to beatgrid beats.
5. WHEN dragging with the free-move modifier THEN keyframe time MAY move
   between beats for micro-timing.
6. WHEN a lane is rendered THEN it SHALL show beat/bar grid context and values
   from `0.0` to `1.0`.

## Requirement 5: Export Specific MixPlans

**User Story:** As a transition author, I want to export the exact transition I
just designed, so it can be rendered and auditioned through the existing
MixPlan tooling.

### Acceptance Criteria

1. WHEN exporting a specific transition THEN the output SHALL be a valid
   MixPlan JSON document.
2. WHEN exporting THEN deck source positions, loaded audio paths, transition
   family, selected anchors, and automation keyframes SHALL be preserved.
3. WHEN the exported MixPlan is parsed by existing validation THEN it SHALL
   pass or show actionable validation errors.

## Requirement 6: Export Assisted-Anchor Recipes

**User Story:** As a transition author, I want to tag semantic anchors and
export a reusable recipe, so the planner can later apply my transition idea to
other compatible songs.

### Acceptance Criteria

1. WHEN exporting a generic recipe THEN the user SHALL have selected required
   anchors for the chosen transition family.
2. WHEN keyframes can be expressed relative to selected anchors THEN exported
   recipe keyframes SHALL use anchor-relative beat/bar offsets.
3. WHEN a keyframe cannot be expressed cleanly THEN export SHALL warn rather
   than silently guessing.
4. WHEN a recipe is exported THEN it SHALL include semantic requirements,
   exact-BPM requirement, future Camelot/key placeholder, energy notes, and
   human notes.

## Requirement 7: Session Save And Reload

**User Story:** As a transition author, I want to reopen an edit session, so I
can keep refining a transition without recreating state.

### Acceptance Criteria

1. WHEN saving a session THEN loaded file paths, deck center positions, zoom,
   mixer state, lanes, keyframes, selected anchors, and transition metadata
   SHALL be written.
2. WHEN loading a session THEN the workbench SHALL restore the same visible
   state and validate referenced files.
3. WHEN a referenced file is missing THEN the UI SHALL report the exact missing
   path and keep the rest of the session readable.

## Requirement 8: Verification

**User Story:** As a maintainer, I want tests for the authoring model and
contract exports, so transition authoring remains deterministic.

### Acceptance Criteria

1. WHEN bar/beat math changes THEN unit tests SHALL verify conversion and
   nearest-beat snapping.
2. WHEN session or recipe schemas change THEN contract examples SHALL validate.
3. WHEN MixPlan export changes THEN tests SHALL parse the exported plan with
   current MixPlan validation.
4. WHEN UI code changes THEN desktop tests SHALL pass.
