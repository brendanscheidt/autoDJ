# AutoDJ

AutoDJ is a desktop-first, mobile-aware app for generating DJ-style sets from
local audio files. The MVP targets local WAV/MP3 imports and assumes the first
supported genre lane is dubstep or adjacent bass music.

The goal is to move beyond simple end-to-start crossfades. The planned engine
will analyze tracks offline, generate a genre-specific mix plan, and execute
that plan through a dumb deck-and-mixer playback engine.

## Current Status

The foundation setup is complete. The project has the repository skeleton, C++
module boundaries, JSON contract surfaces, Python analysis worker package, and
a minimal desktop app target.

Spec 002 local repository and metadata-cache work is complete: the C++
repository module can discover local WAV/MP3 files, assign stable track IDs,
compute content hashes, write/read `repository-manifest.json`, and resolve the
`.autodj-cache/` layout.

Spec 003 analysis MVP work is complete. The Python worker can read a repository
manifest, probe each local source file with `ffprobe`, write per-track
`.autodj-cache/tracks/<track-id>/analyzed-track.json` artifacts, and skip
artifacts that are already current.

Spec 004 real-analysis baseline work is complete. `analyze-batch` added
library-decoded signal analysis for waveform previews, energy and onset curves,
BPM, normalized dubstep tempo, beat markers, rough sections, and cue candidates.

Spec 005 adaptive MIR evaluation selected the current project-owned timing
stack, `current-autodj-signal`, for BPM and beatgrid. It also selected
`dubstep-phrase-hybrid` for semantic sections. That section backend combines the
selected beatgrid, energy/bass/onset evidence, All-In-One boundaries,
SongFormer boundaries, and dubstep phrase heuristics to emit
intro/verse/build/drop/break/outro sections. The old rough section heuristic now
exists only as a fallback when the selected semantic backend cannot run or emits
no usable sections.

Key, vocals, downbeats, and stems are still conservative placeholders unless a
future spec adds a defensible backend. The Python/WSL worker remains a POC and
reference analyzer; future mobile analysis must be ported to native/mobile-safe
code or licensed native libraries.

## Platform Direction

- First implementation target: desktop workbench.
- Core playback direction: portable C++20.
- Desktop app direction: JUCE.
- Analysis direction: Python offline worker.
- Future mobile direction: reuse the C++ playback core from a mobile shell.

Mobile UI, streaming-service integrations, production-grade key/section
analysis, and real stem separation are still out of scope for the current
slice.

## Architecture Summary

Planned pipeline:

```text
AudioRepository
  -> GenreAnalyzer
  -> TrackAnalyzer / AnalysisWorker
  -> MetadataCache
  -> DJStrategy
  -> MixPlan
  -> PlaybackEngine
  -> Desktop Workbench UI
```

The playback engine should execute a deck-control timeline. It should not own
repository, genre, analysis, or DJ strategy decisions.

## C++ Build Commands

The expected C++ verification commands are:

```powershell
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
```

JUCE is fetched by CMake for the desktop app target; no manual JUCE checkout is
required for the current build.

## Python Worker Commands

Set up and test the lightweight Windows Python worker with:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\python -m pip install -e .\analysis\worker-python[dev]
.\.venv\Scripts\python -m pytest .\analysis\worker-python
.\.venv\Scripts\python -m autodj_analysis --help
.\.venv\Scripts\python -m autodj_analysis analyze-batch --help
```

Single-file stub commands remain available:

```powershell
.\.venv\Scripts\python -m autodj_analysis classify <audio-path>
.\.venv\Scripts\python -m autodj_analysis analyze <audio-path> --out <output-dir>
```

Batch analysis consumes a repository manifest produced by the local repository
flow and writes analyzed artifacts into the metadata cache. Real signal analysis
requires the analysis dependencies documented below. By default, `analyze-batch`
uses `current-autodj-signal` for BPM/beatgrid and `dubstep-phrase-hybrid` for
semantic sections.

```powershell
.\.venv\Scripts\python -m autodj_analysis analyze-batch `
  <repository-manifest.json> `
  --out <cache-root>
```

Useful batch options:

```powershell
.\.venv\Scripts\python -m autodj_analysis analyze-batch `
  <repository-manifest.json> `
  --out <cache-root> `
  --ffprobe ffprobe `
  --json
```

For a quick smoke test without the heavy semantic ML dependencies, use the
rough-section fallback explicitly:

```powershell
.\.venv\Scripts\python -m autodj_analysis analyze-batch `
  <repository-manifest.json> `
  --out <cache-root> `
  --section-backend current-autodj-signal `
  --json
```

Install FFmpeg tools so `ffprobe` is available on `PATH` before running real
batch analysis.

## WSL Real-Analysis Environment

Use WSL/Linux Python 3.11 for the full MIR dependency set:

```powershell
wsl --status
wsl --list --verbose
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && python3.11 --version"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && python3.11 -m venv .venv-analysis"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pip install -U pip setuptools wheel"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pip install -e './analysis/worker-python[dev,analysis-wsl,all-in-one,songformer]'"
```

The full selected semantic backend uses All-In-One and SongFormer internally.
That means the WSL environment needs the `all-in-one` and `songformer` extras,
including PyTorch/Torchaudio, TorchCodec, NATTEN, Demucs, CPJKU madmom,
Transformers 4.51.x, Hugging Face Hub 0.30.x, MuQ, MSAF, and related model
runtime dependencies. This stack is intentionally WSL/Linux-oriented for the
POC. Windows Python can still run lightweight tests and rough-section smoke
tests, but the full semantic backend should be run in WSL.

Runtime and licensing constraints to keep in mind:

- `current-autodj-signal` is project-owned and remains the selected BPM/beatgrid
  path.
- `dubstep-phrase-hybrid` depends on All-In-One and SongFormer evidence. It is
  suitable for the local POC but still has model/dependency licensing and
  productization review before any commercial distribution.
- All-In-One code is MIT, but its heavy runtime includes Demucs, NATTEN, madmom,
  Torch/TorchCodec, and FFmpeg behavior that must remain documented.
- SongFormer repository/model-card terms are CC-BY-4.0, with downstream model
  and dataset terms still requiring review before product use.
- `essentia-rhythm`, `beat-this`, and standalone All-In-One timing remain
  comparison backends only; do not auto-fallback to them for production
  artifacts without another benchmark and manual verdict.

Verify generated fixtures and real-analysis dependencies with:

```powershell
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python -m analysis -q"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python/tests/test_batch.py::test_analyze_repository_manifest_runs_real_signal_analysis_for_generated_audio -q"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pip check"
```

The detailed one-song manual checkpoint lives in
[manual-known-song-checkpoint.md](.codex/specs/004-real-audio-analysis-baseline/manual-known-song-checkpoint.md).
Use it to run one local song through `analyze-batch` from WSL and inspect BPM,
normalized BPM, energy shape, semantic sections or fallback rough sections, and
cue candidates. Do not commit the local song, generated manifest, generated
summary, or `.autodj-cache/` outputs.

For large semantic section benchmark runs against Rekordbox XML, use
[large-set-semantic-benchmark-runbook.md](.codex/specs/005-adaptive-mir-candidate-evaluation/large-set-semantic-benchmark-runbook.md).
That benchmark path produces Rekordbox comparison reports, debug waveform JSON,
and copied source audio for manual inspection in the HTML viewer. Rekordbox XML
is evaluation truth only; normal `analyze-batch` generation does not receive
Rekordbox cue labels or reference section times.

## Steering And Specs

Read the steering docs before changing architecture or contracts:

- [.codex/steering/README.md](.codex/steering/README.md)
- [.codex/steering/00-product-vision.md](.codex/steering/00-product-vision.md)
- [.codex/steering/01-system-architecture.md](.codex/steering/01-system-architecture.md)
- [.codex/steering/02-core-contracts.md](.codex/steering/02-core-contracts.md)
- [.codex/steering/03-tech-stack.md](.codex/steering/03-tech-stack.md)
- [.codex/steering/04-project-structure.md](.codex/steering/04-project-structure.md)
- [.codex/steering/07-analysis-pipeline.md](.codex/steering/07-analysis-pipeline.md)
- [.codex/steering/08-engineering-practices.md](.codex/steering/08-engineering-practices.md)

Current executable spec package:

- [.codex/specs/005-adaptive-mir-candidate-evaluation/kiro.json](.codex/specs/005-adaptive-mir-candidate-evaluation/kiro.json)
- [.codex/specs/005-adaptive-mir-candidate-evaluation/requirements.md](.codex/specs/005-adaptive-mir-candidate-evaluation/requirements.md)
- [.codex/specs/005-adaptive-mir-candidate-evaluation/design.md](.codex/specs/005-adaptive-mir-candidate-evaluation/design.md)
- [.codex/specs/005-adaptive-mir-candidate-evaluation/tasks.md](.codex/specs/005-adaptive-mir-candidate-evaluation/tasks.md)
- [.codex/specs/005-adaptive-mir-candidate-evaluation/research-dossier.md](.codex/specs/005-adaptive-mir-candidate-evaluation/research-dossier.md)
- [.codex/specs/005-adaptive-mir-candidate-evaluation/deferred-candidates-and-future-specs.md](.codex/specs/005-adaptive-mir-candidate-evaluation/deferred-candidates-and-future-specs.md)

Completed spec packages:

- [.codex/specs/004-real-audio-analysis-baseline/kiro.json](.codex/specs/004-real-audio-analysis-baseline/kiro.json)
- [.codex/specs/004-real-audio-analysis-baseline/requirements.md](.codex/specs/004-real-audio-analysis-baseline/requirements.md)
- [.codex/specs/004-real-audio-analysis-baseline/design.md](.codex/specs/004-real-audio-analysis-baseline/design.md)
- [.codex/specs/004-real-audio-analysis-baseline/tasks.md](.codex/specs/004-real-audio-analysis-baseline/tasks.md)
- [.codex/specs/004-real-audio-analysis-baseline/manual-known-song-checkpoint.md](.codex/specs/004-real-audio-analysis-baseline/manual-known-song-checkpoint.md)
- [.codex/specs/003-analysis-mvp/kiro.json](.codex/specs/003-analysis-mvp/kiro.json)
- [.codex/specs/003-analysis-mvp/requirements.md](.codex/specs/003-analysis-mvp/requirements.md)
- [.codex/specs/003-analysis-mvp/design.md](.codex/specs/003-analysis-mvp/design.md)
- [.codex/specs/003-analysis-mvp/tasks.md](.codex/specs/003-analysis-mvp/tasks.md)
- [.codex/specs/001-init-foundation/tasks.md](.codex/specs/001-init-foundation/tasks.md)
- [.codex/specs/002-local-repository-metadata-cache/tasks.md](.codex/specs/002-local-repository-metadata-cache/tasks.md)

## Development Rules

- Do not commit local music files, generated cache artifacts, generated stems,
  generated waveform caches, or `.autodj-cache/`.
- Keep real-time playback separate from offline analysis.
- Keep provider-specific repository details out of playback and DJ strategy
  code.
- Treat JSON schemas and fixtures as the contract surface between C++ and
  Python modules.
