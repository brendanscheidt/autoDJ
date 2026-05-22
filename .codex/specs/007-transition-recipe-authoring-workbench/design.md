# Design Document

## Overview

The workbench is implemented in the existing JUCE desktop app. It owns authoring
state and realtime preview, but exports durable JSON artifacts consumed by the
existing AutoDJ plan/render pipeline.

```text
audio + analyzed-track.json + debug-waveform.json
  -> native two-deck authoring state
  -> realtime JUCE preview
  -> session JSON / transition recipe JSON / MixPlan JSON
```

## Data Model

The desktop app keeps a UI-focused model:

- `DeckArtifact`: audio path, analyzed path, debug waveform path, track id,
  title, normalized BPM, beat times, sections, cue points, RGB waveform points.
- `DeckViewState`: center source seconds, zoom seconds, current mixer values.
- `AutomationLane`: deck id, control name, sorted keyframes.
- `AuthoringAnchor`: symbolic name, deck id, source seconds, bar/beat label.
- `AuthoringSession`: transition family, deck states, lanes, anchors, notes.

The model should be serializable to `transition-authoring-session.json` without
requiring real audio bytes inside the JSON.

## UI Layout

- Top toolbar: deck file load buttons, play A, play B, play both, stop, export
  session, export specific MixPlan, export recipe.
- Waveform stack: deck A waveform, deck B waveform, fixed center playhead, beat
  and semantic overlays, current bar/beat label.
- Mixer strip: deck A and deck B volume faders, low/mid/high EQ knobs, and
  reverb-wet knobs.
- Automation editor: one lane per deck/control with keyframes and beat grid.
- Status area: validation warnings and export results.

## Realtime Preview

Use JUCE audio primitives in the desktop app:

- `AudioFormatManager` and `AudioTransportSource` for file playback.
- Per-deck processing for volume, low/mid/high EQ approximation, and reverb wet.
- Automation is evaluated from source time for each deck during preview.
- V1 does not time-stretch, pitch-lock, or stem separate.

The preview engine is an authoring aid. The exported MixPlan remains the
deterministic playback artifact.

## Export Behavior

Authoring convention:

- Future concrete song-pair transitions should be written first as
  `transition-authoring-session.json` files that the native workbench can load.
  This keeps the automation inspectable and tweakable by ear before the
  transition is promoted into a reusable recipe or rendered MixPlan.
- Generated sessions may use per-deck `previewStartDelaySeconds` to represent
  staggered starts, such as a reverb exit where deck B starts after deck A's dry
  cut while deck A's effect tail continues.

Specific MixPlan export:

- Writes contract-shaped `MixPlan` JSON.
- Uses current deck center/source positions and automation lanes.
- Emits track assets, two placements, one transition edge, load/play commands,
  and automation commands.
- Runs exported JSON through existing MixPlan parser/validation where possible.

Generic recipe export:

- Requires assisted anchors selected by the user.
- Converts keyframes to anchor-relative source beat offsets.
- Includes warnings for unsnappable or unsupported keyframes.
- Uses `transition-recipe.schema.json`.

Session export:

- Uses `transition-authoring-session.schema.json`.
- Stores only paths and authoring state, not audio samples.

## Error Handling

Errors should be specific and visible:

- missing audio/analyzed/debug file;
- invalid JSON;
- missing beat grid;
- missing debug waveform points;
- mismatched track IDs;
- unsupported recipe anchor set;
- keyframe not expressible relative to anchors.

Warnings should not block session save, but should block recipe/MixPlan export
when the exported artifact would be invalid.
