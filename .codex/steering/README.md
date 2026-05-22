# AutoDJ Steering Files

These files are the standing implementation guidance for the AutoDJ project.
Future implementation agents should read them before changing architecture,
contracts, build tooling, playback code, analysis code, or DJ strategy logic.

Read in this order:

1. `00-product-vision.md`
2. `01-system-architecture.md`
3. `02-core-contracts.md`
4. `03-tech-stack.md`
5. `04-project-structure.md`
6. `05-dubstep-dj-strategy.md`
7. `06-playback-engine.md`
8. `07-analysis-pipeline.md`
9. `08-engineering-practices.md`
10. `09-roadmap.md`

Core decisions:

- The first product is a desktop-first DJ lab for local WAV/MP3 files.
- Spotify and streaming service playback are out of scope for the MVP.
- The initial genre target is dubstep and adjacent bass music.
- Playback is a dumb, deterministic executor of a deck-control timeline.
- DJ modules generate mix plans. The player does not contain genre logic.
- Audio analysis and stem separation run offline before playback.
- Selected BPM/beatgrid path is `current-autodj-signal`.
- Current POC semantic planning source is Rekordbox XML hot-cue labels applied
  into `AnalyzedTrack` artifacts. `dubstep-phrase-hybrid` and other automatic
  section systems are experimental/fallback providers until a trained drop-start
  model proves reliable enough.
- Transition planning and playback should consume the normalized
  `AnalyzedTrack` section/cue contract, not provider-specific Rekordbox XML,
  All-In-One, SongFormer, CUE-DETR, or EDM-98 objects directly.
- The playback core must stay portable enough to move toward iOS/Android.

Current active implementation/spec packages are:

- `../specs/006-playback-engine-mixplan-poc/`
- `../specs/007-transition-recipe-authoring-workbench/`

Spec 005 remains the analysis research and benchmark record. Earlier spec
packages remain under `../specs/`.
