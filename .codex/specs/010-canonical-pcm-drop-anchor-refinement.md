# Spec 010: Canonical PCM And Drop-Anchor Refinement

> Detailed implementation folder:
> `.codex/specs/010-canonical-pcm-drop-anchor-refinement/`

## Overview

Build a DJ-grade timing branch for AutoDJ focused on the highest-risk point in
the current system: exact drop-start anchor timing. This spec uses the two
research reports in `C:\Users\Brendan\Downloads` as a reset point. The goal is
to replace ad hoc "nearest transient" experiments with a disciplined audio
timeline and signal-processing pipeline:

- decode once to canonical PCM and use that same timeline everywhere timing
  matters;
- extract high-SNR rhythmic views from HPSS/percussive, multiband, phase, and
  reassigned-time features;
- build a drop-anchor candidate dataset from Rekordbox-labeled truth;
- rank drop transient candidates with measurable features before using them in
  drop-switch transition planning;
- evaluate with millisecond-level DJ metrics and manual audition gates.

This spec is intentionally scoped around drop anchors, not full semantic section
recognition. For now, Rekordbox XML labels remain the semantic truth source.
AutoDJ's in-house job is to translate those semantic timestamps onto its own
PCM/beatgrid timeline and refine the exact transient that should be used for
mixing.

## Why Now

Spec 005 proved that general semantic models can find useful arrangement
boundaries but are not reliable enough for exact dubstep build/drop labels.
Spec 006 and Spec 007 proved that drop switches can sound excellent when the
selected anchors are right and the incoming deck is nudged correctly. Spec 008
gave AutoDJ an in-house Camelot key ensemble. Spec 009 added pitch-preserving
tempo control with SoundStretch as the current POC backend.

The remaining blocker is not one more mix-plan trick. It is the exact timing
layer that decides where the first drop transient really is. If that anchor is
wrong by only a few milliseconds, the transition sounds weaker; if it is wrong
by a beat or a wrong nearby transient, the transition fails completely.

## Research Synthesis

Both reports converge on the same engineering direction:

- BPM estimation and beat placement are different problems.
- Standard MIR metrics are too forgiving for DJ use.
- MP3 decoder differences can create offsets large enough to ruin beat-grid
  alignment, so canonical PCM is mandatory.
- ML section models are useful for neighborhoods and labels, but final DJ-grade
  timing still needs deterministic PCM-domain refinement.
- "Snap to the nearest waveform transient" is too weak.
- The better classical path is high-SNR rhythmic representation, global
  metrical context, and local sub-frame transient refinement.

The most useful non-ML techniques to try here are:

- HPSS percussive isolation.
- Multiband onset envelopes: kick, body/snare, hat/noise.
- SuperFlux-style spectral flux with `center=False` timing.
- Complex-domain or phase-based onset cues where practical.
- Reassigned-time spectrogram features for local timing correction.
- Onset backtracking to the pre-attack energy minimum.
- Matched filtering or cross-correlation around drop anchors.
- Global beatgrid phase fitting around strong metrical anchors, not independent
  local beat snapping.

The spec deliberately does not start by training a custom ML model on the
current 48-song set. That set is too small for a robust model. It is valuable as
a regression and audition set, and it should become the seed for a drop-candidate
dataset that can support a model later.

## Initial Reference Links

- All-In-One MP3 offset warning and structure analyzer:
  https://github.com/mir-aidj/all-in-one
- Raveform EDM structure dataset:
  https://mir-aidj.github.io/raveform/
- Raveform dataset article:
  https://reference-global.com/article/10.5334/tismir.288
- librosa onset strength `center` behavior:
  https://librosa.org/doc/main/generated/librosa.onset.onset_strength.html
- librosa HPSS:
  https://librosa.org/doc/main/generated/librosa.effects.hpss.html
- librosa reassigned spectrogram:
  https://librosa.org/doc/main/generated/librosa.reassigned_spectrogram.html
- aubio onset methods:
  https://aubio.org/manual/latest/cli.html
- madmom DBN beat tracking:
  https://madmom.readthedocs.io/en/v0.14.1/modules/features/beats.html

## Relationship To Spec 009

Spec 009 previously called key shifting the immediate Spec 010 follow-up. This
spec intentionally supersedes that sequencing because drop-anchor timing is now
the project-critical risk. Key shifting remains important, but it should move
behind this timing work.

## Completion Criteria

- Canonical PCM artifacts are generated and used consistently by timing,
  waveform, nudge, and render/audition paths.
- Timing-sensitive feature extraction avoids hidden frame-centering offsets.
- Drop candidates around Rekordbox-labeled drops are exported with interpretable
  feature columns and strict error metrics.
- A new drop-anchor scorer is compared against the current raw transient nudge
  on the 48-track set.
- At least one batch of same-BPM drop-switch auditions is generated from the new
  refined anchors.
- User audition verdicts are recorded before replacing the current default.
- Documentation records which transforms improved audible alignment and which
  were dead ends.

