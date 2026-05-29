# DeepDub Drop-Switch Yield Experiment

This note compares the manually verified safe DeepDub baseline against two
controlled yield probes. The safe baseline remains recorded in
`deep-dub-perfect-drop-switch-policy.json`.

## Baseline

- Run: `.autodj-cache/full-set-poc/deep-dub-full-20260528-004848`
- Result: 8 drop-switches, 39 wash-outs.
- Manual verdict: all selected drop switches were perfect.
- Key policy values:
  - `candidateSearchWidth`: 24
  - `maxDropSwitchNudgeMs`: 18
  - `minStretchedDropSwitchNudgeConfidence`: 0.85

## Biggest Gates

Cheap pre-filter gates across the baseline candidate report:

- `key_incompatible`: 1007
- `tempo_delta_exceeds_limit`: 690
- `immediate_artist_repeat`: 114
- `missing_outgoing_second_build_drop`: 55
- `outgoing_tempo_stretched_requires_wash_out`: 27

Attempted drop-switch post-pass rejections:

- 8 failed only `maxDropSwitchNudgeMs`.
- 3 failed only nudge confidence.
- 5 failed both nudge size and confidence.

Interpretation: key compatibility is the largest overall gate, but it is
intentional and should remain strict for drop switches. Among candidates that
actually reached the expensive post-pass, the strongest yield lever is the
maximum allowed drop-switch nudge.

## Key Gate Audit

The safe default is now explicit:

- `--drop-switch-key-policy compatible`: reject confident clashes and also
  reject unknown/low-confidence key matches.

An experimental policy was added:

- `--drop-switch-key-policy allow-unknown`: reject only confident clashes and
  let unknown/low-confidence key matches reach audition.

DeepDub static directed-pair counts across the 48-track batch:

- Tracks with required drop-switch sections and tempo delta <= 10 BPM: 794
- Eligible after all cheap prefilters with `compatible`: 98
- Eligible after all cheap prefilters with `allow-unknown`: 478
- Additional cheap-prefilter-eligible pairs from allowing unknown keys: 380
- Confident key clashes still rejected under both policies: 299

The high-yield policy clearly opens many more possible pairings, but it also
greatly increases expensive nudge/gain work. A full sequence probe with
`allow-unknown` was intentionally stopped before completion because it was still
running post-passes after several minutes. Treat this as a pool-expansion tool
for manual experiments, not a replacement for the verified baseline.

Manual audition update: five exact-BPM DeepDub drop-switch auditions generated
with `allow-unknown` were all reported perfect. After that verdict,
`allow-unknown` became the default planner key policy while the old
`compatible` baseline remains documented as a rollback point.

## Full Mix: Allow Unknown, Width 8

- Run: `.autodj-cache/full-set-poc/deep-dub-full-allow-unknown-key-width8-20260528-154601`
- Changed:
  - `dropSwitchKeyPolicy`: `compatible` -> `allow-unknown`
  - `candidateSearchWidth`: `24` -> `8`
- Kept:
  - `maxDropSwitchNudgeMs`: `18`
  - `minStretchedDropSwitchNudgeConfidence`: `0.85`
  - rendered-domain nudge proof
  - SoundStretch
  - real wash-out sweep
- Result: 19 drop-switches, 28 wash-outs.
- Stretched drop-switches: 8.
- Drop-switch key classes: 12 unknown, 5 adjacent, 2 perfect.
- Validation: passed.
- Full WAV:
  `.autodj-cache/full-set-poc/deep-dub-full-allow-unknown-key-width8-20260528-154601/render/audition.wav`

This is the current high-yield candidate to audition. It more than doubles the
drop-switch count relative to the original safe baseline while preserving the
strict 18 ms nudge cap.

## Effective-BPM Chaining Probe

- Run: `.autodj-cache/full-set-poc/deep-dub-effective-bpm-planonly-20260528-172600`
- Changed:
  - drop-switch candidate filtering uses outgoing effective BPM, not outgoing
    native BPM, after a prior stretched drop-switch;
  - pair nudge proof gets an effective-BPM temporary plan while the mergeable
    full-set plan remains in outgoing source-time domain.
- Kept:
  - `dropSwitchKeyPolicy`: `allow-unknown`
  - `candidateSearchWidth`: `8`
  - `maxDropSwitchNudgeMs`: `18`
  - `minStretchedDropSwitchNudgeConfidence`: `0.85`
  - rendered-domain nudge proof
- Result: 22 drop-switches, 25 wash-outs.
- Stretched drop-switches: 9.
- Validation: passed.

This proves the old non-native-tempo brake was suppressing valid chained
drop-switches. The strict nudge cap remains active; rejected candidates still
fall back to wash-outs.

## Effective-BPM Plus One-Step Lookahead

- Run: `.autodj-cache/full-set-poc/deep-dub-effective-bpm-lookahead-planonly-20260528-184354`
- Changed:
  - keeps the effective-BPM chaining behavior above;
  - ranks drop-switch candidates by cheap one-step follow-up potential before
    key score and tempo delta, so locally valid choices are less likely to
    consume tracks needed for later drop-switches.
- Result: 23 drop-switches, 24 wash-outs.
- Stretched drop-switches: 9.
- Validation: passed.
- Full WAV:
  `.autodj-cache/full-set-poc/deep-dub-effective-bpm-lookahead-planonly-20260528-184354/render/audition.wav`

The lookahead adds only one drop-switch over effective-BPM chaining alone, but
it creates a stronger early drop-switch chain and keeps the same strict quality
gates. Runtime remains high because rejected drop-switch attempts still run the
full pair planner and rendered nudge proof.

## Probe: Nudge 24

- Run: `.autodj-cache/full-set-poc/deep-dub-probe-nudge24-20260528-084006`
- Changed:
  - `candidateSearchWidth`: 24 -> 48
  - `maxDropSwitchNudgeMs`: 18 -> 24
- Kept:
  - key compatibility
  - tempo limits
  - nudge confidence
  - SoundStretch
  - real wash-out sweep
- Result: 10 drop-switches, 37 wash-outs.

This is only a small gain over the safe baseline.

## Probe: Nudge 30

- Run: `.autodj-cache/full-set-poc/deep-dub-probe-nudge30-20260528-090542`
- Changed:
  - `candidateSearchWidth`: 24 -> 48
  - `maxDropSwitchNudgeMs`: 18 -> 30
- Kept:
  - key compatibility
  - tempo limits
  - nudge confidence
  - SoundStretch
  - real wash-out sweep
- Result: 14 drop-switches, 33 wash-outs.
- Preview WAVs rendered: 47.
- Preview index:
  `.autodj-cache/full-set-poc/deep-dub-probe-nudge30-20260528-090542/previews/index.json`

Do not promote this probe until the 14 drop-switch previews are manually
auditioned. The extra yield comes from accepting larger nudge offsets.

## Recommendation

Promote the effective-BPM chaining fix and one-step follow-up sort because they
increase DeepDub yield without relaxing the manually verified nudge gate. Do
not loosen `maxDropSwitchNudgeMs` by default.

The next yield/runtime improvement should not be another threshold tweak. It
should be one of:

- cache pair post-pass results by outgoing/incoming/effective-BPM/policy so
  repeated full-set experiments do not rerun identical nudge proofs;
- add a cheap transient-offset pre-score before invoking the rendered proof;
- replace the greedy sequence builder with a beam/graph planner that maximizes
  drop-switch count while preserving the same strict quality gates.
