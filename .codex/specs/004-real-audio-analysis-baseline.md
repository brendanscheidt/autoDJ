# Spec 004: Real Audio Analysis Baseline

> Kiro-style execution package:
> `.codex/specs/004-real-audio-analysis-baseline/`
>
> Use that folder's `kiro.json`, `requirements.md`, `design.md`, and
> `tasks.md` when executing implementation tasks. This file remains the source
> summary.

## Purpose

Continue Phase 3 by turning the current ffprobe-only analysis artifacts into
the first musically useful `AnalyzedTrack` artifacts. This spec establishes a
Linux/WSL Python 3.11 reference analyzer for MIR libraries, adds library-based
audio loading and signal analysis, and writes honest baseline waveform, energy,
tempo, beat-grid, section, and cue data into the metadata cache.

This is not the final mobile analysis runtime. Python is temporary for the
eventual full offline mobile app, but it is necessary for the POC and can remain
useful for an all-in-one Windows desktop product while analysis quality is being
proven. The POC should rely heavily on the best available Python/MIR libraries
to find the strongest algorithms and combinations. Later work will port the
winning behavior to C++ or another mobile-safe native implementation.

## Steering References

Read these before implementing:

- `.codex/steering/00-product-vision.md`
- `.codex/steering/01-system-architecture.md`
- `.codex/steering/02-core-contracts.md`
- `.codex/steering/03-tech-stack.md`
- `.codex/steering/04-project-structure.md`
- `.codex/steering/05-dubstep-dj-strategy.md`
- `.codex/steering/07-analysis-pipeline.md`
- `.codex/steering/08-engineering-practices.md`
- `.codex/steering/09-roadmap.md`

## Goals

- Establish a repeatable WSL/Linux Python 3.11 analysis environment.
- Add optional analysis dependencies for NumPy, SciPy, librosa, SoundFile,
  Essentia, and additional high-value MIR candidates where supported.
- Survey and smoke-test candidate POC libraries instead of prematurely limiting
  the analyzer to one stack.
- Compare library outputs on generated fixtures and document which backends are
  best for each feature family.
- Record portability notes for future native/mobile C++ implementation.
- Keep dependency availability behind explicit smoke tests and clear errors.
- Add generated synthetic audio fixtures for deterministic tests.
- Add a library-based audio loading boundary that can evolve without rewriting
  batch orchestration.
- Write waveform overview data to
  `<cache-root>/tracks/<track-id>/waveform.json`.
- Populate real RMS, peak, global energy, energy curve, bass-energy curve, and
  onset-density data.
- Populate baseline BPM, normalized BPM, beat markers, and confidence.
- Normalize 70/140 BPM relationships for dubstep-style reasoning.
- Add rough low-confidence section and cue candidates from energy/onset/beat
  data.
- Preserve manifest-driven batch behavior, cache invalidation, and structured
  per-track errors from spec 003.

## Non-goals

- No desktop UI integration.
- No playback command scheduler.
- No DJ strategy generation or transition scoring.
- No stem separation or Demucs integration.
- No vocal-region analysis beyond safe placeholders unless it falls out of
  existing low-cost descriptors.
- No production-grade key detection requirement in this spec.
- No SQLite.
- No mobile UI or mobile packaging.
- No real music files committed to git.
- No requirement that native Windows support every advanced MIR dependency.
- No production mobile native analyzer implementation in this spec.
- No assumption that Python/WSL will ship inside the eventual mobile app.

## Runtime Direction

Use two explicit development runtimes:

- **Windows native:** C++/JUCE/CMake verification and current basic Python tests.
- **WSL/Linux:** Python 3.11 analysis worker with MIR dependencies.

The Python worker remains a process boundary and writes portable JSON artifacts.
Do not let WSL-specific paths or assumptions leak into C++ domain, playback, DJ,
or desktop modules.

## Required Deliverables

### WSL And Python 3.11 Checkpoint

Document and verify a WSL Ubuntu analysis environment with Python 3.11.

The spec implementation should produce commands similar to:

```powershell
wsl --status
wsl -d Ubuntu -- bash -lc "python3.11 --version"
```

Inside WSL, create an isolated analysis virtual environment and install the
worker in editable mode with analysis extras.

### Analysis Dependencies

Add optional dependency groups to `analysis/worker-python/pyproject.toml`.

Expected dependency families:

- `numpy`
- `scipy`
- `librosa`
- `soundfile`
- `audioread` if needed by the loader stack
- `essentia` for WSL/Linux where installable
- `madmom` and/or `BeatNet` for beat/downbeat comparison if installable
- `aubio` or a maintained aubio fork for onset/tempo/pitch comparison, subject
  to license review
- `msaf` for music structure segmentation experiments
- `vamp` and QM Vamp plugins for tempo/beat/key/structure reference outputs
- `audioflux` for feature extraction comparison
- `pyAudioAnalysis` for feature/segmentation baseline comparison
- `torchaudio` when ML-oriented feature extraction becomes useful
- `basic-pitch` for pitch/transcription experiments if helpful
- `mir_eval` for comparing candidate outputs against generated or curated
  references

Do not make native Windows development fail only because Essentia is unavailable
there. Essentia should be required for the WSL analysis checkpoint, while the
worker should produce an actionable error if an advanced backend is requested
without its dependency.

The POC should use as many libraries as are justified by measured analysis
quality. The long-term production decision can be to port behavior, license a
native library, or discard a weak backend after comparison.

### Library-Based Audio Loading

Add a small audio loading boundary, for example:

```text
analysis/worker-python/src/autodj_analysis/audio_io.py
```

It should load local WAV/MP3 files into mono floating-point PCM for analysis,
report sample rate and duration, and convert dependency/decode failures into
structured per-track errors.

The existing ffprobe adapter may continue to provide container metadata, but
signal analysis should use the library decoding boundary.

### Waveform Artifact

Write:

```text
<cache-root>/tracks/<track-id>/waveform.json
```

The artifact should include:

- schema/version or artifact version
- track ID
- analyzer provenance
- source content hash
- sample rate or analysis sample rate
- duration seconds
- overview points suitable for future UI rendering
- peak/RMS summary values
- parameters used to generate the overview

### Energy And Onset Data

Populate `AnalyzedTrack.energy` with real baseline values:

- `globalEnergy`
- `curve`
- `bassEnergyCurve`
- `onsetDensityCurve`

These may be coarse and low-confidence but must be signal-derived.

### Tempo And Beat Grid

Populate `AnalyzedTrack.tempo` and `AnalyzedTrack.beatGrid` with baseline data:

- raw BPM
- normalized BPM for dubstep halftime/doubletime relationships
- tempo confidence
- beat markers in seconds
- optional downbeats only when defensible
- beat-grid confidence

Generated fixtures should prove 140 BPM and 70 BPM cases behave consistently.

### Rough Sections And Cue Candidates

Add conservative section and cue candidates based on energy, onset density, and
beat positions.

Expected first-pass outputs:

- one or more rough `unknown`, `intro`, `build`, `drop`, or `outro` sections
  for synthetic fixtures where the signal makes this obvious
- `build_start`, `drop`, `mix_in`, or `mix_out` cue candidates only when the
  heuristic has a clear reason
- confidence values low enough that later DJ strategy code will choose safe
  transitions unless evidence is strong

### Cache Invalidation

Update analyzer provenance and parameters hash so existing spec 003 artifacts
are rewritten when real signal analysis is enabled.

Cache freshness should account for both:

- `analyzed-track.json`
- `waveform.json`

### Documentation And Manual Checkpoints

Update README/status docs for spec 004 and add manual test guidance:

- WSL dependency smoke test
- generated fixture test command
- one known local song manual check where the user reports whether BPM, energy,
  and cue guesses are plausible
- library/backend comparison notes for BPM, beat-grid, key, sections, and cues
- future native/mobile portability notes for each selected backend

The executable manual checkpoint is maintained in
`.codex/specs/004-real-audio-analysis-baseline/manual-known-song-checkpoint.md`.

## Suggested Verification Commands

Windows regression:

```powershell
.\.venv\Scripts\python -m pytest .\analysis\worker-python
.\.venv\Scripts\python -m autodj_analysis --help
.\.venv\Scripts\python -m autodj_analysis analyze-batch --help
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
```

WSL analysis verification:

```powershell
wsl --status
wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && python3.11 --version"
wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"
```

The exact WSL path may differ if the repository is cloned inside the WSL
filesystem instead of accessed through `/mnt/c`.

## Acceptance Criteria

- WSL/Linux Python 3.11 analysis environment is documented and verified.
- Analysis dependency import smoke tests pass in WSL.
- Candidate MIR libraries are surveyed with installability, license/platform,
  feature coverage, and POC value notes.
- `analyze-batch` still reads repository manifests and writes cache artifacts.
- Generated 140 BPM fixture produces plausible BPM and beat markers.
- Generated 70 BPM fixture normalizes consistently for dubstep reasoning.
- Waveform and energy artifacts are signal-derived and cacheable.
- Synthetic energy-ramp fixture produces at least one defensible section or cue
  candidate.
- Weak or failed analysis produces warnings and safe placeholders, not fake
  high confidence.
- Selected POC backends and parameters are documented well enough to guide a
  future C++/mobile-native port or licensing decision.
- Existing Python and C++ regression tests still pass.
- No real music files, cache artifacts, or venvs are committed.

## Follow-up Specs

Likely next specs:

- `005-playback-engine-command-scheduler`
- `006-dubstep-dj-first-transitions`
- `007-key-and-section-analysis-improvements`
