# Adaptive MIR And AutoDJ Research Dossier

Researched: 2026-05-17

## Executive Decision

The next implementation wave should evaluate a small set of high-signal
candidates rather than trying every library in the ecosystem.

First-wave `evaluate-now` candidates after installation and smoke testing:

1. `current-autodj-signal`: incumbent BPM/beatgrid and debug baseline.
2. `beat-this`: modern beat/downbeat model with clean PyPI install path,
   MIT-licensed code, published ISMIR 2024 paper, manageable model sizes, and
   a real CUDA smoke test in the WSL analysis environment.
3. `all-in-one`: joint timing and functional segment boundary/label model. It
   is operational for BPM, beatgrid, downbeats, and sections on real music in
   the WSL analysis environment, despite heavier PyTorch/NATTEN/Demucs
   dependencies.
4. `essentia-rhythm`: fast C++/Python reference for BPM and beat positions,
   useful as a comparison and potential native path, subject to AGPL/commercial
   licensing decisions.
5. `songformer`: latest functional music structure candidate. The runtime and
   official Hugging Face model path now smoke-test successfully as a section
   candidate.

The current BPM/beatgrid analyzer remains the incumbent to beat. It should not
be replaced unless a candidate is measurably better against Rekordbox XML or
gives a clear operational benefit. The current heuristic section labeler should
be treated as a weak fallback only; it is not worth protecting as the primary
section architecture.

## Timing Selection Outcome

Task 10 benchmarked `current-autodj-signal`, `essentia-rhythm`, `beat-this`,
and `all-in-one` against the local Rekordbox XML exports for BackspinBass,
headache, VERTIGO, and new-feelings. Task 11 manual verification accepted the
benchmark interpretation, and Task 12 selected `current-autodj-signal` for BPM
and beatgrid.

The winning rationale is pragmatic: the incumbent matched normalized BPM and
complete beat count on all known songs, stayed compatible with existing
artifacts, has no optional model/runtime/license dependency, and is project
owned. `beat-this` remains a useful comparison backend but emitted sparse beat
grids and no native BPM; `all-in-one` had reasonable BPM but sparse/late grids
and high runtime; `essentia-rhythm` was fast but less accurate in beat phase and
has AGPL/commercial licensing risk.

Important benchmark lesson: nearest candidate-beat median error is not enough.
Sparse grids can look strong when each emitted beat lands near a reference beat
while many reference beats are missing. Future timing reports must include beat
coverage and reference-beat recall.

## Research Method

Sources were limited to primary or near-primary references where possible:
academic papers, official repositories, official package pages, official docs,
and provider API docs. Blog/forum material was used only to discover candidate
names, not as decision evidence.

Each candidate was assessed for:

- output relevance,
- install path,
- license and model-data terms,
- local/offline viability,
- hosted/API viability,
- compute cost,
- Windows/WSL/future mobile risk,
- AutoDJ fit,
- evaluate/defer/reject decision.

No backend code was implemented in this task. No real music or local benchmark
artifacts were added.

## Timing: BPM, Beatgrid, Downbeats, And Meter

| Candidate | Outputs | Install/runtime | License/model terms | Compute and platform | AutoDJ fit | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| `current-autodj-signal` | BPM, normalized BPM, beat grid, confidence, waveform alignment metadata | Already in repo/WSL analysis env | Project-owned | Fast, local, deterministic; known good on current songs | Strong incumbent; must be benchmarked against Rekordbox XML before replacing | `evaluate-now` |
| `beat-this` | Beats and downbeats; optional DBN path | `pip install beat-this`; needs PyTorch, `tqdm`, `einops`, `soxr`, `rotary-embedding-torch`; FFmpeg/torchaudio for non-WAV | MIT code; model/data terms need final review | GPU optional, CPU fallback; main models about 78 MB, small models about 8.1 MB per upstream docs | Best first ML beatgrid candidate: modern, focused, installable, no mandatory madmom unless DBN is requested | `evaluate-now` |
| `all-in-one` | BPM, beats, downbeats, beat positions, functional segment boundaries, and labels through the installed Python API | Installed locally with PyTorch, NATTEN, latest CPJKU madmom, Demucs, TorchCodec, and FFmpeg support | MIT code | Heavy; upstream reports 10 songs / 33 minutes in 73 seconds on RTX 4090 plus i9-10940X; MP3 timing offsets explicitly warned | Strong joint timing and section candidate; benchmark it against Rekordbox before trusting it over the incumbent | `evaluate-now` |
| `essentia-rhythm` | BPM, beat ticks, confidence, BPM estimate distribution, beat intervals | Already available in WSL extra; RhythmExtractor2013 expects 44.1 kHz input | AGPLv3 for non-commercial, commercial license available | Local C++/Python, likely faster than PyTorch models; WSL verified, Windows Python unsupported per existing survey | Good reference and possible native path, but not expected to beat Rekordbox-quality grids alone | `evaluate-now` |
| `BeatNet` | Beats, downbeats, tempo, meter; online/offline modes | `pip install BeatNet`; 22.05 kHz input expected for raw audio object | CC-BY-4.0 repository/model terms need review | Local PyTorch; inherits madmom/offline dependency concerns | Useful fallback if `beat-this` or `all-in-one` underperform; less attractive as first wave due overlap and dependency friction | `defer` |
| `madmom` | RNN beat activations, DBN beat tracking, downbeats, tempo, meter | Source install likely required for modern Python | BSD source, CC BY-NC-SA model/data files unless otherwise indicated | Old dependency ecosystem; model terms problematic for commercial product | Important reference, but more as transitive dependency or comparison than primary product path | `defer` |
| `Beat Transformer` | Beat and downbeat tracking from demixed instrument spectrograms | Research repo/Colab; no simple package path found | MIT code | Requires demixed spectrogram pipeline and large preprocessed datasets for reproduction | Strong research evidence for stem-aware timing; operationally heavier than `beat-this`/`all-in-one` | `defer` |
| `BEAST` | Online beat/downbeat with streaming Transformer | Paper found; production package path not established | Needs review | Designed for <50 ms online latency; online focus is not needed for offline POC | Interesting later if live/adaptive sync matters; not needed for offline known-song analysis | `defer` |
| `aubio` | Onset, tempo, beat, pitch, MFCC | Python package or native tools | GPLv3-or-later | Lightweight C path, cross-platform, license risk | Useful validator, but unlikely to outperform current/ML candidates on exact DJ beatgrid | `defer` |
| `QM Vamp Bar/Beat Tracker` | Beats, bars, beat count, tempo; Vamp plugin path | Native plugin host and plugin install | QM/Vamp plugin bundle licensing requires review | Cross-platform binary/plugin operational overhead | Good external validator and Mixxx-adjacent reference; too much packaging for first wave | `defer` |
| `Superpowered Analyzer` | BPM, key, beatgrid, bars, waveform, compact music structure | Commercial native SDK | Commercial/proprietary | Cross-platform including mobile and web; very relevant to final product | Strong future native/mobile candidate, but not an academic/open POC backend | `defer` |
| `librosa.beat` | Tempo and beat tracking helper | Already in baseline extras | ISC | Fast local Python; already used by current analyzer | Useful feature baseline, not enough by itself for final beatgrid selection | `defer` as standalone |

### Timing Notes

- `beat-this` is the cleanest first-wave ML timing candidate because it is
  current, packaged, directly predicts beats/downbeats, and avoids DBN unless
  requested.
- `all-in-one` remains strategically important because it joins metrical and
  functional structure analysis. Synthetic click fixtures are not sufficient
  timing smoke tests for this model; real music must be used for capability
  proof and benchmarking.
- `all-in-one` explicitly warns that MP3 decoder differences can introduce
  20-40 ms offsets, matching the viewer issue already found in Spec 004. Any
  benchmark must standardize either WAV input or apply an MP3 timeline offset
  consistently.
- `essentia-rhythm` should be evaluated for speed, native portability, and
  comparative accuracy, not assumed to be the final winner.

### All-In-One Spike Notes

Operational status on 2026-05-17:

- Installed `allin1==1.1.0`, `demucs==4.0.1`, CUDA-enabled
  `torch==2.12.0+cu130`, `torchaudio==2.11.0`, `torchcodec==0.12.0`, CPJKU
  `madmom==0.17.dev0`, and a local source build of `natten==0.21.6`.
- NATTEN `0.14.6` has the legacy symbols expected by All-In-One but does not
  compile cleanly against the local PyTorch 2.12 stack. The adapter therefore
  installs a compatibility shim over NATTEN `0.21.6` before importing All-In-One.
- The local NATTEN `0.21.6` source build required CUDA 13 build wheels and
  venv-local CUDA library symlinks so CMake could resolve `cudart`; this must
  be preserved in setup notes before another machine tries to reproduce it.
- A synthetic click-fixture smoke executed Demucs, spectrogram extraction, and
  All-In-One inference successfully, but produced no beats. That result only
  proves structured empty-output handling; it is not a timing capability test.
- A real-song smoke on `BackspinBass.mp3` produced `tempoStatus=ok`,
  `bpm=140.0`, `beatGridStatus=ok`, `beatCount=273`, `downbeatCount=69`,
  `sectionStatus=ok`, and `sectionCount=9`.
- The adapter registers All-In-One for tempo, beat-grid, and section contracts.

The Python API is practical for timing and section analysis:
`allin1.analyze(path, ...)` returns `bpm`, `beats`, `downbeats`,
`beat_positions`, and segment data containing `start`, `end`, and `label`. The
adapter maps timing into the tempo/beat-grid contracts and maps functional
segments conservatively into the project section contract.

MP3/WAV timeline handling remains critical. Upstream explicitly recommends
converting MP3 to WAV first and reports observed MP3 decoder offset variations
of about 20-40 ms. The adapter therefore prefers `AnalysisContext.analysis_audio_path`
and records the selected timeline mode, FFmpeg availability/path, byproduct
directories, device choice, and processing behavior in provenance.

## Semantic Sections, Structure, And Cues

| Candidate | Outputs | Install/runtime | License/model terms | Compute and platform | AutoDJ fit | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| `all-in-one` | Functional segment boundaries and labels such as intro, verse, chorus, bridge, outro, plus timing outputs | Installed locally; PyTorch + NATTEN compatibility shim + CPJKU madmom + Demucs/FFmpeg support | MIT code; model/data terms need review | Heavy but documented; supports activations and embeddings at 100 FPS | Best immediate replacement candidate for the current section heuristic; needs label mapping for build/drop/break | `evaluate-now` |
| `songformer` | Functional music structure boundaries and labels; large heterogeneous training data and benchmark | Installed locally with Transformers 4.51.3, Hugging Face model snapshot, PyTorch, MuQ, MSAF compatibility shim, and custom-code inference | CC-BY-4.0 repository/model card terms; dependency/model-data terms still need review | New 2025/2026 work; real model smoke works on local CUDA stack | Potentially strongest semantic section model; likely better for pop labels than EDM-specific drops | `evaluate-now` |
| `cue-point-object-detection` | DJ cue points as object detections; cue dataset and model checkpoints claimed public | Direct package path not found in this pass | Needs code/data license review | Model uses object-detection framing over spectrogram-like input | Highly relevant to mix-in/out and phrasing; not enough install clarity for first implementation wave | `defer` |
| `automatic-cue-switch-points` | EDM switch points for DJ mixing, based on DJ rules, feature extraction, novelty analysis | Paper and code/dataset referenced by arXiv; exact install path needs follow-up | Needs code/dataset license review | Lightweight compared with deep models | Very relevant for mix-section selection; better for future cue ranking than section labels | `defer` |
| `MSAF` | Structure boundaries and repeated-section grouping | Existing survey found import failure with current SciPy line | MIT | Python framework, older ecosystem | Useful reference for boundaries, weak for semantic DJ labels | `defer` |
| `structural-function-7class` | Intro, verse, chorus, bridge, outro, instrumental, silence | Paper found, no simple package path established | Needs review | Deep-learning framework | Good taxonomy reference; lacks build/drop/break labels and install path | `defer` |
| `current-heuristic-sections` | Rough intro/build/drop/outro from energy/onsets | Already in repo | Project-owned | Fast, local | Weak; can be retained only as fallback/candidate feature source | `defer` as fallback only |
| `Cyanite segments` | 15-second mood/genre/instrument/energy segments; BPM/key and metadata | Hosted API | Commercial/API terms | Network, cost, privacy; no sub-beat timing | Useful semantic enrichment and set planning, too coarse for exact cue/section boundaries | `defer` |

### Semantic Section Benchmark Outcome

Task 14 benchmarked `current-autodj-signal`, `all-in-one`, and `songformer`
against the combined Rekordbox export at
`C:\Users\Brendan\Desktop\all_songs.xml`. The generated local artifacts are in
`.autodj-cache/semantic-section-benchmark/run-2026-05-18`.

All candidates ran successfully on BackspinBass, headache, VERTIGO, and
new-feelings, but no candidate is ready to select without further work and
manual review:

- `current-autodj-signal` matched 11 sections, missed 13 reference sections,
  had 3 false positives, missed 2 drops, and had 1 false positive drop. It
  found some drops, but section boundaries were poor.
- `all-in-one` matched 7 sections, missed 17 reference sections, had 9 false
  positives, and missed 7 drops. Its matched starts were close, but it mostly
  emitted pop-form/broad structural labels that remain `unknown` under the
  conservative DJ mapping.
- `songformer` matched 8 sections, missed 16 reference sections, had 11 false
  positives, and missed 7 drops. It behaved similarly to All-In-One: useful
  broad structure evidence, but not enough direct dubstep drop/build/break
  semantics.

The practical conclusion is that All-In-One and SongFormer are still valuable
feature sources, but the project needs an EDM/DJ-specific semantic layer before
either can drive transition planning. The current heuristic remains a weak
fallback only and should not be treated as the selected section backend.

### Section Label Mapping

The project label target should remain DJ-oriented:

```text
intro, verse, build, drop, break, outro, unknown
```

Repeated drops are ordered instances of the `drop` label, not extra labels:
`section-drop-001`, `section-drop-002`, `section-drop-003`, and so on. The
canonical `break` label covers breakdown/break-verse regions that often behave
like the next transition staging area in dubstep.

Most academic models use pop-form labels:

```text
intro, verse, chorus, bridge, outro, instrumental, silence
```

Required mapping strategy for task 13:

- `intro` -> `intro`
- `verse` -> `verse`
- `breakdown` or `break/verse` -> `break`
- `chorus` -> candidate `drop` only if energy/bass/onset evidence supports it;
  otherwise keep as `unknown`
- `bridge`/`instrumental` -> candidate `break` or `build` depending on energy
  slope and bass energy
- `outro` -> `outro`
- high-confidence rising pre-chorus/pre-drop energy -> `build`
- high-confidence low-vocal, high-bass, high-energy plateau on phrase boundary
  -> `drop`

No model should be allowed to emit high-confidence `drop` labels solely because
it predicts `chorus`.

### SongFormer Spike Notes

`python -m pip index versions songformer` returned no matching distribution, so
there is no normal PyPI package path. The official path is a GitHub repository,
submodules, a Python 3.10 conda environment, `pip install -r requirements.txt`,
and Hugging Face model files loaded through `transformers.AutoModel` with
`trust_remote_code=True`.

Operational status on 2026-05-17:

- Installed the public runtime stack that is available from package indexes:
  `transformers==4.51.3`, `huggingface-hub==0.30.2`, CUDA-enabled
  `torch==2.12.0`, `torchaudio==2.11.0`, TorchVision, TorchCodec, `muq`,
  `msaf`, `ema-pytorch`, and `x-transformers`.
- Downloaded the official Hugging Face model snapshot and ran the actual
  custom-code model path with `trust_remote_code=True`.
- Added a small SciPy compatibility shim because `msaf==0.1.80` still expects
  `scipy.inf`.
- Transformers 5.x failed model loading on this machine with a meta-device
  tensor error; the working stack is pinned to Transformers 4.51.x and
  Hugging Face Hub 0.30.x.
- Current smoke result: `sectionStatus=ok`, `sectionCount=1`,
  `sourceLabels=["verse"]`.

Primary-source availability status:

- Repository: `https://github.com/ASLP-lab/SongFormer`
- Model: `https://huggingface.co/ASLP-lab/SongFormer`
- Paper: `https://arxiv.org/abs/2510.02797`
- Hugging Face model card reports custom code, output segments with `start`,
  `end`, and `label`, expected raw-array input sample rate of 24,000 Hz, no
  deployed inference provider, F32 tensor type, and about 0.7B parameters.
- GitHub README reports Python environment setup with repo clone/submodules,
  Python 3.10, Ubuntu 22.04.1 testing, checkpoint fetch script, and claimed
  2-4 second whole-song inference on NVIDIA L40 excluding model loading.
- Repository `LICENSE` is CC-BY-4.0. This allows commercial use with
  attribution, but model/data and pretrained dependency terms for MuQ,
  MusicFM, and downstream datasets still need review before product use.

The adapter added in task 9 treats SongFormer as a semantic-section candidate
only. It does not emit BPM, beatgrid, cue points, stems, or energy evidence. Its
labels are therefore mapped conservatively into the AutoDJ section vocabulary:
direct `intro`, `verse`, `build`, `break`/`breakdown`, and `outro` pass through,
while pop-form labels such as `chorus`, `bridge`, `inst`, `instrumental`,
`pre-chorus`, `silence`, and `solo` remain `unknown` until a later evidence
layer can promote them safely.

Decision for this task: `evaluate-now-for-sections`. The backend contract
adapter is installed, the model path smoke-tests, and unavailable/failure
behavior remains structured so it does not block timing work or incumbent
analysis.

## Stem Separation

| Candidate | Outputs | Install/runtime | License/model terms | Compute and platform | AutoDJ fit | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| `Demucs` | Vocals, drums, bass, other; variants support two-stem vocal extraction | Python/PyTorch; existing steering notes archived upstream repo as of 2025 | MIT-style code, model/data review still needed | GPU recommended; CPU slow | Strong future enrichment for vocals, drums, bass, and drop/cue ranking; too heavy for required fast path | `defer` |
| `Spleeter` | 2/4/5-stem separation | Python/TensorFlow stack | MIT code per prior survey/papers | Older but simple; was used by Beat Transformer preprocessing | Useful baseline and possibly simpler than Demucs, but not best current quality | `defer` |
| `Open-Unmix` | Vocals, drums, bass, other | PyTorch reference implementation | MIT | Local, research-friendly | Useful benchmark/reference, less product-aligned than Demucs/RoFormer | `defer` |
| `BS-RoFormer` / `Mel-Band RoFormer` | Modern source separation; vocals/instrumentals/multistem depending model | PyTorch/community inference packages; checkpoint management varies | Code MIT in common repos; checkpoint licenses vary | High quality but operational/model zoo complexity | Future high-quality stems, not needed for Spec 005 completion | `defer` |
| `AudioShake` | Hosted/API stem separation and analysis | Hosted API / SDK | Commercial/API terms | Network/cost; CPU/GPU handled by provider | Good product-quality reference or fallback; not local/offline | `defer` |
| `Music AI stems` | Hosted workflow stem separation plus beat/BPM workflows | Hosted API | Commercial/API terms | Network/cost; provider workflows | Useful comparative backend if local models disappoint | `defer` |
| `zplane STEMS` | Native commercial source separation SDK | Commercial native SDK | Commercial | Native/mobile possible; paid | Strong future product candidate if licensing is acceptable | `defer` |

### Stem Decision

Stem separation should not be required to complete Spec 005 unless `all-in-one`
or another selected section model needs demixed input. Stems are likely a Spec
007/transition-quality feature, not the first section replacement.

## Mix Sections, Transition Techniques, And Automatic DJ Systems

| Candidate | Outputs | Install/runtime | License/model terms | Compute and platform | AutoDJ fit | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| Drum and Bass automatic DJ system | Full automatic DJ pipeline: beat/downbeat/structure, cue selection, track selection, EQ, transition types | Paper and open-source implementation referenced | Needs implementation/license review | Genre-specific, offline/live pipeline | Strategically very relevant because it mirrors AutoDJ architecture and genre-specific constraints | `defer` for strategy spec |
| `Mosaikbox` | Backend for automatic mixing with source separation, beat-grid estimation, KeyFinderService, stem modification | Python 3.11, Docker, MongoDB/KeyFinderService; GPU strongly recommended | Needs license review | Heavy app/backend, not a small library | Useful architecture reference; too broad for Spec 005 backend spike | `defer` |
| Automatic DJ cue switch points | Switch-point generation for EDM based on DJ rules | Paper/code/dataset referenced | Needs code/data license review | Likely lightweight if code is recoverable | Good candidate cue-ranker after section model exists | `defer` |
| Cue Point Estimation using Object Detection | Cue points, phrase adherence, model/dataset claimed public | Direct repo/package not found during this pass | Needs review | ML object detection; likely heavier than rule-based cue scoring | Interesting future cue candidate; not enough install clarity for first wave | `defer` |
| GAN/differentiable DSP transitions | EQ/fader transition generation | Research paper | Needs code/model review | ML training/inference complexity | Interesting transition-rendering research, not needed for analysis metadata | `defer` |
| DJ mix reverse engineering | Extract cue points, transition lengths, mix segmentation from real-world DJ mixes | Research dataset/analysis tools | Dataset/license review needed | Offline analysis | Useful future training/evaluation data for transition strategies | `defer` |

### Transition Decision

This spec should not implement transition technique generation. It should only
document which systems can inform future transition specs. The strongest future
direction is hybrid: reliable beatgrid and sections, deterministic phrase
alignment, and rule-based DJ transition templates, with ML only assisting cue
ranking or transition scoring.

## Set Planning, Similarity, And Track Compatibility

| Candidate | Outputs | Install/runtime | License/model terms | Compute and platform | AutoDJ fit | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| Essentia TensorFlow / Discogs EffNet / MusiCNN | Embeddings, genre/mood/danceability/tagging models | Essentia model downloads + TensorFlow inference | Essentia/model licenses need review | Local WSL/Python; potential native path via Essentia C++ but TF adds weight | Good for similarity, genre, mood, and library browsing; not timing truth | `defer` |
| `MERT` | Self-supervised music embeddings for downstream tasks | Hugging Face/GitHub; PyTorch | Model license/card review needed | Heavy ML model | Good future compatibility/mood/semantic embedding candidate | `defer` |
| `CLAP` / LAION-CLAP | Audio/text embeddings, zero-shot tags, retrieval | PyTorch/Hugging Face support | CC0 code/repo noted; checkpoint/data terms need review | Heavy but local | Good for search and semantic tags; not for beatgrid or exact sections | `defer` |
| `MuLan` | Joint music audio/text embedding | Paper; public package path unclear | Google model availability/licensing unclear | Likely not directly usable locally | Conceptually important, operationally weak for this project now | `reject` for implementation |
| Cyanite similarity | Similar tracks with filters for BPM, genre, key, voice, mood | Hosted API | Commercial/API terms | Network/cost/privacy | Useful future product reference; not local/offline MVP | `defer` |

### Set Planning Decision

Embedding and hosted similarity systems belong in a future set-planning spec.
They should not distract Spec 005 from beatgrid and section correctness.

## Hosted And Commercial Analysis Providers

| Candidate | Relevant outputs | Local/offline | Cost/privacy | AutoDJ fit | Decision |
| --- | --- | --- | --- | --- | --- |
| Music AI | Workflow-based BPM/beat map, stem separation, transcription | No | Upload/cost/vendor dependency | Good external reference backend if local timing candidates fail | `defer` |
| Klangio | Beat/downbeat timings, BPM, meter | No | Upload/cost/vendor dependency | Strong hosted timing reference candidate | `defer` |
| Cyanite | BPM, key, mood, genre, subgenre, voice, instruments, energy, 15s segments, similarity | No | Upload/cost/vendor dependency | Good semantic/set-planning reference, too coarse for beatgrid | `defer` |
| AudioShake | Stem separation, transcription, content analysis | No | Upload/cost/vendor dependency | Strong stem quality reference | `defer` |
| Superpowered | Native BPM, key, beatgrid, bars, waveform, compact music structure | Yes, commercial SDK | Licensing cost; not open research | Strong future native/mobile product candidate | `defer` |

Hosted systems should be optional comparison or fallback paths only. They should
not become mandatory for the desktop POC or future offline mobile goal.

## Rejected Or Low-Priority Candidates

| Candidate | Reason |
| --- | --- |
| Standalone `librosa.beat` as final backend | Already used as a baseline component; not strong enough by itself for Rekordbox-like exactness. |
| Raw current section heuristic as final backend | Too brittle on known songs and not semantically reliable. It may survive only as fallback or feature input. |
| MuLan implementation path | Strong paper, but no clear official local model/package path surfaced for direct implementation. |
| GAN transition generation in Spec 005 | Solves rendering/transition style, not analysis correctness. |
| Real-time/online-only beat trackers as first wave | Offline batch analysis can use whole-track evidence; online latency is not an MVP constraint. |

## Benchmark Plan For Task 2+

### Known Songs

Use the local known-song set and Rekordbox XML exports already established by
manual testing:

```text
BackspinBass
headache
VERTIGO
new-feelings
```

Do not commit audio, Rekordbox XML, or generated benchmark artifacts.

### Timing Metrics

For each backend:

- processing time,
- model/dependency load time,
- raw BPM,
- normalized BPM,
- BPM absolute error versus Rekordbox,
- first beat offset in milliseconds,
- median nearest-beat absolute error,
- 95th percentile nearest-beat absolute error,
- beat error at cue A/B/C/D where available,
- accumulated drift at track midpoint and near final cue,
- downbeat/bar alignment if emitted.

### Section/Cue Metrics

For each section backend:

- emitted labels,
- boundary times,
- confidence values,
- mapping from model labels to AutoDJ labels,
- nearest Rekordbox cue boundary error for cue-labeled sections,
- missed known drops/builds/breaks,
- false positive drops/builds/breaks,
- whether labels remain stable under MP3/WAV input normalization.

### Manual Checkpoint Artifacts

Every plausible candidate should produce:

- `analyzed-track.json`,
- `debug-waveform.json` or compatible waveform artifact,
- a benchmark summary JSON/Markdown file,
- enough provenance to identify backend, version, model, and parameters.

The task must stop for user review before final selection.

## First-Wave Implementation Recommendations

Task 2 should refine the spec around this concrete first wave:

1. Add backend contracts and benchmark harness.
2. Keep `current-autodj-signal` as incumbent backend.
3. Add `essentia-rhythm` candidate for speed/native comparison.
4. Add `beat-this` candidate for beat/downbeat ML comparison.
5. Add `all-in-one` candidate for joint timing and section comparison.
6. Add `songformer` as an installed section-analysis candidate.
7. Do not implement stems except where required by `all-in-one` or section
   candidates.
8. Do not implement set planning or transition generation in this spec.

## Future-Spec Backlog

Detailed handoff notes for future specs now live in
`deferred-candidates-and-future-specs.md`. Use that file as the first stop for
future stem, set-planning, transition, hosted-provider, embedding, and
native/mobile tasks before re-opening web research.

- Stem separation and vocal clash detection: Demucs, BS-RoFormer,
  AudioShake, Music AI, zplane STEMS.
- Set planning and track compatibility: Essentia embeddings, MERT, CLAP,
  Cyanite similarity, harmonic/key scoring.
- Transition technique generation: Drum and Bass automatic DJ architecture,
  Mosaikbox, differentiable DSP/GAN transition research.
- Native/mobile analyzer: Superpowered, Essentia C++ licensing, audioFlux C
  path, homegrown C++ ports of chosen algorithms.
- Manual correction UX: beatgrid drag/nudge, cue editing, section relabeling,
  and exporting/importing corrected metadata.

## Primary Sources

### Timing

- Beat This paper: https://arxiv.org/abs/2407.21658
- Beat This implementation: https://github.com/CPJKU/beat_this
- Beat This PyPI package: https://pypi.org/project/beat-this/
- All-In-One paper: https://arxiv.org/abs/2307.16425
- All-In-One implementation: https://github.com/mir-aidj/all-in-one
- BeatNet paper: https://arxiv.org/abs/2108.03576
- BeatNet implementation: https://github.com/mjhydri/BeatNet
- Beat Transformer paper: https://arxiv.org/abs/2209.07140
- Beat Transformer implementation: https://github.com/zhaojw1998/Beat-Transformer
- BEAST paper: https://arxiv.org/abs/2312.17156
- madmom implementation/license: https://github.com/CPJKU/madmom
- Essentia RhythmExtractor2013 docs: https://essentia.upf.edu/reference/std_RhythmExtractor2013.html
- Essentia beat detection tutorial: https://essentia.upf.edu/tutorial_rhythm_beatdetection.html
- QM Vamp plugin docs: https://vamp-plugins.org/plugin-doc/qm-vamp-plugins.html
- Superpowered Analyzer: https://superpowered.com/music-analysis-bpm-key-detection-waveform

### Structure And Cues

- All-In-One implementation: https://github.com/mir-aidj/all-in-one
- SongFormer paper: https://arxiv.org/abs/2510.02797
- Semantic structural functions paper: https://arxiv.org/abs/2205.14700
- MSAF implementation: https://github.com/urinieto/msaf
- MSAF docs: https://msaf.readthedocs.io/
- Automatic Detection of Cue Points for DJ Mixing: https://arxiv.org/abs/2007.08411
- Cue Point Estimation using Object Detection: https://arxiv.org/abs/2407.06823

### Stems

- Demucs paper: https://arxiv.org/abs/1909.01174
- Demucs implementation: https://github.com/facebookresearch/demucs
- Spleeter implementation: https://github.com/deezer/spleeter
- Open-Unmix implementation: https://github.com/sigsep/open-unmix-pytorch
- BS-RoFormer paper: https://arxiv.org/abs/2309.02612
- Mel-Band RoFormer paper: https://arxiv.org/abs/2310.01809
- BS-RoFormer implementation: https://github.com/lucidrains/BS-RoFormer
- AudioShake docs: https://developer.audioshake.ai/
- Music AI API docs: https://music.ai/docs/api/reference

### DJ Mixing, Set Planning, And Similarity

- Drum and Bass automatic DJ system: https://link.springer.com/article/10.1186/s13636-018-0134-8
- Mosaikbox thesis page: https://repositum.tuwien.at/handle/20.500.12708/212628
- Mosaikbox implementation: https://github.com/robaerd/mosaikbox
- Automatic DJ transitions with differentiable DSP/GANs: https://arxiv.org/abs/2110.06525
- DJ mix reverse engineering: https://arxiv.org/abs/2008.10267
- DJ mix analysis project: https://mir-aidj.github.io/djmix-analysis/
- MERT paper: https://arxiv.org/abs/2306.00107
- MERT implementation: https://github.com/yizhilll/MERT
- Essentia model catalog: https://essentia.upf.edu/documentation/models.html
- LAION-CLAP implementation: https://github.com/LAION-AI/CLAP
- MuLan paper: https://arxiv.org/abs/2208.12415
- Cyanite analysis docs: https://api-docs.cyanite.ai/docs/audio-analysis-v6-classifier
- Cyanite similarity docs: https://api-docs.cyanite.ai/docs/similarity-search/
- Klangio API docs: https://api-docs.klang.io/
