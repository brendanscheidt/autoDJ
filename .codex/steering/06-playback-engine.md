# Playback Engine

## Purpose

The playback engine is a deterministic executor of a `MixPlan`. It should feel
like a programmable set of CDJs and a mixer:

- Decks can load, play, pause, stop, seek, and loop.
- The mixer exposes volume, EQ, filter, effects, and crossfader controls.
- Automation keyframes change controls over the set timeline.

The engine should not contain genre logic or decide what to play next.

## Deck Model

Each deck should support:

- Loaded track or stem.
- Source position.
- Timeline start.
- Playback state.
- Tempo/rate.
- Loop state.
- Gain/volume.
- Per-deck EQ.
- Per-deck effects sends or wet controls.

The MVP UI can show two decks, but the engine data model should allow more than
two decks. Future acapella/stem layering may need a third or fourth deck.

## Mixer Model

Controls:

- `volume`
- `eqLow`
- `eqMid`
- `eqHigh`
- `filter`
- `reverbWet`
- `reverbTailGain`
- `reverbDecaySeconds`
- `echoWet`
- `tempo`
- `crossfader`

MVP ranges are normalized floats. Later, EQ should move to dB-aware ranges.

Suggested signal flow per deck:

```text
AudioSource
  -> Tempo/Pitch stage
  -> Loop stage
  -> EQ
  -> Filter
  -> Effects send/wet
  -> Volume
  -> Mixer sum
  -> Master limiter
  -> Output
```

The exact order can evolve, but automation semantics should remain stable.
For CDJ-style exits, reverb must support post-fader tail behavior: dry deck
volume may cut to zero while the already-fed reverb return continues to decay.
Reverb quality is still POC-level; authored recipes and rendered auditions are
the source of truth for tuning.

## Automation

Automation is represented as keyframes on controls.

Interpolation modes:

- `hold`
- `linear`
- `smoothstep`
- `exponential`

Rules:

- If no keyframe exists for a control, use its default value.
- If playback seeks, automation state must be recomputed deterministically.
- Conflicting automation on the same control/time range should be rejected or
  resolved during plan validation.
- Automation evaluation must be real-time safe.

## Timeline Execution

The engine consumes sorted `DeckCommand` events.

Execution phases:

1. Validate all referenced tracks/stems exist.
2. Preload audio needed near the playhead.
3. Start a transport clock.
4. Dispatch commands whose `at` time has been reached.
5. Evaluate automation for the current timeline time.
6. Render deck audio and mix output.

The transport clock is the authority for set timeline time. Deck source time is
derived from deck playback state, tempo, loops, and seeks.

## Real-Time Safety

The audio callback must avoid:

- Blocking file I/O.
- Network calls.
- Python calls.
- Locks that can block on UI or worker threads.
- Unbounded heap allocation.
- JSON parsing.
- Heavy logging.
- Analysis or model inference.

Use background threads for:

- File scanning.
- Decoding/preloading.
- Waveform generation.
- Analysis worker invocation.
- Plan generation.

Use lock-free queues or bounded message queues where UI/control events need to
cross into the audio engine.

## Audio Loading

MVP options:

- Full file decode into memory for short test fixtures.
- Buffered streaming for real tracks.

The architecture should move toward buffered streaming. Dubstep tracks are often
large enough that loading many full tracks into memory is not a good long-term
mobile assumption.

## Beat Sync And Tempo

The first MVP behavior required exact normalized BPM equality for second-build
drop switches. Spec 009 expands this with pitch-preserving tempo control:

- Engine/manual MixPlans can request target BPM or tempo ratio changes while
  preserving pitch.
- The automatic planner gates candidates with a configurable BPM window rather
  than an engine-level hard cap.
- Current POC generated auditions use one-sided incoming SoundStretch matching:
  an incoming deck may be rendered to the outgoing deck's BPM when the delta is
  inside the configured gate. Default gate: `10 BPM`.
- Midpoint bridge planning, where both decks move toward a shared middle BPM,
  remains deferred because dynamic tempo ramps are not yet accepted by the
  offline renderer.
- Prefer simple reverb/hard-cut exits when tempo matching is unavailable or
  quality diagnostics are poor.
- Store desired deck `tempo` automation and preserve-pitch intent in the plan.

Time-stretching stays behind an interface so the backend can be swapped.
SoundStretch is the accepted POC backend after manual auditions; Rubber Band is
kept as an experimental comparison because it reduced perceived loudness and
bass fullness in the tested dubstep material. The offline renderer is allowed
to prove quality first; native realtime integration can follow after the
selected backend is accepted by audition.

## Looping

Loop commands specify:

- Source start time.
- Length in beats.
- Deck.
- Timeline activation time.

The engine resolves loop length from the track beat grid. If no reliable beat
grid is available, the plan should not use loop-tighten templates.

Loop transitions must be sample-stable. A loop that drifts will ruin the most
important MVP transition style.

## Validation

Before playback, validate:

- Schema version supported.
- All tracks and stems resolve.
- Commands are sorted or sortable.
- Deck numbers are valid.
- Load happens before play.
- Automation controls and values are valid.
- No impossible loop lengths.
- Transition edge references exist.
- Timeline values are non-negative and finite.

Warnings should include:

- Low-confidence analysis used in complex transition.
- Unknown stem quality.
- Tempo delta above recommended threshold.
- Overlapping dense vocal regions.

## Testing

Core playback tests should include:

- Keyframe interpolation.
- Seek recomputes automation state.
- Command ordering.
- Loop state changes.
- Plan validation rejects bad references.
- No-crash playback of synthetic fixtures.

Later audio quality tests should include:

- Render known fixture plan to WAV.
- Compare timing of impulses against expected sample positions.
- Verify loop boundaries remain stable.
- Verify automation reaches expected values at expected times.
