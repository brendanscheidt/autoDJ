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
- Automatic semantic section best candidate is `dubstep-phrase-hybrid`, with
  `current-autodj-signal` rough sections retained only as fallback.
- Manual Rekordbox XML cue labels are now the trusted POC semantic oracle for
  transition planning until a trained drop-start model reaches acceptance
  accuracy.
- Deferred MIR/provider/stem/native candidates are cataloged in
  `.codex/specs/005-adaptive-mir-candidate-evaluation/deferred-candidates-and-future-specs.md`.

Deliverables:

- FFmpeg probe/decode integration.
- Python POC/reference analyzer using strong MIR libraries aggressively where
  they materially improve output quality.
- Selected BPM/beatgrid artifact path using `current-autodj-signal`.
- Selected section artifact path using `dubstep-phrase-hybrid`.
- Rekordbox XML import/export path for manually labeled semantic cues.
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

Status:

- Spec 006 implemented a C++ MixPlan parser/validator, deterministic scheduler,
  two MVP transition templates, a Python offline renderer, transient nudging,
  and drop-switch energy/gain planning for audition artifacts.
- Spec 007 implemented the first native JUCE transition authoring workbench for
  two-deck inspection, automation editing, and session/MixPlan/recipe export.

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

Current direction:

- Use Rekordbox-labeled `AnalyzedTrack` artifacts as the semantic input.
- Prefer exact normalized BPM matches for drop switches. When exact matches are
  not enough, allow SoundStretch-matched incoming tracks inside the configured
  BPM gate.
- Use compatible in-house Camelot keys for generated drop-switch pairs.
- Use `selected-madmom-keyfinder` for AutoDJ key output; Rekordbox XML
  `Tonality` values remain key benchmark truth only.
- Use reverb exits or simpler cuts when BPM or semantic confidence does not
  support a drop switch.
- Keep automatic semantic detection as a replaceable provider rather than a
  blocker for transition-intelligence work.
- Current full-set POC status, 2026-05-27: generated set plans use pairwise
  drop-switch and wash-out fragments, SoundStretch where needed, key-compatible
  drop-switch candidate selection, transient nudge/gain planning, and hard-stop
  placement truncation so old tracks do not keep playing under later
  transitions. The generator now validates that outgoing placements end at stop
  time and that drop-switch windows stay dry. Spec 011 promotes this into the
  supported `autodj-analysis plan-set` preview-first workflow with candidate,
  validation, preview, and full-set summary reports.
- Latest Spec 011 checkpoint renders from an accepted preview MixPlan rather
  than rerunning pair search:
  `.autodj-cache/full-set-poc/spec011-full-render-checkpoint-20260527-2118/render/audition.wav`.
  The rendered set is about 21 minutes and contains 9 drop switches plus 6
  wash-outs. Manual audition remains the final quality gate.

Deliverables:

- Candidate transition generation using selected beatgrid and section metadata.
- BPM/key/phrase compatibility scoring. Confident distant Camelot clashes reject
  the second-build drop-switch template; reverb exits keep warning-only key
  behavior because dry overlap is short.
- Intro/outro blend template.
- Build-to-drop swap template.
- Hard-cut fallback.
- Debug annotations.

Success:

- Generate a deterministic short set from analyzed tracks.
- Audition generated transitions in the desktop app.
- Bad transitions can be traced to analysis or strategy decisions.
- Generate a transition preview pack before spending time on a full WAV render.

## Phase 5.5: Pitch-Preserving Tempo Control

Target: next foundational playback/toolbox spec.

Spec:

- `.codex/specs/009-pitch-preserving-tempo-control.md`

Deliverables:

- Research and smoke-test serious Master-Tempo-style candidates: Rubber Band,
  SoundTouch, Signalsmith Stretch, Superpowered, zplane elastique, and related
  commercial SDKs where practical.
- Add MixPlan fields and renderer support for target BPM, tempo ratio,
  preserve-pitch intent, and tempo ramp metadata.
- Render tempo-matched WAV auditions without changing musical key.
- Keep transient nudge and beatgrid mapping correct after stretching.
- Let the planner consider one-sided incoming SoundStretch drop switches when
  the incoming deck can match the outgoing deck's BPM inside a configurable BPM
  window. Midpoint bridge ramps remain a later extension.

Success:

- User-auditioned stretched drop-switch examples sound acceptable.
- Default automatic planner window is documented and tunable.
- The selected backend's licensing, quality, runtime, and mobile/native risks
  are recorded.

## Phase 5.6: Canonical PCM And Drop-Anchor Timing Refinement

Target: immediately after Spec 009's first tempo-control pass.

Deliverables:

- Decode each source once to canonical PCM and use that same timing source for
  analysis, waveform, nudge, render, and audition paths.
- Audit timing-sensitive feature extraction for hidden sample-rate and
  frame-centering shifts.
- Build a drop-anchor candidate dataset from Rekordbox-labeled drop cues.
- Score exact drop-start transients using HPSS/percussive, multiband onset,
  low-band impact, bass persistence, and related DSP evidence.
- Generate same-BPM drop-switch auditions before changing defaults.

Success:

- Refined drop anchors equal or beat the current nudge path on regression pairs
  and improve known failure cases by user audition.

## Phase 5.7: Pitch/Key Shift Without Tempo Change

Target: after canonical timing work proves drop switches are stable.

Deliverables:

- Change key/Camelot by semitone steps without changing BPM.
- Preserve tempo/beatgrid alignment while testing pitch-shift quality.
- Integrate with Spec 008 key detection so harmonic compatibility can be
  achieved by candidate selection or controlled key shift.
- Keep formant/transient/stereo quality warnings explicit.

Success:

- A track can be shifted to a nearby Camelot-compatible key without disturbing
  BPM-sensitive transitions.

## Phase 6: Loop Tighten And Drop-Focused Transitions

Target: 1 to 2 weeks.

Deliverables:

- Loop command execution.
- Loop-tighten transition template.
- Better low-end automation.
- Timing tests with impulse/click fixtures.

Success:

- Loop-tighten into drop works on high-confidence beat grids.
- Drop-focused transitions remain gated by high-confidence timing evidence.

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

- A supervised drop-start dataset/training loop using Rekordbox-labeled XML as
  ground truth.
- Candidate-feature extraction from current heuristics, All-In-One/SongFormer
  boundaries, CUE-DETR/EDM-98 research outputs, beat-aligned mel/bass/onset
  features, and manual corrections.
- Strict holdout evaluation by song. Random beat-level splits are not
  acceptable.
- Confidence calibration and regression cleanup for `dubstep-phrase-hybrid`
  only if it remains useful as a candidate source.
- UI correction tools for section/cue errors.
- Regression fixtures from bad analysis cases.

Success:

- Trained drop-start recognition reaches an acceptance threshold high enough to
  replace Rekordbox labels for most tracks. Until then, Rekordbox labels remain
  the trusted oracle.

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
