# Implementation Plan

## Execution Rules

- Before starting any task, read `kiro.json`, `requirements.md`, `design.md`,
  and the required steering docs listed in `kiro.json`.
- Only mark a checkbox complete after implementing and verifying that task.
- Keep work within the task ownership unless the task explicitly says
  otherwise.
- Do not implement BPM detection, key detection, section detection, waveform
  generation, stem separation, DJ strategy, playback, mobile UI, SQLite, or
  streaming-service integrations in this spec.
- Use generated temporary files and fake `ffprobe` test doubles. Do not add real
  music files.
- If a task is blocked, leave it unchecked and add a short blocker note under
  that task with the command/error and affected requirement.

## Tasks

- [x] 1. Review current analysis worker and contract surfaces
  - Read `analysis/worker-python` source and tests.
  - Read `core/contracts/schemas/analyzed-track.schema.json`.
  - Read `core/contracts/schemas/repository-manifest.schema.json`.
  - Identify reusable code from the current single-track stub and where new
    batch/probe/cache modules should live.
  - Document compatibility concerns in implementation notes only where useful.
  - _Requirements: 2.1, 5.1, 9.1_
  - Implementation note: keep the existing single-track `classify` and
    `analyze` stubs working while adding new `manifest.py`, `cache.py`,
    `probe.py`, and `batch.py` modules. Reuse JSON writing, ISO timestamp, and
    package version patterns from `analyze.py`, but do not reuse
    `stable_track_id()` or `stub_source_hash()` for manifest-driven batch
    artifacts because repository manifests already provide stable track IDs and
    real content hashes. The analyzed-track schema requires top-level tempo,
    key, beatGrid, sections, energy, vocals, cuePoints, and quality fields, but
    arrays can be empty and confidences can be low; batch artifacts should avoid
    the current stub's fake high-confidence beat/section/cue values. The
    analyzed-track schema does not explicitly list `formatHint` under
    `source`, but `additionalProperties` is enabled, so preserving it from the
    repository manifest is contract-compatible. No Python dependency changes are
    needed for the first manifest/cache/probe slices beyond standard-library
    subprocess and JSON handling.

- [x] 2. Add Python repository manifest reader
  - Add a small manifest reader for `repository-manifest.json`.
  - Recover repository ID, source metadata, and track assets needed for
    analysis.
  - Preserve source URI and content hash exactly from the manifest.
  - Resolve local source paths for probing.
  - Add tests for valid manifests, malformed JSON, and missing required fields.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 7.4_

- [x] 3. Add metadata cache path and artifact freshness helpers
  - Resolve `<cache-root>/tracks/<track-id>/analyzed-track.json`.
  - Add atomic JSON write helper.
  - Add helper to load existing analyzed artifacts safely.
  - Implement freshness checks against schema version, track ID, analyzer
    producer/version, source content hash, and parameters hash.
  - Add tests for path resolution, atomic writes, fresh artifacts, stale content
    hashes, stale analyzer versions, stale parameters hashes, malformed JSON,
    and `--force` behavior at the helper level if practical.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 4. Add FFprobe subprocess adapter
  - Implement an adapter around `ffprobe -v error -print_format json
    -show_format -show_streams <audio-file>`.
  - Parse duration, sample rate, channels, codec, bit rate, format, and tags.
  - Select the primary audio stream deterministically.
  - Return structured errors for missing executable, nonzero exit, invalid JSON,
    missing files, and no audio stream.
  - Add tests using fake `ffprobe` executables or subprocess test doubles.
  - Add an optional generated-WAV integration test that skips when real
    `ffprobe` is unavailable.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 7.1, 7.4_
  - Verification note: after installing `ffprobe` on PATH,
    `.\.venv\Scripts\python -m pytest .\analysis\worker-python\tests\test_probe.py -q -rs`
    passed 9/9 tests with no skipped tests. The full Python worker suite also
    passed 50/50 tests.

- [x] 5. Build analyzed-track artifacts from manifest tracks and probe data
  - Preserve repository track identity fields in the artifact source.
  - Populate real duration, sample rate, channels, and provider metadata from
    probe results.
  - Populate analyzer provenance with producer, producer version,
    created-at time, source content hash, and parameters hash.
  - Replace fake high-confidence BPM/beat/section data with explicit
    low-confidence placeholders.
  - Add quality warnings that musical analysis is not implemented yet.
  - Add tests for artifact field mapping and placeholder honesty.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 6. Implement batch analysis workflow
  - Iterate tracks from a repository manifest.
  - Skip up-to-date artifacts unless forced.
  - Probe and write stale or missing artifacts.
  - Continue processing when individual tracks fail.
  - Return a summary with total, analyzed, skipped, failed, per-track statuses,
    artifact paths, and structured errors.
  - Add tests for all-success, skip-current, rewrite-stale, force-rewrite, and
    partial-failure batches.
  - _Requirements: 1.2, 1.3, 4.5, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3_
  - Verification note: `.\.venv\Scripts\python -m pytest
    .\analysis\worker-python\tests\test_batch.py -q` passed 14/14 tests, and
    `.\.venv\Scripts\python -m pytest .\analysis\worker-python -q` passed
    55/55 tests.

- [x] 7. Add `analyze-batch` CLI command
  - Add `autodj-analysis analyze-batch <repository-manifest.json> --out
    <cache-root>`.
  - Add `--ffprobe`, `--force`, `--parameters-hash`, and `--json` options.
  - Make stdout useful for humans by default and machine-readable with `--json`.
  - Return exit code 0 for all analyzed/skipped, and nonzero for manifest-level
    or per-track failures after producing a summary.
  - Add CLI tests for help output, JSON summary output, successful run, manifest
    failure, and partial failure.
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 7.1, 7.2, 7.3, 7.4_
  - Verification note: `.\.venv\Scripts\python -m pytest
    .\analysis\worker-python\tests\test_cli.py -q` passed 7/7 tests,
    `.\.venv\Scripts\python -m pytest .\analysis\worker-python -q` passed
    60/60 tests, `.\.venv\Scripts\python -m autodj_analysis --help` passed,
    and `.\.venv\Scripts\python -m autodj_analysis analyze-batch --help`
    passed.

- [x] 8. Add schema or fixture validation for generated artifacts
  - Validate generated artifacts against the existing analyzed-track contract if
    a lightweight validator is already available.
  - If no validator is available, add focused tests for all required top-level
    fields and document that full JSON Schema validation remains future work.
  - Ensure artifacts do not include fake high-confidence musical analysis.
  - _Requirements: 5.1, 5.4, 5.5_
  - Verification note: no repo-local JSON Schema validator dependency is
    available, so focused tests now read the analyzed-track schema's required
    fields and validate generated builder and batch artifacts against those
    required sections. Full Draft 2020-12 JSON Schema validation remains future
    work. `.\.venv\Scripts\python -m pytest
    .\analysis\worker-python\tests\test_contract_shape.py -q` passed 3/3
    tests, and `.\.venv\Scripts\python -m pytest .\analysis\worker-python -q`
    passed 63/63 tests.

- [x] 9. Update README status and commands
  - Update `README.md` so it no longer says the project is only in foundation
    setup.
  - Document that spec 002 local repository/cache work is complete.
  - Add `analyze-batch` command examples.
  - Document that this phase only probes basic file metadata; BPM/key/sections
    are still not real.
  - Preserve warnings not to commit local music or generated cache artifacts.
  - _Requirements: 8.1, 8.2, 8.3_
  - Verification note: `README.md` now documents completed foundation and spec
    002 repository/cache work, the current manifest-driven `analyze-batch`
    workflow, `ffprobe` metadata-only scope, placeholder musical analysis, and
    local media/cache artifact commit warnings. `.\.venv\Scripts\python -m
    pytest .\analysis\worker-python -q` passed 63/63 tests,
    `.\.venv\Scripts\python -m autodj_analysis --help` passed, and
    `.\.venv\Scripts\python -m autodj_analysis analyze-batch --help` passed.

- [x] 10. Preserve analysis architecture boundaries
  - Search analysis worker code to confirm it does not import desktop UI,
    playback, DJ strategy, or C++ repository modules.
  - Confirm no Essentia/librosa/Demucs/numpy/scipy/soundfile dependencies were
    added in this spec.
  - Confirm no real audio files or generated cache artifacts were added to git.
  - Add a lightweight pytest or script guard if practical.
  - Document any intentional exceptions under this task before marking complete.
  - _Requirements: 7.4, 8.3_
  - Verification note: added `test_boundaries.py`, a lightweight pytest guard
    that parses analysis worker source imports, checks `pyproject.toml` for
    forbidden heavy analysis dependencies, and scans committable git paths for
    local media or generated cache artifacts. No intentional boundary
    exceptions were found. `.\.venv\Scripts\python -m pytest
    .\analysis\worker-python\tests\test_boundaries.py -q` passed 3/3 tests,
    `.\.venv\Scripts\python -m pytest .\analysis\worker-python -q` passed
    66/66 tests, `.\.venv\Scripts\python -m autodj_analysis --help` passed,
    and `.\.venv\Scripts\python -m autodj_analysis analyze-batch --help`
    passed.

- [x] 11. Run full verification and update task status
  - Run `.\.venv\Scripts\python -m pytest .\analysis\worker-python`.
  - Run `.\.venv\Scripts\python -m autodj_analysis --help`.
  - Run `.\.venv\Scripts\python -m autodj_analysis analyze-batch --help`.
  - Run `cmake --preset debug`.
  - Run `cmake --build --preset debug`.
  - Run `ctest --preset debug`.
  - Update this file's checkboxes only for verified completed tasks.
  - Document any blockers with command output summaries and affected
    requirements.
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_
  - Verification note: full verification passed. `.\.venv\Scripts\python -m
    pytest .\analysis\worker-python` passed 66/66 tests,
    `.\.venv\Scripts\python -m autodj_analysis --help` passed,
    `.\.venv\Scripts\python -m autodj_analysis analyze-batch --help` passed,
    `cmake --preset debug` configured successfully, `cmake --build --preset
    debug` built all targets successfully, and `ctest --preset debug` passed
    7/7 tests.
