# Spec 001: Init Foundation

> Kiro-style execution package: `.codex/specs/001-init-foundation/`
>
> Use that folder's `kiro.json`, `requirements.md`, `design.md`, and `tasks.md`
> when executing implementation tasks. This file remains the source summary.

## Purpose

Initialize the repository so future agents can build features on a stable
foundation. This spec sets up project structure, build commands, schema
surfaces, stub modules, and tests. It should not attempt real DJ intelligence or
production audio DSP.

## Steering References

Read these before implementing:

- `.codex/steering/00-product-vision.md`
- `.codex/steering/01-system-architecture.md`
- `.codex/steering/02-core-contracts.md`
- `.codex/steering/03-tech-stack.md`
- `.codex/steering/04-project-structure.md`
- `.codex/steering/08-engineering-practices.md`

## Goals

- Create the repo skeleton described in `04-project-structure.md`.
- Add a root CMake project with predictable build/test commands.
- Add a minimal JUCE desktop app target.
- Add stub C++ libraries for domain, repository, playback, and DJ modules.
- Add JSON schemas for core artifacts.
- Add example valid fixtures.
- Add a Python analysis worker package with a stub CLI.
- Add a stub genre analyzer that returns `dubstep`.
- Add tests proving the foundation compiles and basic contracts are shaped.

## Non-goals

- No real audio analysis.
- No real stem separation.
- No production-quality deck playback.
- No mobile app.
- No Spotify or streaming integrations.
- No SQLite migration.
- No full Dubstep DJ algorithm.

## Required Deliverables

### Repository Files

Create:

```text
README.md
.gitignore
CMakeLists.txt
CMakePresets.json
```

The README should document:

- MVP purpose.
- Current supported platform.
- Build commands.
- Python analysis commands.
- Where steering/spec docs live.

The `.gitignore` should exclude:

- CMake build folders.
- Python virtual environments.
- Python cache files.
- `.autodj-cache/`
- generated stems/waveforms.
- local media import folders.
- editor/OS noise.

### C++ Structure

Create:

```text
apps/autodj-desktop/
core/domain/
core/repository/
core/playback/
core/dj/
core/contracts/
```

Each C++ module should have a `CMakeLists.txt` and compile as either a static
library or app target.

Minimum C++ targets:

- `autodj_domain`
- `autodj_repository`
- `autodj_playback`
- `autodj_dj`
- `autodj_desktop`

Minimum domain types:

- `TrackId`
- `PlanId`
- `TimelineSeconds`
- `TrackSeconds`

Minimum repository stub:

- `IAudioRepository`
- `LocalAudioRepository` skeleton that can be constructed but does not need full
  scanning yet.

Minimum playback stub:

- `PlaybackEngine` skeleton.
- `loadPlan`, `play`, `pause`, `stop`, `seek`, `getState` methods.
- Plan validation result type.

Minimum DJ stub:

- `IDJStrategy`.
- `DubstepDJStrategy` skeleton that can return an empty or fixture-backed
  `MixPlan` placeholder.

### JUCE Desktop App

Create a minimal JUCE app that:

- Builds through CMake.
- Opens a desktop window.
- Shows a basic app title and placeholder panels for repository, analysis,
  mix plan, and playback.
- Does not need real playback yet.

Keep UI wiring thin. Do not put core logic in the app component.

### Contracts And Schemas

Create:

```text
core/contracts/schemas/analyzed-track.schema.json
core/contracts/schemas/mix-plan.schema.json
core/contracts/schemas/repository-manifest.schema.json
core/contracts/examples/analyzed-track.stub.json
core/contracts/examples/mix-plan.stub.json
core/contracts/examples/repository-manifest.stub.json
```

The schemas should include at least the fields from `02-core-contracts.md` that
are required for stub artifacts:

- `schemaVersion`
- IDs.
- source/provenance.
- BPM/key placeholders.
- beat grid array.
- sections array.
- track placements.
- transitions.
- deck commands.

Do not overfit the first schema. It can be permissive where future analysis
fields are expected, but the known top-level shape should be validated.

### Python Analysis Worker

Create:

```text
analysis/worker-python/pyproject.toml
analysis/worker-python/src/autodj_analysis/__init__.py
analysis/worker-python/src/autodj_analysis/cli.py
analysis/worker-python/src/autodj_analysis/genre.py
analysis/worker-python/src/autodj_analysis/analyze.py
analysis/worker-python/tests/
```

Minimum CLI:

```powershell
python -m autodj_analysis --help
python -m autodj_analysis classify <audio-path>
python -m autodj_analysis analyze <audio-path> --out <output-dir>
```

Minimum behavior:

- `classify` returns a JSON `GenreVerdict` with `primaryGenre: "dubstep"`.
- `analyze` writes a stub `analyzed-track.json` matching the schema.
- The analysis stub should include obvious placeholder confidence values and a
  provenance object that says it is a stub.

Do not install heavy analysis dependencies in this spec. Keep Essentia/librosa
Demucs integration for a later spec.

### Tests

Add enough tests to prove the foundation works.

C++:

- Domain type construction.
- Playback engine accepts/rejects a trivial plan placeholder.
- DJ strategy can be constructed.

Python:

- Stub genre analyzer returns `dubstep`.
- CLI analyze command writes JSON.
- Generated JSON has expected top-level keys.

Schema:

- If a lightweight validator is introduced, validate example fixtures.
- If not, keep fixtures ready and add schema validation in a follow-up spec.

## Suggested Build Commands

C++:

```powershell
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
```

Python:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\python -m pip install -e .\analysis\worker-python[dev]
.\.venv\Scripts\python -m pytest .\analysis\worker-python
.\.venv\Scripts\python -m autodj_analysis --help
```

## Acceptance Criteria

- Repo has the target skeleton.
- CMake configures successfully.
- C++ build succeeds.
- C++ tests run through CTest.
- Minimal JUCE app target exists and builds.
- Python package installs in editable mode.
- Python tests pass.
- Stub `classify` command emits a dubstep verdict.
- Stub `analyze` command emits `analyzed-track.json`.
- Contract examples exist and match the documented top-level shapes.
- README documents how to run all foundation commands.

## Implementation Notes

- Use C++20.
- Keep dependencies minimal.
- If JUCE FetchContent setup is slow or blocked, document the exact blocker and
  still create the intended target structure.
- Do not add real audio files.
- Generated fixtures should be tiny JSON files.
- Keep all generated build artifacts out of git.

## Follow-up Specs

Likely next specs:

- `002-local-audio-repository.md`
- `003-analysis-mvp.md`
- `004-playback-engine-skeleton.md`
- `005-dubstep-dj-first-transitions.md`
