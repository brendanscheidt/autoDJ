# AutoDJ

AutoDJ is a desktop-first, mobile-aware app for generating DJ-style sets from
local audio files. The MVP targets local WAV/MP3 imports and assumes the first
supported genre lane is dubstep or adjacent bass music.

The goal is to move beyond simple end-to-start crossfades. The planned engine
will analyze tracks offline, generate a genre-specific mix plan, and execute
that plan through a dumb deck-and-mixer playback engine.

## Current Status

The project is in foundation setup. The initial implementation spec is building
the repository skeleton, C++ module boundaries, JSON contract surfaces, Python
analysis worker stub, and a minimal desktop app target.

## Platform Direction

- First implementation target: desktop workbench.
- Core playback direction: portable C++20.
- Desktop app direction: JUCE.
- Analysis direction: Python offline worker.
- Future mobile direction: reuse the C++ playback core from a mobile shell.

Mobile UI, streaming-service integrations, real audio analysis, and real stem
separation are out of scope for the initial foundation spec.

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

The expected C++ foundation commands are:

```powershell
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
```

At this stage the root CMake project is intentionally minimal. Later tasks in
the init spec add module targets and tests.

## Python Worker Commands

Once the Python analysis worker package is created by the init spec, use:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\python -m pip install -e .\analysis\worker-python[dev]
.\.venv\Scripts\python -m pytest .\analysis\worker-python
.\.venv\Scripts\python -m autodj_analysis --help
```

The first worker implementation is a stub. Heavy dependencies such as Essentia,
librosa, Demucs, and FFmpeg integration are planned for later specs.

## Steering And Specs

Read the steering docs before changing architecture or contracts:

- [.codex/steering/README.md](.codex/steering/README.md)
- [.codex/steering/00-product-vision.md](.codex/steering/00-product-vision.md)
- [.codex/steering/01-system-architecture.md](.codex/steering/01-system-architecture.md)
- [.codex/steering/02-core-contracts.md](.codex/steering/02-core-contracts.md)
- [.codex/steering/03-tech-stack.md](.codex/steering/03-tech-stack.md)
- [.codex/steering/04-project-structure.md](.codex/steering/04-project-structure.md)
- [.codex/steering/08-engineering-practices.md](.codex/steering/08-engineering-practices.md)

Current executable spec package:

- [.codex/specs/001-init-foundation/kiro.json](.codex/specs/001-init-foundation/kiro.json)
- [.codex/specs/001-init-foundation/requirements.md](.codex/specs/001-init-foundation/requirements.md)
- [.codex/specs/001-init-foundation/design.md](.codex/specs/001-init-foundation/design.md)
- [.codex/specs/001-init-foundation/tasks.md](.codex/specs/001-init-foundation/tasks.md)

## Development Rules

- Do not commit local music files, generated stems, generated waveform caches,
  or `.autodj-cache/`.
- Keep real-time playback separate from offline analysis.
- Keep provider-specific repository details out of playback and DJ strategy
  code.
- Treat JSON schemas and fixtures as the contract surface between C++ and
  Python modules.

