# Implementation Plan

## Execution Rules

- Before starting any task, read `kiro.json`, `requirements.md`, `design.md`,
  and the required steering docs listed in `kiro.json`.
- Only mark a checkbox complete after implementing and verifying that task.
- Keep work within the task ownership unless the task explicitly says otherwise.
- Do not implement real audio analysis, real stem separation, mobile UI, or
  streaming-service integrations in this spec.
- If a task is blocked, leave it unchecked and add a short blocker note under
  that task with the command/error and affected requirement.

## Tasks

- [x] 1. Create root repository scaffolding
  - Create root `README.md`, `.gitignore`, `CMakeLists.txt`, and
    `CMakePresets.json`.
  - Document the MVP purpose, desktop-first direction, build commands, Python
    worker commands, and steering/spec doc locations in `README.md`.
  - Add ignore rules for CMake builds, Python virtual environments, Python cache,
    `.autodj-cache/`, generated stems/waveforms, local media, and common
    editor/OS files.
  - _Requirements: 1.1, 1.2, 1.3, 10.1, 10.2_

- [x] 2. Create target project directory layout
  - Create `apps/autodj-desktop`, `core/domain`, `core/repository`,
    `core/playback`, `core/dj`, `core/contracts`, `analysis/worker-python`,
    `fixtures`, `tools/scripts`, and `docs` directories.
  - Add placeholder `.gitkeep` files only where needed to preserve empty
    directories.
  - Ensure the layout matches `.codex/steering/04-project-structure.md`.
  - _Requirements: 1.4_

- [x] 3. Set up CMake foundation
  - Configure the root project for C++20.
  - Add subdirectories for `core/domain`, `core/repository`, `core/playback`,
    `core/dj`, and `apps/autodj-desktop`.
  - Enable CTest.
  - Add `debug` configure, build, and test presets.
  - Verify `cmake --preset debug` configures or document the blocker.
  - _Requirements: 2.1, 2.3, 10.1_

- [x] 4. Implement `autodj_domain` stub library and tests
  - Add `core/domain/CMakeLists.txt`.
  - Add public headers under `core/domain/include/autodj/domain/`.
  - Define `TrackId`, `PlanId`, `TimelineSeconds`, and `TrackSeconds`.
  - Add basic tests for construction/value access.
  - Register tests with CTest.
  - _Requirements: 2.2, 2.4, 3.1, 3.2, 3.3_

- [x] 5. Implement `autodj_repository` skeleton and tests
  - Add `core/repository/CMakeLists.txt`.
  - Add `IAudioRepository` and constructible `LocalAudioRepository`.
  - Keep scanning behavior as a placeholder only.
  - Add tests verifying construction and placeholder repository ID/state.
  - Ensure the module depends only on appropriate lower-level modules.
  - _Requirements: 2.2, 2.4, 2.5, 4.1, 4.2, 4.3, 4.4_

- [x] 6. Implement `autodj_playback` skeleton and tests
  - Add `core/playback/CMakeLists.txt`.
  - Add `PlaybackEngine`, `PlaybackState`, and `PlanValidationResult`.
  - Implement placeholder `loadPlan`, `play`, `pause`, `stop`, `seek`, and
    `getState`.
  - Add tests for validation and state transitions.
  - Read `.codex/steering/06-playback-engine.md` before implementation.
  - _Requirements: 2.2, 2.4, 2.5, 5.1, 5.2, 5.3, 5.4_

- [x] 7. Implement `autodj_dj` skeleton and tests
  - Add `core/dj/CMakeLists.txt`.
  - Add `IDJStrategy` and `DubstepDJStrategy`.
  - Make `DubstepDJStrategy` report support for `dubstep`.
  - Add a placeholder plan generation method that returns an empty or
    fixture-shaped plan without analyzing audio.
  - Add tests for construction, supported genre, and placeholder generation.
  - _Requirements: 2.2, 2.4, 2.5, 6.1, 6.2, 6.3, 6.4_

- [x] 8. Add minimal JUCE desktop app target
  - Add `apps/autodj-desktop/CMakeLists.txt`.
  - Configure a minimal `autodj_desktop` app target.
  - Implement a window with app title and placeholder regions for repository,
    analysis, mix plan, and playback.
  - Keep UI code thin and free of core business logic.
  - If JUCE setup blocks the task, document the exact command/error and keep the
    target structure in place.
  - _Requirements: 2.2, 2.4, 7.1, 7.2, 7.3, 7.4, 10.1_

- [x] 9. Add JSON contract schemas and examples
  - Create `core/contracts/schemas/analyzed-track.schema.json`.
  - Create `core/contracts/schemas/mix-plan.schema.json`.
  - Create `core/contracts/schemas/repository-manifest.schema.json`.
  - Create matching stub examples under `core/contracts/examples/`.
  - Include versioned top-level shapes documented in
    `.codex/steering/02-core-contracts.md`.
  - Do not reference real audio files.
  - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 10. Create Python analysis worker package
  - Add `analysis/worker-python/pyproject.toml`.
  - Add package files under `analysis/worker-python/src/autodj_analysis/`.
  - Implement `python -m autodj_analysis --help`.
  - Implement `classify <audio-path>` returning a stub dubstep `GenreVerdict`.
  - Implement `analyze <audio-path> --out <output-dir>` writing stub
    `analyzed-track.json`.
  - Read `.codex/steering/07-analysis-pipeline.md` before implementation.
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.6_

- [x] 11. Add Python tests
  - Add pytest tests for stub genre classification.
  - Add pytest tests for stub analyze artifact creation.
  - Add pytest tests or CLI invocation coverage for expected top-level keys.
  - Verify the documented Python install/test commands or document blockers.
  - _Requirements: 9.5, 10.2_

- [x] 12. Run foundation verification and update task status
  - Run `cmake --preset debug`.
  - Run `cmake --build --preset debug`.
  - Run `ctest --preset debug`.
  - Create a Python virtual environment if needed.
  - Run editable Python install.
  - Run Python tests.
  - Run `python -m autodj_analysis --help`.
  - Update this file's checkboxes only for verified completed tasks.
  - Document any blockers with command output summaries and affected
    requirements.
  - _Requirements: 10.1, 10.2, 10.3, 10.4_
