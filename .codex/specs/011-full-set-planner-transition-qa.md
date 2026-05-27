# Spec 011: Full-Set Planner And Transition QA

> Detailed implementation folder:
> `.codex/specs/011-full-set-planner-transition-qa/`

## Overview

Promote the current full-set POC flow into a dependable planning and review
workflow. Specs 006 through 010 produced the main toolbox:

- Rekordbox XML labels as the trusted semantic oracle for now.
- In-house BPM, beatgrid, key detection, and Camelot compatibility.
- SoundStretch tempo matching for pitch-preserving drop switches.
- Canonical PCM/drop-anchor refinement and the selected nudge path.
- Drop-switch and wash-out transition fragments.
- A full-set generator script that can chain 48 songs into one rendered WAV.

The next risk is no longer a single DSP primitive. The risk is set-level
decision quality: choosing the right next song, choosing drop-switch versus
wash-out, avoiding stale state leaks, avoiding too many emergency wash-outs in a
row, and making it easy to inspect bad transitions before spending time on a
full render.

## Goals

- Promote `tools/scripts/generate_full_set_poc.py` into a supported planning
  command or well-documented tool path.
- Make full-set planning deterministic, configurable, and explainable.
- Generate short transition preview WAVs and JSON reports before rendering a
  60-90 minute set.
- Add set-level constraints for key, BPM/stretch, energy, artist repetition,
  transition variety, and wash-out spacing.
- Add validation gates that fail before render if a plan can leak audio, carry
  wet FX into drop switches, or leave ambiguous deck state.
- Preserve the working drop-switch and wash-out behavior rather than rewriting
  transition DSP in this spec.

## Non-Goals

- Do not train semantic drop detection in this spec.
- Do not add new transition families beyond optional hard-cut/emergency
  fallback metadata.
- Do not implement key shifting; that remains a future toolbox feature.
- Do not build a full library browser or realtime DJ UI.
- Do not remove Rekordbox semantic labels as the trusted POC oracle.

## Current Baseline

The latest full-set path lives in `tools/scripts/generate_full_set_poc.py`.
It selects tracks from analyzed artifacts, prefers compatible drop-switches,
falls back to wash-out transitions, validates dry drop-switch windows, truncates
outgoing placements at stop time, and renders via `autodj-analysis
render-mixplan`.

Known pain points:

- Pair choice is still more script-like than product-like.
- User feedback happens after listening to a huge WAV instead of a transition
  preview pack.
- Transition rejections are not summarized well enough for planning decisions.
- There is no structured set-level scoring or user verdict loop.
- Full renders are expensive, so bad decisions should be caught earlier.

## Completion Criteria

- A set planner command/tool can generate a plan, transition previews, and a
  full-set report from an analyzed folder.
- Reports explain why each track/transition was selected, rejected, or deferred.
- Preview WAVs make it practical to audit transitions before full rendering.
- Hard validations catch stop-placement overruns, wet drop-switch FX, missing
  assets, duplicate deck state, and unsupported tempo plans before render.
- A manual checkpoint records user verdicts on a generated preview pack and one
  full-set render.
- Steering docs and runbooks describe the accepted workflow and remaining
  limitations.

