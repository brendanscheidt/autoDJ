# Engineering Practices

## General Standards

- Keep modules separated by the architecture docs.
- Prefer small, testable interfaces over framework-bound services.
- Keep the playback engine real-time safe.
- Make offline analysis deterministic and cacheable where practical.
- Do not commit local music files, stems, or generated cache data.
- Use source-controlled fixtures for contract and playback tests.

## Contract-First Development

For features that cross module boundaries:

1. Update or add the JSON schema.
2. Add a valid fixture.
3. Add an invalid fixture for important failure modes.
4. Update C++/Python readers/writers.
5. Add tests.

The schemas in `core/contracts/schemas` should be treated as the source of
truth. Steering docs explain intent; schemas define the executable shape.

## Testing Strategy

### C++ Tests

Use CTest through CMake.

Initial coverage:

- Domain value objects.
- JSON parsing/validation helpers.
- Mix plan validation.
- Automation interpolation.
- Command scheduling.
- Local repository scanning.

### Python Tests

Use `pytest`.

Initial coverage:

- Stub genre analyzer output.
- Analysis CLI writes schema-shaped JSON.
- Fixture manifests parse.
- Cue generation helpers.
- Cache key generation.

### Audio Fixtures

Use generated or licensed short fixtures.

Good synthetic fixtures:

- Click track with known BPM/downbeats.
- Sine bass pulses.
- Short noise risers.
- Impulse markers for timing tests.

Avoid committing commercial tracks. Local developer libraries should stay
outside git.

## Build Commands

The expected foundation commands are:

```powershell
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
```

For Python:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\python -m pip install -e .\analysis\worker-python[dev]
.\.venv\Scripts\python -m pytest .\analysis\worker-python
```

If `uv` is introduced later, keep equivalent pip commands documented.

## Real-Time Audio Rules

The audio callback must not:

- Allocate unbounded memory.
- Parse JSON.
- Wait on file I/O.
- Call Python.
- Call network APIs.
- Take blocking locks.
- Perform analysis.

Anything expensive belongs in a background thread or offline worker.

## Logging

Use structured logs where practical.

Important events:

- Import scan results.
- Analysis job start/end/failure.
- Cache invalidation.
- Mix plan generation summary.
- Transition selection reasons.
- Plan validation warnings.
- Playback load/play/stop/seek events.

Do not log from the audio callback except through a real-time-safe diagnostic
buffer designed for that purpose.

## Versioning

Version separately:

- JSON schemas.
- Analysis worker.
- DJ strategies.
- Playback engine.
- Cached artifacts.

Cached artifacts must identify which producer/version created them.

## Dependency Hygiene

- Keep C++ dependencies minimal in the core.
- Hide optional DSP libraries behind interfaces.
- Keep Python analysis dependencies isolated from the desktop app build.
- Pin dependency versions once implementation begins.
- Re-check licenses before shipping any binary distribution.

## Documentation Updates

When changing architecture:

- Update the relevant steering file.
- Update contracts/schemas if data shape changes.
- Update the spec or create a new spec.
- Include migration notes if cached artifacts are affected.

## Review Posture

When reviewing changes, prioritize:

- Real-time safety regressions.
- Contract drift.
- Hidden coupling between UI, DJ strategy, and playback.
- Missing confidence/fallback handling.
- Non-deterministic plan generation without a seed.
- Fixture or test gaps for timing behavior.

