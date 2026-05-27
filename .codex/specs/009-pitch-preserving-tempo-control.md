# Spec 009: Pitch-Preserving Tempo Control

> Detailed implementation folder:
> `.codex/specs/009-pitch-preserving-tempo-control/`

## Overview

Add pitch-preserving tempo control as a first-class AutoDJ tool. The goal is to
let the engine and offline renderer play a track at a target BPM without
changing musical key, then let the Dubstep DJ planner use that capability to
create more valid transition candidates.

This is intentionally scoped before full set planning. A planner that can only
drop-switch exact native BPM matches is too constrained; a planner that can
tempo-match within a configurable window can choose from a much larger candidate
graph while preserving key compatibility decisions from Spec 008.

## Why Now

Spec 006 and Spec 007 proved that drop switches require tight rhythmic
alignment. Spec 008 added in-house Camelot key detection. The next fundamental
DJ primitive is Master-Tempo-style playback: change the effective BPM while
keeping pitch/key stable.

This gives later set planning a practical toolbox:

- exact native BPM drop switch when available;
- tempo-matched drop switch when the pair is close enough;
- reverb/impact exit when tempo matching is not musically safe;
- future key-shifted transitions after Spec 010.

## Rekordbox Reference

Rekordbox/CDJ Master Tempo is the user-facing reference for quality. Public
documentation confirms the behavior: playback speed changes while pitch remains
fixed. Public AlphaTheta/Pioneer materials do not disclose the internal
algorithm or SDK.

The practical goal is therefore not to clone Rekordbox internals. The goal is
to evaluate strong time-stretch libraries until rendered transitions meet the
same listening standard on dense dubstep material.

## Candidate Backend Families

Evaluate realistic local/native candidates:

- Rubber Band Library: high-quality C++ time-stretch/pitch-shift library with
  CLI utility, GPL/commercial licensing, and a strong POC path.
- zplane elastique SDK: commercial professional time-stretch/pitch-shift family
  widely associated with pro DAW quality; evaluate licensing/access if free
  candidates are not good enough.
- Superpowered TimeStretching: cross-platform/mobile-focused commercial C++
  SDK with real-time time-stretching and pitch-shifting.
- Signalsmith Stretch: MIT, header-only C++ pitch/time library; attractive for
  native integration and licensing, but must be auditioned on full-mix dubstep.
- SoundTouch: LGPL, simple and accessible tempo/pitch/rate library; useful as a
  baseline and fallback quality comparison.
- Zynaptiq ZTX: commercial C/C++ SDK for high-quality time-stretching,
  pitch-shifting, and formant work; evaluate only if needed.

## Planning Policy

There should be no hard engine-level cap on requested stretch amount. If a
manual MixPlan asks for a large tempo ratio, the backend should either render it
or emit an explicit backend limitation/error.

Planner candidate selection does need a musical gate.

Default POC policy:

- `maxTempoAdjustmentBpmPerDeck = 10.0`
- `maxTotalTempoBridgeBpm = 20.0`
- exact normalized BPM equality remains required at the moment of a drop-switch
  overlap after tempo planning is applied.

Example:

- Song A native/current normalized BPM: `140`
- Song B native normalized BPM: `160`
- With a `10 BPM` per-deck window, planner may ramp Song A up to `150` and
  start Song B stretched down to `150`.
- The transition is eligible because both decks meet at an exact shared
  transition BPM and neither deck moves more than `10 BPM` from its native or
  current planned BPM.

The default values are configurable because the musical tolerance may prove
smaller for dense dubstep.

## Follow-On Spec 010

The next fundamental tool after this spec is pitch/key shifting without changing
BPM. That should be its own spec because it has different musical rules:

- tempo stays fixed;
- key/Camelot changes by semitone steps;
- formant/stereo/transient quality becomes the main risk;
- planner decisions must account for both detected key confidence and audible
  pitch-shift quality.

Spec 009 may choose a backend that can also pitch shift, but it should not
implement planner key shifting yet.

## Initial Research References

- Rekordbox/CDJ Master Tempo behavior:
  https://www.pioneer-dj.de/wp-content/uploads/2024/02/Pioneer-DJ-CDJ-3000-User-Manual.pdf
- AlphaTheta/Pioneer Master Tempo feature page:
  https://www.pioneerdj.com/es-419/product/features/generic/master-tempo/
- Rubber Band Library:
  https://www.breakfastquay.com/rubberband/index.html
- Rubber Band technical notes:
  https://www.breakfastquay.com/rubberband/technical.html
- SoundTouch README:
  https://www.surina.net/soundtouch/README.html
- SoundTouch license:
  https://www.surina.net/soundtouch/license.html
- zplane elastique product family:
  https://products.zplane.de/products/elastiquepitch/
- Superpowered Time Stretching:
  https://superpowered.com/time-stretching
- Signalsmith Stretch:
  https://github.com/Signalsmith-Audio/signalsmith-stretch
- Zynaptiq ZTX:
  https://www.zynaptiq.com/ztx/

## Completion Criteria

- At least two local tempo-stretch candidates are genuinely runnable and
  auditioned.
- A selected POC backend can render source audio at a target BPM without
  changing pitch.
- MixPlan contracts can express tempo targets/ramps and preserve-pitch intent.
- The offline renderer applies tempo stretching before existing EQ/effects
  automation.
- Beatgrid/source-time mapping remains deterministic after stretch.
- Transient nudge still works after tempo matching.
- The Dubstep DJ planner can generate stretched drop-switch candidates within a
  configurable BPM window.
- Audition artifacts compare native-BPM, stretched, and fallback transitions.
- Documentation records quality, licensing, runtime, and mobile/native risks.

