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

Spec 004 is the current real-analysis baseline. `analyze-batch` now adds
library-decoded signal analysis for waveform previews, energy and onset curves,
BPM, normalized dubstep tempo, beat markers, rough sections, and cue candidates.
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
requires the analysis dependencies documented below.

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
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pip install -e './analysis/worker-python[dev,analysis-wsl]'"
```

Verify generated fixtures and real-analysis dependencies with:

```powershell
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python -m analysis -q"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python/tests/test_batch.py::test_analyze_repository_manifest_runs_real_signal_analysis_for_generated_audio -q"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pip check"
```

The detailed one-song manual checkpoint lives in
[manual-known-song-checkpoint.md](.codex/specs/004-real-audio-analysis-baseline/manual-known-song-checkpoint.md).
Use it to run one local song through `analyze-batch` from WSL and inspect BPM,
normalized BPM, energy shape, rough sections, and cue candidates. Do not commit
the local song, generated manifest, generated summary, or `.autodj-cache/`
outputs.

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

- [.codex/specs/004-real-audio-analysis-baseline/kiro.json](.codex/specs/004-real-audio-analysis-baseline/kiro.json)
- [.codex/specs/004-real-audio-analysis-baseline/requirements.md](.codex/specs/004-real-audio-analysis-baseline/requirements.md)
- [.codex/specs/004-real-audio-analysis-baseline/design.md](.codex/specs/004-real-audio-analysis-baseline/design.md)
- [.codex/specs/004-real-audio-analysis-baseline/tasks.md](.codex/specs/004-real-audio-analysis-baseline/tasks.md)
- [.codex/specs/004-real-audio-analysis-baseline/manual-known-song-checkpoint.md](.codex/specs/004-real-audio-analysis-baseline/manual-known-song-checkpoint.md)

Completed spec packages:

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
