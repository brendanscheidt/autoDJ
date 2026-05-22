# Spec 007: Native Transition Recipe Authoring Workbench

> Detailed implementation folder:
> `.codex/specs/007-transition-recipe-authoring-workbench/`

## Overview

Build a native JUCE two-deck transition authoring workbench for designing
AutoDJ transition recipes by ear. The workbench loads two tracks plus their
AutoDJ analysis artifacts, renders beatgrid/semantic waveform views, previews
volume/EQ/reverb automation in realtime, and exports concrete MixPlans,
generic transition recipes, and authoring sessions.

This replaces hand-authored text templates as the primary transition design
workflow. Text transition sheets remain a developer fallback, not the target
authoring surface.

## Primary Goals

- Load audio, `analyzed-track.json`, and `debug-waveform.json` explicitly for
  each of two decks.
- Show stacked RGB waveforms with fixed center playhead, beat/bar markers,
  semantic sections, cue points, and current bar/beat labels.
- Let the user scrub each deck by dragging, zoom with the mouse wheel, and
  preview each deck individually or both decks together.
- Provide per-deck volume, low/mid/high EQ, and reverb-wet controls.
- Create and edit beat-snapped keyframes on automation lanes.
- Export exact two-song MixPlans, reusable assisted-anchor recipes, and
  reloadable authoring sessions.

## Explicit Non-Goals

- No HTML/Electron/Tauri workbench.
- No stem controls in v1.
- No pitch-preserving time-stretch or BPM matching in v1.
- No library browser or automatic folder scanning in v1.
- No fully automatic generic recipe inference; generic recipe export requires
  user-selected anchors.

