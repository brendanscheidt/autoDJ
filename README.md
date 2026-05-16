# AutoDJ

AutoDJ is a desktop-first, mobile-aware app for generating DJ-style sets from
local audio files. The MVP targets local WAV/MP3 imports and assumes the first
supported genre lane is dubstep or adjacent bass music.

The goal is to move beyond simple end-to-start crossfades. The planned engine
will analyze tracks offline, generate a genre-specific mix plan, and execute
that plan through a dumb deck-and-mixer playback engine.

## Current Status

The foundation setup is complete. The project now has the repository skeleton,
C++ module boundaries, JSON contract surfaces, Python analysis worker package,
and a minimal desktop app target.

Spec 002 local repository and metadata-cache work is complete: the C++
repository module can discover local WAV/MP3 files, assign stable track IDs,
compute content hashes, write/read `repository-manifest.json`, and resolve the
`.autodj-cache/` layout.

Spec 003 analysis MVP work is in progress. The Python worker can read a
repository manifest, probe each local source file with `ffprobe`, and write
per-track `.autodj-cache/tracks/<track-id>/analyzed-track.json` artifacts while
skipping artifacts that are already current. This phase only records basic
container and stream metadata such as duration, sample rate, channel count,
codec, format, bit rate, and tags. BPM, key, beat grids, sections, waveform
generation, cue points, and stem separation are not real yet and are represented
as low-confidence placeholders.

## Platform Direction

- First implementation target: desktop workbench.
- Core playback direction: portable C++20.
- Desktop app direction: JUCE.
- Analysis direction: Python offline worker.
- Future mobile direction: reuse the C++ playback core from a mobile shell.

Mobile UI, streaming-service integrations, musical analysis, waveform
generation, and real stem separation are still out of scope for the current
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

Set up and test the Python analysis worker with:

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
flow and writes analyzed artifacts into the metadata cache:

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
  --parameters-hash sha256:ffprobe-v1-placeholders-v1 `
  --json
```

Install FFmpeg tools so `ffprobe` is available on `PATH` before running real
batch analysis. Heavy musical-analysis dependencies such as Essentia, librosa,
and Demucs are not part of this phase.

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

- [.codex/specs/003-analysis-mvp/kiro.json](.codex/specs/003-analysis-mvp/kiro.json)
- [.codex/specs/003-analysis-mvp/requirements.md](.codex/specs/003-analysis-mvp/requirements.md)
- [.codex/specs/003-analysis-mvp/design.md](.codex/specs/003-analysis-mvp/design.md)
- [.codex/specs/003-analysis-mvp/tasks.md](.codex/specs/003-analysis-mvp/tasks.md)

Completed spec packages:

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
