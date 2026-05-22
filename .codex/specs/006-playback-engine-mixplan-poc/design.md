# Design Document

## Overview

Spec 006 turns selected analysis metadata into an executable transition plan.
The first implementation should avoid a full automatic set planner. It should
prove a narrow loop:

```text
analyzed-track.json for song_a and song_b
  -> transition template selection
  -> MixPlan JSON
  -> plan validation and scheduling
  -> audible/manual audition artifact
  -> user verdict
```

The intended result is a deterministic, inspectable proof that the app can
switch from one dubstep track to another using beatgrid and section metadata.

## Existing Code Context

- `core/contracts/schemas/mix-plan.schema.json` already defines placements,
  transitions, load/play/stop/seek/loop commands, and automation commands for
  `volume`, `eqLow`, `eqMid`, `eqHigh`, `filter`, `reverbWet`, `echoWet`,
  `tempo`, and `crossfader`.
- `core/playback` currently has a placeholder `PlaybackEngine` with transport
  state and plan-loading validation stubs.
- `core/dj` currently has `DubstepDJStrategy::generatePlanPlaceholder()`.
- `tools/analysis-debug-viewer.html` is for analysis debugging, not final
  playback. It may remain useful for checking chosen cue/section positions.

## Core Data Model

### Track Analysis Summary

Planner code should build a small internal summary from each
`analyzed-track.json`:

- `trackId`
- `sourceUri` or resolved local audio path if available
- `tempo.normalizedBpm`
- beat times
- ordered `build` sections
- ordered `drop` sections
- cue points
- confidence/warnings

For Spec 006, a measure is 4 beats. If a later analysis version emits reliable
downbeats or time signatures, that can replace the fixed assumption.

### Transition Template Result

Template selection should produce:

- technique id;
- selected source sections and cue points;
- calculated measure counts;
- source start/end seconds for each track;
- timeline start/drop/end seconds;
- automation keyframes;
- debug reasons;
- risk flags.

This result is then converted to contract-shaped `MixPlan` JSON.

## Template 1: Second-Build Drop Switch

Inputs:

- `song_a` has ordered build/drop pairs:
  - build 1 -> drop 1;
  - build 2 -> drop 2.
- `song_b` has build 1 -> drop 1.
- `song_a.tempo.normalizedBpm == song_b.tempo.normalizedBpm` exactly. There is
  no BPM tolerance in this POC path because the first offline renderer will not
  implement pitch-preserving time stretch.

Candidate selection:

- If the next candidate song does not match `song_a`'s normalized BPM exactly,
  keep scanning the candidate pool for another song that can satisfy Template 1.
- Only fall back to Template 2 after no exact-BPM Template 1 candidate is found
  or after all exact-BPM candidates are rejected for section/confidence/timing
  reasons.
- Record `bpm_mismatch_for_drop_switch` when a specific pair is rejected only
  because its normalized BPM differs.

Timing:

```text
a_build_2_start = start of song_a build 2
a_drop_2_start = start of song_a drop 2
measure_seconds = 60 / normalized_bpm * 4
measures_to_drop = round((a_drop_2_start - a_build_2_start) / measure_seconds)
b_start = song_b_drop_1_start - measures_to_drop * song_b_measure_seconds
aligned_drop_timeline = timeline time where song_a drop 2 would start
song_b timeline start = aligned_drop_timeline - (song_b_drop_1_start - b_start)
```

Automation:

- Start `song_b` at low or zero volume at its calculated build position.
- Fade `song_b` up during the build.
- Fade `song_a` down so it reaches 0 by two measures before the aligned drop.
- Keep `song_b` full volume at aligned drop.

Initial automation curves should be simple linear or smoothstep keyframes. The
plan should record curve choices so manual review can judge them.

## Template 2: Drop-End Reverb Exit

Inputs:

- `song_a` has a current or first usable drop with end time.
- `song_a` does not have a usable second build/drop pair.
- `song_b` has a first beat or source-start cue.

Timing:

```text
a_drop_end = end of chosen song_a drop
a_ramp_start = a_drop_end - 8 measures
a_final_measure = a_drop_end - 1 measure
b_start = first beat/source-start of song_b
b_low_restore_end = a_drop_end + 4 measures at song_b tempo
```

Automation:

- `song_a.eqLow`: 1.0 -> 0.0 from ramp start to drop end.
- `song_a.reverbWet`: 0.0 -> configurable mid value from ramp start to final
  measure, then -> 1.0 at drop end.
- `song_a.volume`: hold 1.0 until final measure, then -> 0.0 by drop end.
- `song_b.eqLow`: 0.0 at start, -> 1.0 over 4 measures.
- `song_a.reverbWet` or reverb return level: -> 0.0 over 4 measures after
  song_b starts.

Decision: implement this as CDJ-style post-fader reverb behavior for the POC.
The outgoing dry deck volume may reach 0 while the reverb tail remains audible.
If the current schema cannot express this cleanly, extend it with an explicit
reverb-tail control such as `reverbReturn`, `reverbTailGain`, or
`reverbDecaySeconds` rather than faking the tail with deck dry volume.

## Playback Scheduling

The playback engine should treat the `MixPlan` as an immutable event schedule.

Validation responsibilities:

- required fields exist;
- timestamps are non-negative;
- commands reference known tracks/decks/placements;
- automation keyframes are sorted or can be sorted deterministically;
- no impossible source times;
- technique-specific invariants for the two MVP templates.

Runtime responsibilities:

- maintain transport time;
- compute active deck state for arbitrary timeline time;
- recompute state after seek by replaying or evaluating the plan from the
  beginning;
- expose state for tests and, later, UI/audio callbacks.

Execution order for same-time commands:

1. stop/clear previous deck state;
2. load;
3. seek;
4. automation holds/keyframes;
5. play.

This order can be changed if implementation reveals a better audio-engine
sequence, but it must remain deterministic and tested.

## Audition Target Options

Decision: the first audition target is a Python offline render harness that
generates a local WAV preview from a `MixPlan`. WAV is preferred over MP3 for
the POC to avoid encoder-delay ambiguity while judging beat-accurate
transitions. The renderer must render audible volume, low-EQ, and a simple
CDJ-style post-fader reverb-tail approximation. A realtime desktop/UI debugger
is deferred unless the offline artifacts are not enough to diagnose a
transition problem.

## Debug Output

Each generated plan should include annotations such as:

- selected template;
- why alternatives were rejected;
- section IDs used;
- measure counts to drop/end;
- aligned drop timeline;
- confidence warnings;
- expected handoff point where `song_b` becomes primary.

The local audition folder should include:

- `mix-plan.json`;
- `transition-debug-summary.md` or `.json`;
- rendered WAV preview audio.

## Safety And Artifact Policy

- Do not commit real audio, rendered mixes, Rekordbox XML, or generated local
  audition artifacts.
- Use ignored output paths such as `.autodj-cache/mixplan-poc/<run-name>/`.
- Keep tests on synthetic fixtures or small generated audio/click fixtures.
