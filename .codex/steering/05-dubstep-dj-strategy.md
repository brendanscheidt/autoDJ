# Dubstep DJ Strategy

## Purpose

The Dubstep DJ strategy is the first genre-specific AutoDJ brain. It consumes a
pool of analyzed dubstep tracks and emits a `MixPlan` that the playback engine
can execute.

It owns:

- Track ordering.
- Transition technique selection.
- Cue point selection.
- Energy arc.
- Automation keyframes.
- Debug reasons for decisions.

It does not own:

- Audio rendering.
- File importing.
- Stem separation implementation.
- Generic playback controls.
- UI behavior.

## Input Assumptions

For the MVP, assume every input track has already passed a genre gate and is
dubstep or adjacent bass music.

The strategy should still inspect compatibility. It should downrank or reject
tracks with:

- Low beat-grid confidence.
- Missing or ambiguous drop sections.
- Missing or incompatible Camelot key data for long harmonic overlaps.
- Tempo too far outside the target range.
- Unusable intro/outro material.
- High vocal clash risk.
- Analysis confidence too low for planned transition types.

## Tempo Model

Dubstep commonly uses halftime feel. Normalize tempo before comparing tracks.

Examples:

- 70 BPM can be equivalent to 140 BPM.
- 75 BPM can be equivalent to 150 BPM.
- 87 BPM may be equivalent to 174 BPM for adjacent bass genres, but should be
  treated cautiously in a dubstep-only strategy.

The `TempoAnalysis` should expose both raw and normalized BPM. The strategy
should compare normalized BPM first, then verify beat-grid alignment.

## Required Track Features

The strategy works best when each `AnalyzedTrack` includes:

- BPM and normalized BPM.
- Beat grid and downbeats.
- Key/Camelot estimate.
- Sections: intro, verse, build, ordered drops, break, outro.
- Energy curve.
- Bass energy curve.
- Vocal regions.
- Cue candidates.
- Stem paths when available.

Each feature must have confidence. The strategy should prefer simple transitions
when confidence is low.

For the current POC, semantic section confidence should come from manually
labeled Rekordbox XML when available. Automatic semantic backends may populate
the same fields, but high-risk transitions such as drop switches should treat
machine-only drop labels as provisional until the future trained drop-start
model is accepted.

For dubstep, repeated drops should be addressed by order within the track:
drop 1, drop 2, drop 3, and so on. Use canonical section labels in artifacts
and carry the order in section IDs/indices. Treat `break` as the canonical
breakdown/break-verse staging region between drops.

## Transition Templates

### Intro/Outro Blend

Use when:

- Outgoing track has a clean outro or low-energy breakdown.
- Incoming track has a clean intro.
- BPM and key are compatible.
- Vocal clash risk is low.

Typical automation:

- Start incoming deck with volume `0.0`.
- Keep incoming lows down initially.
- Fade incoming volume over 16 or 32 bars.
- Swap lows near phrase boundary.
- Fade outgoing volume or echo out.

### Build-To-Drop Swap

Use when:

- Incoming track has a high-confidence build ending in a drop.
- Outgoing track can create tension leading into the same drop boundary.
- Phrases align cleanly.

Typical automation:

- Bring incoming build in over outgoing breakdown/build.
- Reduce outgoing lows.
- Increase filter/reverb tension if useful.
- Hard or near-hard swap at incoming drop.
- Restore lows on incoming deck at drop.

### Second-Build Drop Swap

Use when:

- Song 1 has already played drop 1.
- Song 1 has a high-confidence second build and known bar count until drop 2.
- Song 2 has a compatible build 1 and drop 1.
- The two builds can be aligned so both drops land on the same downbeat.
- Native exact normalized BPM matches are preferred. If no exact pair is chosen,
  the POC may use SoundStretch to render the incoming song to the outgoing
  song's normalized BPM when the delta is inside the configured gate. The
  effective BPM at the overlap must still be exact.

Typical automation:

- Count bars from song 1 build 2 start to song 1 drop 2.
- Start song 2 build 1 the same number of bars before its drop.
- Bring song 2 up during the first half of the aligned build.
- Hand low-end ownership from song 1 to song 2 at the build midpoint.
- Keep both builds audible after the midpoint.
- Cut song 1 one bar before the aligned drop so song 2 owns the predrop and
  drop.
- Apply transient nudge to the incoming source around the transition anchors so
  kicks/transients line up by ear.
- If SoundStretch was used, the nudge pass must use tempo-aware source/timeline
  mapping and the rendered asset should be validated before trusting long
  beat-locked overlap.

### Drop Double

Use when:

- Both tracks have compatible drops.
- BPM is nearly identical or time-stretch quality is acceptable.
- Key clash is acceptable.
- Drops have complementary frequency/vocal content.

Typical automation:

- Align drops on the same downbeat.
- Keep both audible for a short phrase.
- Manage low end aggressively to avoid mud.
- Choose one track as primary after the double.

Risk:

- This can sound bad quickly. Require high confidence and conservative duration.

### Vocal Predrop Layer And Drop Chop

Use when:

- The tracks are harmonically compatible.
- Song 2 has a clean vocal/acapella stem.
- Song 1 has a verse or break region with low vocal clash risk.
- Both tracks have compatible builds and drops.

Typical automation:

- Layer song 2 vocal over song 1 verse/break.
- At the build, bring in song 2 build while tightening or looping the vocal.
- Use one clean pre-drop bar from either song.
- Chop between compatible drops every 4 bars, ending on song 2 break.

Risk:

- Requires reliable key/chord compatibility, stem quality, vocal timing, and
  phrase-aware drop segmentation.

### Frequency-Complement Drop Double

Use when:

- Both drops are rhythmically compatible.
- One drop carries strong low end with sparse high end.
- The other drop carries complementary high end with controllable low/mid
  energy.

Typical automation:

- Align drops on the same downbeat.
- Cut or reduce high end on the low-end-heavy track.
- Cut or reduce low/mid energy on the high-end-heavy track.
- Keep the double short unless frequency clash metrics remain strong.

Risk:

- Requires reliable band-energy and masking analysis, not just section labels.

### Loop Tighten

Use when:

- Outgoing track has a loopable build, fill, vocal chop, riser, or pre-drop
  phrase.
- Incoming track has a strong drop target.
- Beat grid confidence is high.

Typical automation:

- Set loop length to 4 or 8 beats.
- Tighten to 2, 1, and optionally 1/2 beat.
- Increase filter/reverb/echo or reduce lows.
- Release or clear loop at incoming drop.

Risk:

- Requires precise loop points and clean transient handling.

### Vocal Over Instrumental

Use when:

- A vocal stem or strong vocal region exists.
- The target instrumental region has low vocal presence.
- Key compatibility is high.
- Stem quality is acceptable.

Typical automation:

- Load vocal stem on an additional deck if available.
- Keep instrumental deck as primary.
- Apply EQ/filter to reduce clash.
- Exit before vocal conflict or drop if it becomes crowded.

MVP note:

- This should be optional until stem quality scoring exists.

### Hard Cut / Impact Cut

Use when:

- Track sections demand a sharp switch.
- Phrase alignment is exact.
- Energy jump is intentional.
- A safer blend is not musically appropriate.

Typical automation:

- Cut outgoing volume at downbeat.
- Start incoming at drop/downbeat.
- Optional echo tail on outgoing deck.

## Scoring Model

The strategy should score candidate transitions before selecting them.

Suggested initial score:

```text
score =
  0.25 * bpmCompatibility +
  0.20 * phraseAlignment +
  0.15 * keyCompatibility +
  0.15 * sectionCompatibility +
  0.10 * energyArcFit +
  0.10 * vocalClashSafety +
  0.05 * analysisConfidence
```

Weights can vary by transition template. For example, loop tightening should
weight beat-grid confidence more heavily than key compatibility.

## Compatibility Signals

### BPM Compatibility

High score:

- Exact effective normalized BPM match at the drop-switch overlap.
- Native exact normalized BPM match remains preferred when available.
- Tempo-matched drop switches may be considered when the incoming deck can be
  rendered with SoundStretch to the outgoing deck's BPM inside the configured
  adjustment window. Midpoint bridge planning, where both decks move to a shared
  middle BPM, remains a future extension.
- Normalized BPM delta <= 1% for simpler non-time-stretched transitions.
- Beat grid confidence is high.

Medium score:

- Delta <= 3% and time-stretch backend is available.

Low score:

- Delta > 5%, unless doing an intentional hard cut.

Current tempo-stretch planning target:

- Default `maxTempoAdjustmentBpmPerDeck = 10.0`.
- A `145 BPM` outgoing track and `150 BPM` incoming track can become eligible
  by rendering the incoming track to `145 BPM` with SoundStretch, if rendered
  timing and manual audition pass.
- A `140 BPM` outgoing track and `160 BPM` incoming track is still outside the
  current one-sided generated-audition path, even though a future midpoint
  bridge could theoretically meet at `150 BPM`.
- Tempo matching changes eligibility; it does not remove the need for
  compatible key, phrase, energy, and transient alignment.

### Key Compatibility

Use Camelot-style compatibility when available.

For key detection work, Rekordbox XML `Tonality` values are benchmark truth, not
the production key source. `AnalyzedTrack.key.camelot` comes from
`selected-madmom-keyfinder`, which chooses confident madmom CNN output and falls
back to keyfinder when madmom confidence is below the production gate.

High score:

- Same key.
- Adjacent Camelot key.
- Relative major/minor where musically acceptable.

Low score:

- Distant key with sustained melodic/vocal overlap.

Current planner behavior:

- Drop-switch candidates with confident distant Camelot clashes are rejected for
  the second-build drop-switch template. Generated audition batches filter to
  Camelot-compatible pairs by default and can include exact-BPM or
  SoundStretch-eligible BPM-matched pairs depending on the batch tempo policy.
- Reverb exits warn on key clashes but do not block, because the dry overlap is
  intentionally short.
- Missing or low-confidence key metadata is annotated as unknown compatibility
  inside strategy diagnostics. Generated key-aware audition batches should use
  freshly analyzed artifacts with `AnalyzedTrack.key.camelot` populated; the
  default batch filter rejects unknown key compatibility for long drop-switch
  overlaps.

Key matters less for short percussion-heavy cuts and more for blends, doubles,
and vocals.

### Phrase Alignment

Prefer 8, 16, and 32-bar boundaries. For dubstep, 16 and 32 bars should dominate
early templates.

High score:

- Incoming drop lands exactly on a downbeat and phrase boundary.
- Outgoing transition point also lands on a phrase boundary.

Low score:

- Transition starts mid-phrase without a strong reason.

### Section Compatibility

Good pairings:

- Outgoing outro -> incoming intro.
- Outgoing breakdown -> incoming build.
- Outgoing build -> incoming drop.
- Outgoing drop end -> incoming drop start for doubles or impact cuts.

Risky pairings:

- Vocal verse over vocal verse.
- Drop over dense drop without EQ control.
- Intro over high-energy drop unless intentionally layering.

### Vocal Clash Safety

High score:

- Only one audible vocal source.
- Vocal stem is isolated and target instrumental has low vocal presence.

Low score:

- Two vocals overlap in different keys or rhythms.

## Plan Generation Flow

1. Filter tracks by minimum analysis quality.
2. Normalize tempo and key fields.
3. Load or choose a semantic cue provider. Prefer Rekordbox-labeled
   `AnalyzedTrack` artifacts for the current POC.
4. Generate candidate cue points only when accepted semantic labels are missing.
5. Build transition candidates between compatible track pairs.
6. Score candidates by template-specific rules, including energy compatibility
   and transient-nudge diagnostics for drop switches.
7. Select an energy arc for the set.
8. Choose track sequence using transition scores and energy goals.
9. Compile selected transitions into deck commands and automation lanes.
10. Validate resulting `MixPlan`.
11. Emit annotations explaining selected and rejected transitions.

## Energy Arc

The MVP should support a simple `ramp` energy arc:

- Start medium.
- Build over the first third.
- Peak in the final third.
- Avoid too many max-energy tracks back-to-back.

Later add:

- Wave-shaped arcs.
- User-directed "go harder" controls.
- Adaptive track choice based on listener actions.

## Failure Handling

If the strategy cannot create a high-confidence transition, it should fall back
in this order:

1. Simpler phrase-aligned intro/outro blend.
2. Echo-out into phrase-aligned start.
3. Hard cut on downbeat.
4. Reject the track from the generated set.

Do not emit complex automation for low-confidence analysis. Bad confidence
should result in safer DJ behavior.

## Debug Output

Every transition should include:

- Final score.
- Chosen technique.
- Why it was chosen.
- Major risk flags.
- Cue points used.
- Rejected alternatives when useful.

This is essential for making bad transitions fixable.
