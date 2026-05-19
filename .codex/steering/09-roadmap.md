# Roadmap

This is a rough implementation timeline. It should guide sequencing, not act as
a fixed schedule.

## Phase 0: Steering And Specs

Status: current documentation phase.

Deliverables:

- Product vision.
- Architecture docs.
- Contract guidance.
- Tech stack decision record.
- Project structure plan.
- Dubstep DJ strategy plan.
- Playback and analysis guidance.
- First implementation spec.

## Phase 1: Init Foundation

Target: 1 to 3 days.

Spec:

- `.codex/specs/001-init-foundation.md`

Deliverables:

- Repo structure.
- Root CMake project.
- CMake presets.
- Minimal JUCE desktop app target.
- C++ domain/playback/repository/dj stub libraries.
- Contract schemas and example fixtures.
- Python analysis package with stub CLI.
- Stub genre analyzer.
- Basic tests and validation commands.

Success:

- `cmake --preset debug`
- `cmake --build --preset debug`
- `ctest --preset debug`
- Python CLI runs and writes stub artifacts.

## Phase 2: Local Repository And Metadata Cache

Target: 2 to 5 days.

Deliverables:

- Local folder/file import.
- WAV/MP3 discovery.
- Track IDs and content hashes.
- Repository manifest.
- Cache directory layout.
- Reanalysis invalidation based on content hash.

Success:

- User can point the app at a folder and see local tracks.
- Modified files are detected.
- No analysis is rerun unnecessarily.

## Phase 3: Analysis MVP

Target: 1 to 2 weeks.

Spec 005 status:

- BPM/beatgrid selected path is `current-autodj-signal`.
- Semantic section selected path is `dubstep-phrase-hybrid`, with
  `current-autodj-signal` rough sections retained only as fallback.
- Deferred MIR/provider/stem/native candidates are cataloged in
  `.codex/specs/005-adaptive-mir-candidate-evaluation/deferred-candidates-and-future-specs.md`.

Deliverables:

- FFmpeg probe/decode integration.
- Python POC/reference analyzer using strong MIR libraries aggressively where
  they materially improve output quality.
- Selected BPM/beatgrid artifact path using `current-autodj-signal`.
- Selected section artifact path using `dubstep-phrase-hybrid`.
- Comparison/deferred timing candidates documented for later reference:
  Essentia, Beat This, All-In-One timing, BeatNet, madmom, aubio, Vamp/QM, and
  Superpowered.
- Deferred structure/cue candidates documented for later reference:
  All-In-One/SongFormer evidence layers, automatic cue switch points, cue object
  detection, MSAF, and hosted semantic providers.
- Evaluation harness using generated fixtures and mir_eval where useful.
- BPM/key/beat grid fields in `AnalyzedTrack`.
- Basic waveform overview.
- Semantic section detection with honest confidence and fallback behavior.
- Cue candidate generation.
- Confidence values.
- Portability notes for later native/mobile analysis implementation.

Success:

- Analyze a small local dubstep folder.
- Inspect generated metadata in UI or CLI.
- Beat grid and rough drop/build candidates are visible.
- Candidate libraries are compared honestly, and the winning POC behavior is
  captured well enough to port or license later.

## Phase 3.5: Native Analysis Feasibility

Target: after the Python POC produces useful metadata.

Deliverables:

- Identify which POC analysis outputs must run offline on mobile.
- Decide whether to port algorithms to homegrown C++, license native libraries,
  or use mobile-safe ML runtimes.
- Build a small native prototype for waveform, energy, onset, and at least one
  tempo/beat-grid path.
- Compare native output against Python POC golden fixtures.

Success:

- There is a credible path to on-device mobile analysis without WSL, CPython, or
  server-side preprocessing.

## Phase 4: Playback Engine Skeleton

Target: 1 to 2 weeks.

Deliverables:

- Deck model.
- Mixer model.
- MixPlan loader.
- Command scheduler.
- Keyframe automation.
- Basic volume/EQ/filter controls.
- Synthetic fixture playback tests.
- Minimal workbench transport UI.

Success:

- A hand-authored `MixPlan` can load two tracks and crossfade/automate controls.
- Seeking recomputes automation correctly.
- Basic plan validation catches bad references.

## Phase 5: First Dubstep MixPlan Generator

Target: 1 to 2 weeks.

Deliverables:

- Candidate transition generation using selected beatgrid and section metadata.
- BPM/key/phrase compatibility scoring.
- Intro/outro blend template.
- Build-to-drop swap template.
- Hard-cut fallback.
- Debug annotations.

Success:

- Generate a deterministic short set from analyzed tracks.
- Audition generated transitions in the desktop app.
- Bad transitions can be traced to analysis or strategy decisions.

## Phase 6: Loop Tighten And Drop-Focused Transitions

Target: 1 to 2 weeks.

Deliverables:

- Loop command execution.
- Loop-tighten transition template.
- Drop-double candidate scoring.
- Better low-end automation.
- Timing tests with impulse/click fixtures.

Success:

- Loop-tighten into drop works on high-confidence beat grids.
- Drop doubles are used only when compatibility is strong.

## Phase 7: Stems And Vocal-Aware Transitions

Target: 2 to 4 weeks.

Deliverables:

- Demucs wrapper as the first likely local candidate.
- Optional comparison notes for BS-RoFormer/Mel-Band RoFormer, Open-Unmix,
  Spleeter, AudioShake, Music AI, and zplane STEMS before product commitment.
- Stem cache.
- Vocal region detection from stems.
- Stem quality gating.
- Vocal-over-instrumental transition prototype.

Success:

- App can optionally extract vocals/instrumentals.
- DJ avoids obvious vocal clashes.
- At least one stem-based transition sounds intentional on test tracks.

## Phase 8: Better Section Detection

Target: ongoing.

Deliverables:

- Confidence calibration and regression cleanup for `dubstep-phrase-hybrid`.
- Improved drop/build/break detection only after real transition failures show
  where the selected backend is insufficient.
- UI correction tools for section/cue errors.
- Regression fixtures from bad analysis cases.

Success:

- Strategy errors increasingly come from musical taste, not bad metadata.

## Phase 9: Mobile Feasibility Prototype

Target: after desktop MVP proves mix quality.

Deliverables:

- C++ playback core isolated from desktop UI.
- Small iOS or Android shell prototype.
- Mobile audio backend evaluation.
- Mobile analysis runtime evaluation based on Phase 3.5 findings.
- Time-stretch backend decision.
- Analysis/stem strategy for mobile constraints.

Success:

- A precomputed `MixPlan` can play on a mobile device using local audio assets,
  and the remaining path to local on-device analysis is technically understood.

## Biggest Risks

- Section detection is harder than BPM/key extraction.
- Stem quality may be inconsistent for dense dubstep.
- Time-stretch quality matters for professional-sounding blends.
- Android latency and device variance can complicate mobile later.
- Licensing decisions for JUCE, FFmpeg builds, stem models, and DSP backends must
  be resolved before shipping commercially.
