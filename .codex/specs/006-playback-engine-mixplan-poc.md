# Spec 006: Playback Engine And MixPlan POC

> Kiro-style execution package:
> `.codex/specs/006-playback-engine-mixplan-poc/`

## Purpose

Build the first audible AutoDJ proof of concept: take analyzed dubstep tracks,
choose one of two simple transition templates, emit a deterministic `MixPlan`,
and execute or audition that plan well enough to judge whether the selected
Spec 005 analysis metadata is musically usable.

Spec 005 answered "what metadata can we trust enough for a POC?" Spec 006
answers "can that metadata drive a real transition?" Later audition and
benchmark work refined the answer: BPM/beatgrid is trusted, but automatic
semantic drop detection is not yet trusted enough. Rekordbox-labeled semantic
cues are therefore the preferred oracle for transition planning until the
trained drop-start model exists.

## Selected Inputs From Spec 005

- BPM and beatgrid: `current-autodj-signal`.
- Preferred semantic sections and cue candidates: Rekordbox XML hot-cue labels
  applied into `AnalyzedTrack`.
- Experimental semantic sections and cue candidates: `dubstep-phrase-hybrid`
  and other automatic providers.
- Relevant labels: `intro`, `verse`, `build`, `drop`, `break`, `outro`.
- Real audio and generated analysis artifacts remain local-only and out of git.

## MVP Transition Behaviors

### Situation 1: Second-Build Drop Switch

Use when `song_a` has at least two marked build/drop pairs and `song_b` has a
usable first build/drop pair. This transition is allowed only when
`song_a.tempo.normalizedBpm` and `song_b.tempo.normalizedBpm` are exactly equal
after analysis normalization. Do not apply a BPM tolerance for this POC. If the
planner has multiple candidate incoming songs, it must scan for an exact-BPM
candidate before falling back to Situation 2.

1. Let `song_a` play through drop 1.
2. When `song_a` reaches build 2, calculate how many measures remain until
   `song_a` drop 2.
3. Start `song_b` from the same number of measures before its first drop.
4. Slowly crossfade/build-blend from `song_a` to `song_b`.
5. Ensure `song_a` reaches volume 0 no later than 2 measures before the aligned
   drop boundary.
6. Let `song_b` be the only full-volume source at the drop. `song_b` becomes
   the outgoing track for the next transition, and `song_a`'s deck becomes
   available for loading.

### Situation 2: Drop-End Reverb Exit

Use when `song_a` does not have a usable second build/drop pair but has a
usable current drop end and `song_b` has a usable first beat/start.

1. Let `song_a` play into its drop.
2. Eight measures before the drop ends, begin reducing `song_a` low EQ while
   increasing reverb wet to a moderate value.
3. During the final measure of the drop, reduce `song_a` volume to 0 and push
   reverb wet to 100%, leaving only the reverb tail.
4. At the exact beat where the drop ends, `song_a` dry volume is 0 and reverb
   is full wet.
5. Start `song_b` from its first beat with low EQ at 0.
6. Over four measures, restore `song_b` low EQ to 100% while fading
   `song_a`'s reverb tail to 0. `song_b` becomes the outgoing track for the
   next transition.

## Non-Goals

- Stem separation.
- Vocal-aware transitions.
- Layered drop variants.
- Loop tightening.
- Automatic full-set planning beyond a deterministic two-track or small-track
  chain POC.
- Solving remaining section-analysis edge cases before hearing transitions.
- Committing real songs, Rekordbox XML, rendered mixes, or generated artifacts.

## Completion Criteria

- A hand-authored or generated `MixPlan` can represent both MVP transition
  situations.
- The playback engine can validate and schedule the plan deterministically.
- A Python offline render harness can produce local WAV audition audio that is
  good enough to judge timing, volume, EQ-low, and simple CDJ-style post-fader
  reverb-tail behavior. A realtime UI debugger is deferred unless audition
  problems require it.
- The planner can choose Situation 1 when the second build/drop exists and
  an exact-normalized-BPM incoming candidate exists, and Situation 2 when no
  valid exact-BPM drop-switch candidate exists.
- Debug annotations explain why each transition was chosen and which sections,
  beats, and measures were used.
- The user manually auditions generated outputs and records a verdict before
  the spec is considered complete.
