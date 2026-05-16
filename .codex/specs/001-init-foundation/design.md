# Design Document

## Overview

This design implements the first executable foundation for AutoDJ. The result is
a desktop-first, mobile-aware scaffold with C++ core boundaries, a JUCE desktop
app placeholder, JSON contracts, and a Python analysis-worker stub.

The design intentionally stops before real audio processing. It creates the
surfaces that future specs will fill in:

- Repository ingestion via `IAudioRepository`.
- Offline analysis via `autodj_analysis`.
- Strategy generation via `IDJStrategy`.
- Timeline execution via `PlaybackEngine`.
- Cross-language artifacts via JSON schemas.

## Steering Context

Implementation agents must read:

- `.codex/steering/00-product-vision.md`
- `.codex/steering/01-system-architecture.md`
- `.codex/steering/02-core-contracts.md`
- `.codex/steering/03-tech-stack.md`
- `.codex/steering/04-project-structure.md`
- `.codex/steering/08-engineering-practices.md`

Playback tasks should also read:

- `.codex/steering/06-playback-engine.md`

Analysis-worker tasks should also read:

- `.codex/steering/07-analysis-pipeline.md`

## Architecture

Foundation dependency direction:

```text
apps/autodj-desktop
  -> core/playback
  -> core/dj
  -> core/repository
  -> core/domain

analysis/worker-python
  -> core/contracts/schemas

core/playback
  -> core/domain

core/dj
  -> core/domain

core/repository
  -> core/domain
```

The foundation may keep JSON parsing minimal. Schema files and examples are
contract artifacts first; full generated bindings or runtime validation can come
later.

## Project Layout

Create this layout:

```text
AudioProj/
  README.md
  .gitignore
  CMakeLists.txt
  CMakePresets.json

  apps/
    autodj-desktop/
      CMakeLists.txt
      src/

  core/
    domain/
      CMakeLists.txt
      include/autodj/domain/
      src/
      tests/
    repository/
      CMakeLists.txt
      include/autodj/repository/
      src/
      tests/
    playback/
      CMakeLists.txt
      include/autodj/playback/
      src/
      tests/
    dj/
      CMakeLists.txt
      include/autodj/dj/
      src/
      tests/
    contracts/
      schemas/
      examples/

  analysis/
    worker-python/
      pyproject.toml
      src/autodj_analysis/
      tests/

  fixtures/
    audio/
    metadata/
    plans/

  tools/
    scripts/

  docs/
    decisions/
    diagrams/
```

## CMake Design

Root `CMakeLists.txt` should:

- Require CMake 3.24 or newer unless a lower version is specifically chosen.
- Set C++20.
- Enable testing.
- Add subdirectories for core modules and the desktop app.
- Keep third-party setup isolated.

`CMakePresets.json` should define at least:

- `debug` configure preset.
- `debug` build preset.
- `debug` test preset.

Preferred commands:

```powershell
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
```

## JUCE Desktop App Design

The desktop app should be minimal. It exists to prove the app target builds and
launches.

UI placeholder regions:

- Repository.
- Analysis.
- Mix Plan.
- Playback.

Implementation guidance:

- Use JUCE through CMake.
- If FetchContent is used, keep it in the desktop app or a small dependency
  wrapper.
- If JUCE setup blocks implementation, still create the intended target shape
  and document the blocker with the exact command/error.
- Do not put repository scanning, analysis, DJ strategy, or playback logic in UI
  components.

## C++ Module Design

### `autodj_domain`

Minimum responsibility:

- Shared IDs and time values.

Suggested types:

```cpp
namespace autodj::domain {
struct TrackId { std::string value; };
struct PlanId { std::string value; };
using TimelineSeconds = double;
using TrackSeconds = double;
}
```

Tests:

- Construct IDs.
- Verify stored values.
- Verify time aliases/wrappers can be used by other modules.

### `autodj_repository`

Minimum responsibility:

- Define the repository boundary.
- Provide a constructible local repository skeleton.

Suggested interface:

```cpp
class IAudioRepository {
public:
    virtual ~IAudioRepository() = default;
    virtual std::string repositoryId() const = 0;
};
```

`LocalAudioRepository` may accept a root path but does not need to scan yet.

### `autodj_playback`

Minimum responsibility:

- Define the playback engine boundary.
- Provide placeholder state transitions and plan validation result.

Suggested surface:

```cpp
class PlaybackEngine {
public:
    PlanValidationResult loadPlan(const std::string& planJson);
    void play();
    void pause();
    void stop();
    void seek(domain::TimelineSeconds timelineSeconds);
    PlaybackState getState() const;
};
```

The placeholder can treat any non-empty plan string as valid unless a simple
fixture parser is added. Keep the API easy to replace with structured types.

### `autodj_dj`

Minimum responsibility:

- Define strategy contract.
- Provide `DubstepDJStrategy` placeholder.

Suggested surface:

```cpp
class IDJStrategy {
public:
    virtual ~IDJStrategy() = default;
    virtual std::string strategyId() const = 0;
    virtual std::vector<std::string> supportedGenres() const = 0;
    virtual std::string generatePlanPlaceholder() const = 0;
};
```

Future specs can replace string plans with structured `MixPlan` types.

## Contract Schema Design

Create permissive-but-useful JSON schemas:

- `analyzed-track.schema.json`
- `mix-plan.schema.json`
- `repository-manifest.schema.json`

Each schema should:

- Include `$schema`.
- Include `$id`.
- Require `schemaVersion`.
- Require the primary artifact ID.
- Require the minimum fields needed by stub fixtures.
- Allow additional fields where future analysis data is expected.

Create examples:

- `analyzed-track.stub.json`
- `mix-plan.stub.json`
- `repository-manifest.stub.json`

The examples should be tiny and should not reference real audio files.

## Python Worker Design

Use a package named `autodj_analysis`.

Package layout:

```text
analysis/worker-python/
  pyproject.toml
  src/autodj_analysis/
    __init__.py
    __main__.py
    cli.py
    genre.py
    analyze.py
  tests/
```

CLI commands:

```powershell
python -m autodj_analysis --help
python -m autodj_analysis classify <audio-path>
python -m autodj_analysis analyze <audio-path> --out <output-dir>
```

Use only standard library plus test/dev dependencies for this spec.

Suggested modules:

- `genre.py`: `classify_stub(audio_path) -> dict`
- `analyze.py`: `analyze_stub(audio_path, output_dir) -> Path`
- `cli.py`: argument parsing and command dispatch.
- `__main__.py`: entrypoint for `python -m autodj_analysis`.

Stub analyzed-track output should include:

- `schemaVersion`.
- `trackId`.
- `source`.
- `analyzer` provenance identifying the stub producer.
- `durationSeconds` placeholder.
- `tempo`, `key`, `beatGrid`, `sections`, `energy`, `vocals`, `cuePoints`,
  `quality`.

## Error Handling

Foundation behavior should be simple and explicit:

- Missing CLI arguments should return a normal argparse error.
- Analysis output directory should be created if missing.
- Placeholder C++ validation should return structured errors, not throw for
  expected invalid input.
- Build dependency blockers should be documented rather than hidden.

## Testing Strategy

C++ tests should run through CTest and cover:

- Domain construction.
- Repository skeleton construction.
- Playback validation and state transitions.
- DJ strategy construction and supported genre.

Python tests should run through pytest and cover:

- Stub genre verdict shape.
- Stub analysis artifact creation.
- CLI analyze command writes JSON with expected top-level keys.

Schema validation may be added in this spec if lightweight. If not, examples
must still be created and validation should be tracked as a future task.

## Implementation Constraints

- Do not add commercial or real local music files.
- Do not add real Essentia/librosa/madmom/Demucs/FFmpeg integrations.
- Do not add SQLite.
- Do not add mobile UI.
- Do not add Spotify/SoundCloud/streaming provider integration.
- Keep UI placeholder code thin.
- Keep core modules dependency-light.

