# Project Structure

## Target Layout

```text
AudioProj/
  README.md
  CMakeLists.txt
  CMakePresets.json
  .gitignore

  apps/
    autodj-desktop/
      CMakeLists.txt
      src/
      assets/

  core/
    domain/
      CMakeLists.txt
      include/autodj/domain/
      src/
      tests/
    contracts/
      schemas/
      examples/
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

  analysis/
    worker-python/
      pyproject.toml
      src/autodj_analysis/
      tests/
    profiles/
    notebooks/

  fixtures/
    audio/
    metadata/
    plans/

  tools/
    scripts/

  docs/
    decisions/
    diagrams/

  .codex/
    steering/
    specs/
```

## Directory Responsibilities

### `apps/autodj-desktop`

Owns the desktop application shell.

Allowed:

- JUCE UI code.
- Desktop app state.
- Workbench panels.
- Wiring between UI and core services.

Not allowed:

- Genre-specific DJ logic.
- Persistent contract definitions.
- Analysis algorithms that should live in `analysis`.
- Playback internals that should live in `core/playback`.

### `core/domain`

Owns shared C++ domain types that are not tied to a specific UI or provider.

Examples:

- Track IDs.
- Time types.
- Plan IDs.
- Enum types.
- Lightweight value objects.

Keep this dependency-light. It should compile fast and be easy to test.

### `core/contracts`

Owns schema and fixture definitions for data crossing module/process boundaries.

Examples:

- `analyzed-track.schema.json`
- `mix-plan.schema.json`
- `repository-manifest.schema.json`
- Valid example artifacts.
- Invalid example artifacts for validation tests.

The schemas are the source of truth for JSON artifacts. C++ and Python code must
match them.

### `core/repository`

Owns repository implementations.

MVP:

- `LocalAudioRepository`
- File scanning.
- Content hashing.
- Repository manifests.

Future:

- Other repository adapters, if allowed by source provider constraints.

### `core/playback`

Owns the real-time playback engine.

Examples:

- Deck model.
- Mixer model.
- Automation interpolation.
- Plan validation.
- Audio source buffering.
- Effects chain.

This module should be usable without the desktop UI.

### `core/dj`

Owns DJ strategy interfaces and C++ strategy implementations.

MVP:

- Interface definitions.
- Basic plan compiler helpers.
- Dubstep strategy can start here or in a subfolder such as
  `core/dj/dubstep`.

If early strategy work is faster in Python, it can live in `analysis` or a
future `strategy-python` package, but the emitted artifact must still be a
valid `MixPlan`.

### `analysis/worker-python`

Owns the offline analysis CLI and Python package.

Examples:

- `autodj-analysis analyze`
- `autodj-analysis analyze-batch`
- Essentia/librosa integrations.
- Demucs wrapper.
- JSON artifact writer.

This package should not import desktop UI code.

### `fixtures`

Stores small test fixtures.

Rules:

- Do not commit commercial music files.
- Prefer generated audio fixtures, short synthetic clips, or explicitly licensed
  samples.
- Keep fixture size small.
- Store expected metadata and mix plans for contract tests.

### `tools/scripts`

Houses developer scripts that wrap common workflows.

Examples:

- Dependency checks.
- Schema validation.
- Fixture generation.
- Formatting/lint entrypoints.

Scripts should be cross-platform when practical. PowerShell is acceptable for
Windows-only helper scripts, but core build commands should remain CMake/Python.

## Build Artifacts

Do not commit:

- `build/`
- `.venv/`
- Python cache files.
- Generated stems.
- Generated waveform caches.
- Local media imports.
- User-specific app state.

Generated analysis artifacts may be committed only when they are fixtures under
`fixtures/`.

## Naming

- C++ namespaces: `autodj::domain`, `autodj::playback`, `autodj::repository`,
  `autodj::dj`.
- Python package: `autodj_analysis`.
- JSON schema IDs: `autodj.<artifact-name>.v1`.
- Plan IDs: opaque strings such as `plan-<uuid>`.
- Track IDs: repository-stable opaque strings.

## Dependency Direction

Preferred dependency graph:

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
  -> core/contracts generated types/helpers

core/dj
  -> core/domain
  -> core/contracts generated types/helpers
```

Avoid circular dependencies. If two modules need the same type, move that type
to `core/domain` or a schema-generated contract layer.

## First Foundation Target

The first implementation spec should create this structure with compiling stubs,
not full functionality. A good foundation proves:

- CMake configures and builds.
- A minimal JUCE desktop app launches.
- A C++ domain/test target compiles.
- Python analysis CLI runs and emits stub JSON.
- JSON schemas exist and have valid example artifacts.

