# Implementation Plan

## Execution Rules

- Before starting any task, read `kiro.json`, `requirements.md`, `design.md`,
  and the required steering docs listed in `kiro.json`.
- Only mark a checkbox complete after implementing and verifying that task.
- Keep work within the task ownership unless the task explicitly says
  otherwise.
- Do not implement desktop UI, playback scheduling, DJ strategy generation,
  mobile UI, SQLite, stem separation, or streaming-service integrations in this
  spec.
- Use generated temporary audio fixtures and test doubles. Do not add real music
  files.
- Keep WSL/Linux analysis dependency assumptions out of native C++ app,
  playback, DJ, and repository modules.
- Treat Python/WSL as a POC/reference analyzer, not the final offline mobile
  runtime.
- Use strong Python/MIR libraries aggressively when they improve POC analysis
  quality.
- Record backend parameters, output quality, license/platform constraints, and
  future C++/mobile-portability notes for selected feature families.
- If a task is blocked, leave it unchecked and add a short blocker note under
  that task with the command/error and affected requirement.

## Tasks

- [x] 1. Review current analysis contracts and runtime assumptions
  - Read the required steering docs listed in `kiro.json`.
  - Read `analysis/worker-python` source and tests.
  - Read `core/contracts/schemas/analyzed-track.schema.json`.
  - Read the current README analysis status and setup commands.
  - Confirm the existing `analyze-batch` workflow, cache freshness keys, and
    boundary tests that will need updates for approved MIR dependencies.
  - Confirm steering now treats Python as POC/reference analysis and mobile as
    requiring a future native/offline analysis path.
  - Document implementation notes under this task if path/runtime constraints
    affect later tasks.
  - Implementation notes:
    - Current `analyze-batch` is still the Spec 003 ffprobe-only baseline: it
      writes producer `autodj_analysis.ffprobe`, version `0.1.0`, and parameter
      hash `sha256:ffprobe-v1-placeholders-v1`. Spec 004 must change producer or
      parameter identity when real signal analysis lands so cached placeholder
      artifacts are rewritten.
    - `cache.py` currently models only `analyzed-track.json`. Adjacent waveform
      artifacts need explicit cache path/freshness helpers, but can reuse the
      existing safe track directory and atomic JSON write pattern.
    - `analyzed-track.schema.json` already has the required top-level fields for
      tempo, beat grid, sections, energy, vocals, cue points, and quality, and
      allows additional properties for backend provenance. A separate waveform
      artifact contract/schema is still a Spec 004 decision.
    - `test_boundaries.py` intentionally forbids MIR/runtime dependencies such
      as `essentia`, `librosa`, `numpy`, `scipy`, and `soundfile`; task 3 must
      replace that with an allowlisted dependency policy while keeping the
      existing no-media/no-cache-artifacts guard.
    - README still describes Spec 003 as in progress and says heavy analysis
      dependencies are out of phase. Task 12 should update that status after the
      dependency/runtime path is proven.
    - WSL/Python 3.11 path handling is a real constraint: persisted `sourceUri`
      values should remain stable contract values while the analyzer explicitly
      resolves Windows and WSL filesystem paths at runtime.
  - _Requirements: 1.4, 2.5, 9.1, 10.1, 11.1, 12.1, 12.2_

- [x] 2. Establish WSL Ubuntu and Python 3.11 checkpoint
  - Verify WSL status from Windows with `wsl --status`.
  - Verify an Ubuntu distribution is installed and reachable.
  - Verify or install Python 3.11 inside WSL.
  - Record the exact WSL distro and Python version in this task's verification
    note.
  - If Python 3.11 cannot be installed quickly, stop and document the blocker
    with command output rather than continuing into analysis implementation.
  - Verification note:
    - `wsl --status`: default distribution `Ubuntu-24.04`, default version `2`.
      WSL reported that WSL1 is not supported with the current machine
      configuration, but the verified distro is running on WSL2.
    - `wsl --list --verbose`: `Ubuntu-24.04` is installed, running, and using
      WSL version `2`.
    - `wsl -d Ubuntu-24.04 -- bash -lc "cat /etc/os-release | grep '^PRETTY_NAME='"`:
      `PRETTY_NAME="Ubuntu 24.04.4 LTS"`.
    - `wsl -d Ubuntu-24.04 -- bash -lc "python3.11 --version"`:
      `Python 3.11.15`.
    - `wsl -d Ubuntu-24.04 -- bash -lc "python3.11 -m venv /tmp/py311-check && /tmp/py311-check/bin/python --version && rm -rf /tmp/py311-check"`:
      `Python 3.11.15`.
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 3. Research candidate MIR libraries, add analysis extras, and set up WSL virtualenv
  - Create a candidate library matrix covering feature role, install command,
    license, platform constraints, POC value, and future mobile/native risk.
  - Include at least librosa, Essentia, madmom, BeatNet, aubio/aubio fork,
    MSAF, Vamp/QM plugins, audioFlux, pyAudioAnalysis, torchaudio, Basic Pitch,
    and mir_eval unless a source clearly disqualifies one.
  - Add approved optional dependency groups to
    `analysis/worker-python/pyproject.toml`.
  - Include NumPy, SciPy, librosa, SoundFile, and audio loading support in the
    base analysis extra.
  - Include Essentia in a WSL/Linux-specific analysis extra or equivalent
    documented install path.
  - Add candidate extras or documented install paths for libraries selected for
    immediate smoke testing.
  - Add or update `.gitignore` entries for any WSL analysis virtualenv path used
    by the spec.
  - Create the WSL analysis virtualenv and install the worker in editable mode
    with development and analysis extras.
  - Implementation notes:
    - Added `.codex/specs/004-real-audio-analysis-baseline/mir-library-survey.md`
      with candidate roles, install paths, licenses, platform constraints, POC
      value, and future native/mobile risk notes.
    - Added optional worker extras: `analysis` for NumPy/SciPy/librosa/SoundFile
      and audio loading support, `analysis-wsl` for the same stack plus
      Essentia, and `analysis-candidates` for audioFlux, pyAudioAnalysis, and
      mir_eval.
    - PyPI did not expose a final `essentia>=2.1b6` package for this Python
      3.11 environment. The verified WSL constraint is
      `essentia>=2.1b6.dev1389,<2.2`.
    - MSAF is included in the survey but deferred from the immediate candidate
      extra. It installed, but import verification failed with
      `ImportError: cannot import name 'inf' from 'scipy'` against SciPy
      `1.17.1`.
    - Added `.venv-analysis/` to `.gitignore` and updated the spec WSL
      verification commands to use the verified `Ubuntu-24.04` distro name.
    - Created `.venv-analysis` in WSL `Ubuntu-24.04` with Python `3.11.15` and
      installed the worker in editable mode with `[dev,analysis-wsl]`.
    - Verified WSL core imports: NumPy `1.26.4`, SciPy `1.17.1`, librosa
      `0.11.0`, SoundFile `0.13.1`, audioread `3.1.0`, and Essentia
      `2.1-beta6-dev`.
    - Verified candidate imports for the immediate smoke-test group:
      audioFlux `0.1.9`, mir_eval `0.8.2`, and pyAudioAnalysis `0.3.14`.
    - Verification commands:
      - `.\.venv\Scripts\python -m pytest .\analysis\worker-python`: 68 passed.
      - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`:
        67 passed, 1 skipped.
      - Windows and WSL `python -m autodj_analysis --help` and
        `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m pip check`: no broken requirements found.
  - _Requirements: 1.5, 2.1, 2.2, 2.3, 2.6, 2.7, 2.8, 2.9, 10.2, 12.1, 12.4_

- [x] 4. Add dependency smoke tests and boundary policy updates
  - Add pytest smoke tests for approved analysis dependencies.
  - Ensure native Windows base tests do not require Essentia.
  - Ensure WSL analysis verification imports Essentia or reports a documented
    blocker.
  - Add dependency-gated smoke tests for any candidate backends selected in task
    3.
  - Update boundary/dependency guard tests to allow only the approved analysis
    dependencies from this spec.
  - Confirm disallowed local media and generated cache artifact checks still
    work.
  - Implementation notes:
    - Added `autodj_analysis.dependencies.require_optional_dependency()` so
      future analysis backends can convert missing or broken optional
      dependency imports into structured `analysis_dependency_missing` or
      `analysis_dependency_import_error` worker errors instead of raw import
      tracebacks.
    - Added dependency smoke tests for the approved `analysis` extra packages:
      NumPy, SciPy, librosa, SoundFile, and audioread.
    - Added WSL-gated smoke coverage for Essentia. The test is skipped in a
      native Windows base venv, but required when running inside the verified
      Linux `.venv-analysis` environment or when
      `AUTODJ_REQUIRE_ANALYSIS_WSL=1` is set.
    - Added dependency-gated candidate smoke tests for the Task 3 immediate
      candidate group: audioFlux, mir_eval, and pyAudioAnalysis.
    - Updated dependency boundary tests so `analysis`, `analysis-wsl`, and
      `analysis-candidates` must exactly match the approved dependency sets and
      remain optional rather than direct project dependencies.
    - Refactored the local-media/generated-artifact git guard into a predicate
      with synthetic rejection/allowance tests, then kept the existing
      `git ls-files --cached --others --exclude-standard` scan.
    - Verification commands:
      - `.\.venv\Scripts\python -m pytest .\analysis\worker-python`: 84 passed,
        9 skipped. The skipped tests are optional MIR smoke tests in the native
        Windows base environment.
      - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`:
        92 passed, 1 skipped. The WSL run imported the analysis and candidate
        dependencies.
      - Windows `python -m autodj_analysis --help` and
        `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m pip check`: no broken requirements found.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 3.5, 11.1, 11.2_

- [x] 5. Add generated audio fixture helpers
  - Add test helper functions that generate temporary WAV files.
  - Generate deterministic 140 BPM click fixtures.
  - Generate deterministic 70 BPM halftime fixtures.
  - Generate deterministic energy-ramp fixtures with known low/high regions.
  - Generate a silence or near-silence fixture for low-confidence fallback
    tests.
  - Ensure generated files are temporary or ignored and never committed.
  - Implementation notes:
    - Added `analysis/worker-python/tests/audio_fixtures.py` with standard
      library helpers that generate mono 16-bit PCM WAV files under a
      caller-provided temp directory.
    - Added deterministic fixture helpers for 140 BPM click tracks, 70 BPM
      halftime click/pulse tracks with normalized 140 BPM metadata,
      low-to-high energy ramps, silence, and near-silence.
    - Added guardrails so generated fixture filenames must be plain `.wav`
      names with no directory components, preventing accidental path traversal
      or non-WAV outputs.
    - Added unit tests for WAV metadata, expected beat timing, raw/normalized
      BPM metadata, energy-ramp low/high RMS separation, silence and
      near-silence levels, deterministic byte output, temp-path confinement,
      and unsafe filename rejection.
    - Existing boundary tests still scan `git ls-files --cached --others
      --exclude-standard` and reject committable local media/generated cache
      paths; generated WAVs in this task are created only through pytest
      `tmp_path`.
    - Verification commands:
      - `.\.venv\Scripts\python -m pytest .\analysis\worker-python`: 93 passed,
        9 skipped.
      - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`:
        101 passed, 1 skipped.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 6. Add library-based audio loading boundary
  - Add a small audio loading module around the selected library stack.
  - Load local audio into mono floating-point PCM with sample rate and duration.
  - Convert missing dependency, decode, empty audio, and unsupported format
    failures into structured worker errors.
  - Keep ffprobe metadata probing separate from signal decoding.
  - Add tests for successful generated-WAV loading and expected decode failure.
  - Implementation notes:
    - Added `analysis/worker-python/src/autodj_analysis/audio_io.py` as the
      signal decode boundary. It keeps third-party `soundfile`, `numpy`, and
      `librosa` calls isolated from batch orchestration and separate from the
      existing `ffprobe` metadata adapter.
    - Added `DecodedAudio` with mono floating-point PCM samples, sample rate,
      decoded duration, source channel count, and source path.
    - Added `AudioLoadError.to_dict()` for structured expected failures:
      `audio_dependency_missing`, `audio_decode_error`, `audio_empty`, and
      `audio_unsupported_format`; missing source paths continue to report
      `source_missing` consistently with the existing probe path.
    - Loading uses SoundFile into `float32`, folds multi-channel input to mono,
      and defaults to deterministic analysis sample rate `22050`. Resampling is
      isolated behind librosa and only required when decoded source sample rate
      differs from the target rate.
    - Added tests using generated WAV fixtures for successful decode, native
      sample-rate preservation, resampling, malformed WAV decode failure, empty
      WAV failure, unsupported extension failure before dependency import,
      missing source reporting, missing optional dependency reporting, and
      silence fixture loading.
    - Verification commands:
      - `.\.venv\Scripts\python -m pytest .\analysis\worker-python`: 96 passed,
        15 skipped. The skipped tests are optional analysis/candidate smoke and
        dependency-gated decode tests in the native Windows base environment.
      - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`:
        110 passed, 1 skipped.
      - Windows `python -m autodj_analysis --help` and
        `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m pip check`: no broken requirements found.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 9.4_

- [x] 7. Implement waveform overview artifact generation
  - Add helpers to compute stable waveform overview points from decoded audio.
  - Write `<cache-root>/tracks/<track-id>/waveform.json` atomically.
  - Include analyzer provenance, source content hash, duration, sample rate,
    summary peak/RMS values, and generation parameters.
  - Extend cache freshness checks so stale or missing waveform artifacts trigger
    analysis work.
  - Add tests for waveform shape, atomic write behavior, freshness, and force
    rewrite behavior.
  - Implementation notes:
    - Added `autodj_analysis.waveform` with deterministic peak/RMS overview
      generation from `DecodedAudio`, bounded by `targetPointCount` and using
      documented `peak-rms` parameters.
    - Added `build_waveform_artifact()` with track ID, analyzer provenance,
      source content hash, duration, analysis sample rate, parameters, summary
      peak/RMS values, and signal-derived points.
    - Added `write_waveform_artifact()` and `waveform_path()` so
      `<cache-root>/tracks/<track-id>/waveform.json` is written via the existing
      same-directory atomic JSON write path.
    - Added generic JSON artifact loading plus `load_waveform_artifact()` and
      `check_analysis_artifact_freshness()` so a fresh analyzed-track artifact
      plus stale or missing waveform artifact is treated as analysis work rather
      than a skip. Full `analyze-batch` signal composition remains in task 11.
    - Added tests for waveform shape, stable point generation, signal-derived
      energy differences, atomic waveform writes, invalid input errors, missing
      and stale waveform freshness, and force rewrite behavior.
    - Verification commands:
      - `.\.venv\Scripts\python -m pytest .\analysis\worker-python`: 105
        passed, 16 skipped.
      - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`:
        120 passed, 1 skipped.
      - Windows `python -m autodj_analysis --help` and
        `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m pip check`: no broken requirements found.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 9.2, 9.3_

- [x] 8. Implement energy and onset feature extraction
  - Compute signal-derived global energy.
  - Populate `energy.curve` with normalized RMS or comparable frame energy.
  - Populate `energy.bassEnergyCurve` with a simple low-frequency energy
    estimate.
  - Populate `energy.onsetDensityCurve` from onset strength or onset density.
  - Add warnings for coarse or low-confidence energy/onset estimates.
  - Add tests using generated energy-ramp fixtures.
  - Implementation notes:
    - Added `autodj_analysis.features` with `compute_energy_features()` and
      `build_energy_analysis()` for the `AnalyzedTrack.energy` shape.
    - Energy parameters are deterministic and recorded on the internal result:
      frame length `2048`, hop length `512`, max curve points `512`,
      low-pass bass cutoff `180 Hz`, and onset density window `0.5 seconds`.
    - `globalEnergy` is signal-derived from frame RMS. `energy.curve` is
      normalized frame RMS. `bassEnergyCurve` uses a SciPy 4th-order low-pass
      estimate when available. `onsetDensityCurve` uses librosa onset strength
      with a short moving average.
    - Feature values are clamped to `0.0..1.0` where practical. The extractor
      emits warnings for near-silence, very short audio, downsampled/coarse
      curves, weak onset evidence, and unavailable optional bass/onset
      dependencies.
    - `build_analyzed_track_artifact()` now accepts optional `EnergyFeatures`
      and appends feature warnings into `quality.warnings`; default ffprobe-only
      batch behavior remains unchanged until task 11 wires real signal analysis
      into `analyze-batch`.
    - Portability notes: frame RMS, low-pass bass RMS, and moving-average onset
      density are straightforward to port to native C++/mobile; librosa onset
      strength is a Python POC baseline whose behavior should be compared before
      selecting the final native implementation.
    - Added tests for dependency failures, artifact energy population, generated
      energy-ramp curves, generated click-track onset response, and silence
      low-confidence warnings.
    - Verification commands:
      - `.\.venv\Scripts\python -m pytest .\analysis\worker-python`: 109
        passed, 19 skipped.
      - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`:
        127 passed, 1 skipped.
      - Windows `python -m autodj_analysis --help` and
        `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m pip check`: no broken requirements found.
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 9. Implement baseline BPM, normalization, and beat grid
  - Compare selected candidate backends for BPM and beat timing where practical.
  - Use the best selected library stack to estimate BPM and beat times.
  - Populate `tempo.bpm`, `tempo.normalizedBpm`, `tempo.confidence`, and
    candidates where useful.
  - Populate `beatGrid.beats` with stable indexes, times, and confidence.
  - Leave downbeats empty or low-confidence unless evidence is defensible.
  - Add tests for generated 140 BPM and 70 BPM fixtures.
  - Add tests for weak/silent audio fallback behavior.
  - Document backend choice, parameters, and future native portability notes.
  - Implementation notes:
    - Added `autodj_analysis.tempo` with `compute_tempo_features()`,
      `normalize_dubstep_bpm()`, `build_tempo_analysis()`, and
      `build_beat_grid()`.
    - Compared three practical POC candidates from the decoded signal:
      sample transient interval timing, `librosa.beat.beat_track`, and
      librosa onset-interval timing. The highest-confidence candidate drives
      the emitted BPM and beat grid, while all candidates are recorded in
      `tempo.candidates`.
    - Dubstep normalization follows the spec bands: 65-95 BPM normalizes by
      doubling for halftime, 130-190 BPM remains straight, 95-130 BPM remains
      straight with reduced confidence, and out-of-band values choose a related
      half/double value with low confidence.
    - Beat markers include stable indexes, seconds, and confidence. Downbeats
      are intentionally left empty with a warning because no phrase/downbeat
      evidence is defensible yet.
    - `build_analyzed_track_artifact()` now accepts optional `TempoFeatures`
      and appends tempo warnings into `quality.warnings`; default ffprobe-only
      batch behavior remains unchanged until task 11 wires real signal analysis
      into `analyze-batch`.
    - Backend parameters: hop length `512`, preferred start BPM `140`, plausible
      candidate range `50..220 BPM`, fallback dubstep BPM `140`.
    - Portability notes: sample transient interval timing, beat grid synthesis,
      and dubstep BPM normalization are straightforward to port to native
      C++/mobile. `librosa.beat_track` and librosa onset strength are retained
      as Python POC/reference backends and should be compared before selecting
      a native implementation.
    - Added tests for normalization behavior, dependency failures, artifact
      tempo/beat-grid population, generated 140 BPM click fixtures, generated
      70 BPM halftime normalization, and silence low-confidence fallback.
    - Verification commands:
      - `.\.venv\Scripts\python -m pytest .\analysis\worker-python`: 114
        passed, 22 skipped.
      - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`:
        135 passed, 1 skipped.
      - Windows `python -m autodj_analysis --help` and
        `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m pip check`: no broken requirements found.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 12.1, 12.2, 12.3, 12.5_

- [x] 10. Implement rough sections and cue candidates
  - Compare heuristic output against selected structure/segmentation libraries
    where practical.
  - Use energy, onset, and beat-grid features to find conservative rough
    section candidates.
  - Generate cue candidates only where the signal evidence is clear.
  - Snap cue times to nearby beat markers when beat-grid confidence is adequate.
  - Keep ambiguous tracks empty or low-confidence with clear warnings.
  - Add tests using synthetic energy-ramp fixtures and weak/silent fixtures.
  - Document backend choice, parameters, and future native portability notes.
  - Implementation notes:
    - Added `autodj_analysis.structure` with `compute_structure_features()`,
      `build_sections()`, and `build_cue_points()` for the `AnalyzedTrack`
      section and cue shapes.
    - The selected baseline is a conservative heuristic backend,
      `heuristic-energy-onset-v1`, using normalized energy, bass energy, onset
      density, and optional beat-grid confidence. MSAF remains deferred from
      task 3 because it was not compatible with the verified SciPy stack, and
      Essentia/librosa recurrence/Vamp-style segmenters remain comparison
      candidates for later improvement rather than blockers for this baseline.
    - The heuristic detects sustained high-energy plateaus as rough `drop`
      sections, rising energy before a drop as `build`, obvious opening low
      energy as `intro`, and obvious ending low energy as `outro`.
    - Cue candidates are emitted only for defensible rough evidence:
      `mix_in`, `build_start`, `drop`, and `mix_out`. Cue times snap to nearby
      beat markers only when beat-grid confidence is at least `0.65` and a beat
      is within `0.20 seconds`.
    - Weak or ambiguous evidence returns empty sections and cue points with
      explicit warnings. Heuristic section confidence is capped below
      production-grade levels, and every result warns that rough section/cue
      analysis is heuristic.
    - `build_analyzed_track_artifact()` now accepts optional
      `StructureFeatures` and appends structure warnings into
      `quality.warnings`; default ffprobe-only batch behavior remains unchanged
      until task 11 wires real signal analysis into `analyze-batch`.
    - Backend parameters: default high-energy threshold `0.65`, low-energy
      threshold `0.35`, minimum section duration `0.75 seconds`, cue snap window
      `0.20 seconds`, minimum dynamic range `0.25`, and minimum peak energy
      `0.20`.
    - Portability notes: this baseline is straightforward to port to native
      C++/mobile because it operates on existing time/value curves and beat
      markers. Future native work can replace or augment it with selected
      structure segmentation backends once those candidates prove better than
      the heuristic on fixtures and real songs.
    - Added tests for clear energy-ramp section/cue detection, beat-snapped
      cues, low-confidence no-snap behavior, weak evidence fallback, artifact
      section/cue population, generated energy-ramp fixtures, and generated
      silence fallback.
    - Verification commands:
      - `.\.venv\Scripts\python -m pytest .\analysis\worker-python`: 121
        passed, 24 skipped.
      - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`:
        144 passed, 1 skipped.
      - Windows `python -m autodj_analysis --help` and
        `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m autodj_analysis analyze-batch --help`: passed.
      - WSL `python -m pip check`: no broken requirements found.
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 12.1, 12.2, 12.3, 12.5_

- [x] 11. Integrate real analysis into `analyze-batch`
  - Compose ffprobe metadata, decoded audio, waveform, energy, tempo, beat-grid,
    sections, and cue candidates into generated artifacts.
  - Update analyzer producer/version/parameters hash so ffprobe-only artifacts
    are rewritten.
  - Preserve manifest identity fields, source content hash, and structured
    per-track failure behavior.
  - Ensure one failed track does not block analysis or skipping for other
    tracks.
  - Ensure `--json` summaries remain parseable and include useful failure
    details.
  - Add batch and CLI tests for success, skip-current, stale waveform rewrite,
    force rewrite, and partial analysis failure.
  - Implementation notes:
    - Updated `analyze-batch` to decode each stale/forced track, generate
      waveform JSON, compute energy/tempo/beat-grid/rough structure features,
      and compose them with FFprobe metadata in `analyzed-track.json`.
    - Switched batch freshness identity to `autodj_analysis.signal` with a new
      signal parameters hash, and freshness now requires both analyzed-track and
      waveform artifacts to be current.
    - Preserved per-track structured failures for probe, decode, waveform,
      feature, tempo, structure, and cache errors so later tracks still run.
    - Added JSON summary `waveformPath` output and CLI/batch test injection for
      deterministic signal-analysis tests.
    - Added generated-audio integration coverage for real batch signal analysis
      plus stale waveform, force rewrite, skip-current, CLI JSON, and partial
      failure cases.
  - Verification commands:
    - `.\.venv\Scripts\python -m pytest .\analysis\worker-python`: 123
      passed, 25 skipped.
    - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`:
      147 passed, 1 skipped.
    - Windows `python -m autodj_analysis analyze-batch --help`: passed.
    - WSL `python -m autodj_analysis analyze-batch --help`: passed.
    - WSL `python -m pip check`: no broken requirements found.
  - _Requirements: 4.4, 5.4, 6.1, 7.3, 8.5, 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 12. Add manual known-song checkpoint documentation
  - Update README or spec docs with WSL setup commands and analysis test
    commands.
  - Document how to run `analyze-batch` on one known local song from WSL.
  - Document what the user should inspect: BPM, normalized BPM, energy shape,
    rough sections, and cue candidates.
  - Document selected backend combinations and why they were selected over
    alternatives.
  - Document future native/mobile porting implications for waveform, energy,
    BPM/beat-grid, sections, and cues.
  - Preserve warnings not to commit local media or generated cache artifacts.
  - Update README status so spec 003 is complete and spec 004 is current or
    implemented as appropriate.
  - Implementation notes:
    - Updated `README.md` so Spec 003 is listed as complete and Spec 004 is
      listed as the current real-analysis baseline, including waveform, energy,
      tempo, beat-grid, rough section, and cue-candidate outputs.
    - Added WSL Python 3.11 setup commands, analysis dependency install
      commands, generated-fixture verification commands, and WSL `pip check`
      guidance to `README.md`.
    - Added
      `.codex/specs/004-real-audio-analysis-baseline/manual-known-song-checkpoint.md`
      with a one-song WSL `analyze-batch` workflow, manifest generation snippet,
      artifact inspection snippet, BPM/energy/section/cue checklist, backend
      combination notes, and future native/mobile portability notes.
    - Updated the spec summary to point to the manual checkpoint document.
    - Preserved warnings that local songs, generated manifests/summaries, and
      `.autodj-cache/` outputs must not be committed.
  - Verification commands:
    - `.\.venv\Scripts\python -m pytest .\analysis\worker-python -q`: 123
      passed, 25 skipped.
    - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python -m analysis -q"`:
      21 passed, 127 deselected.
    - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pip check"`:
      no broken requirements found.
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 12.1, 12.2, 12.4, 12.5_

- [x] 13. Run full verification and update task status
  - Run native Windows Python worker tests.
  - Run native Windows CLI help commands.
  - Run WSL dependency smoke tests and WSL analysis pytest suite.
  - Run `cmake --preset debug`.
  - Run `cmake --build --preset debug`.
  - Run `ctest --preset debug`.
  - Update this file's checkboxes only for verified completed tasks.
  - Document any blockers with command output summaries and affected
    requirements.
  - Implementation notes:
    - Full verification initially found one CTest boundary failure:
      `autodj_repository_boundaries` scanned into `.venv-analysis/` and flagged
      sample WAV files installed inside third-party Python packages.
    - Updated `core/repository/tests/verify_repository_boundaries.cmake` to
      skip the documented `.venv-analysis/` virtual environment, matching the
      existing `.venv/` skip behavior and `.gitignore` policy.
    - Reran the CMake/CTest boundary path after the fix; all C++ tests passed.
  - Verification commands:
    - `.\.venv\Scripts\python -m pytest .\analysis\worker-python -q`: 123
      passed, 25 skipped.
    - `.\.venv\Scripts\python -m autodj_analysis --help`: passed.
    - `.\.venv\Scripts\python -m autodj_analysis analyze-batch --help`:
      passed.
    - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python/tests/test_dependency_smoke.py -q"`:
      9 passed.
    - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python -q"`:
      147 passed, 1 skipped.
    - `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pip check"`:
      no broken requirements found.
    - `cmake --preset debug`: passed.
    - `cmake --build --preset debug`: passed.
    - `ctest --preset debug`: 7/7 tests passed after the boundary skip fix.
    - `.\.venv\Scripts\python -m pytest .\analysis\worker-python\tests\test_boundaries.py -q`:
      18 passed.
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8_
