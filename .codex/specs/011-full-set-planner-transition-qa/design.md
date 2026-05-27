# Design Document

## Architecture

Spec 011 keeps the existing analysis and transition-template boundaries:

```text
AnalyzedTrack artifacts
  -> set planner candidate search
  -> pairwise transition fragment generation
  -> nudge and gain post-passes
  -> full-set MixPlan merge
  -> validation
  -> transition preview renders
  -> optional full-set render
```

The planner should consume canonical `AnalyzedTrack` artifacts, not raw
Rekordbox XML. Rekordbox labels remain the current source of semantic truth only
because they have already been applied into analyzed artifacts.

## Modules

### Planner Input Model

Create a small Python planner module first, because the current working path and
renderer are Python-driven:

- `autodj_analysis.full_set_planner`
- `autodj_analysis.transition_preview`
- optional CLI commands under `autodj-analysis`

The current `tools/scripts/generate_full_set_poc.py` can be the migration source
or temporary wrapper. The implementation should keep the script working while
moving reusable logic into package modules.

### Candidate Model

Candidate records should include:

- outgoing track id and incoming track id;
- transition type: `drop_switch`, `wash_out`, or future fallback;
- exact BPM or SoundStretch ratio;
- Camelot compatibility class;
- semantic anchor ids and section confidence;
- nudge report summary;
- energy/gain report summary for drop switches;
- rejection reasons if not selected.

### Set Policy

Initial policy should be deterministic and conservative:

- prefer drop-switch when key, BPM/stretch, sections, nudge, and energy are good;
- use wash-out to escape incompatible BPM/key/section conditions;
- discourage repeated wash-outs;
- discourage large tempo shifts if exact or smaller shifts are available;
- keep a configurable random seed and candidate sample size so generated sets
  are varied but reproducible.

### Validation

Validation should run before any render:

- outgoing placements must end at or before the first matching stop command;
- active drop-switch decks must not have positive wet FX automation inside the
  transition window;
- incoming decks must have dry FX reset commands before placement start;
- no unsupported tempo ramps for the offline renderer;
- assets referenced by placements exist through asset root resolution;
- track placement ids and transition ids are unique.

The current generator already has two of these checks; this spec expands them
and makes them part of the supported command path.

### Preview Rendering

Preview rendering should avoid rendering the whole set for every transition.
V1 can create per-transition cropped MixPlans by:

1. selecting placements that overlap a preview timeline window;
2. shifting timeline times so the preview starts at zero;
3. keeping enough pre-roll for reverb/echo state when needed;
4. rendering the cropped plan through the existing offline renderer.

For drop-switch previews, default to a musically useful window:

- 8 or 16 bars before the transition start;
- 8 or 16 bars after the aligned drop or handoff.

For wash-out previews:

- 8 bars before outgoing drop end;
- 12-16 seconds after handoff so the sweep/tail can be heard.

### Reports

Every run should write:

- `full-set-summary.json`;
- `candidate-report.json`;
- `validation-report.json`;
- `previews/index.json` when previews are generated;
- `render/render-summary.json` when full render is generated.

Reports should be optimized for manual listening and debugging rather than only
unit-test assertions.

## Testing Strategy

Unit tests:

- candidate scoring is deterministic for a seed;
- wash-out spacing penalty works;
- validation catches placement overruns and wet drop-switch FX;
- preview MixPlan cropping preserves automation and asset references;
- report writers produce stable JSON.

Integration tests:

- run a tiny 3-4 track set from generated audio fixtures;
- render at least one preview for drop-switch and wash-out;
- verify full-set command refuses invalid plans before render.

Manual tests:

- generate a preview pack from the 48-song dubstep folder;
- user listens to selected previews and records verdict;
- render a full set only after preview pack is acceptable.

## Risks

- Full preview rendering can still be slow if each preview decodes large MP3s.
  Mitigation: reuse canonical/stretched assets where practical.
- Over-scoring may make sets feel too conservative. Mitigation: keep seed and
  policy controls visible.
- Bad semantic labels can still cause bad transitions. Mitigation: report anchor
  labels and source times clearly.

