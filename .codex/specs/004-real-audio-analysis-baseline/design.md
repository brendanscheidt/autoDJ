# Design Document

## Overview

Spec 003 made analysis batch-aware and cache-correct but intentionally left
musical fields as placeholders. This spec adds the first real signal analysis:
library-based decode, waveform overview, energy/onset curves, BPM, beat grid,
rough sections, and cue candidates.

Python/WSL is the POC/reference analyzer. It should use the strongest available
MIR libraries aggressively to find the best analysis quality. It is not the
final offline mobile runtime; successful outputs must be documented well enough
to port, license, or replace later in a native/mobile analyzer.

## Steering Context

Implementation agents must read:

- `.codex/steering/00-product-vision.md`
- `.codex/steering/01-system-architecture.md`
- `.codex/steering/02-core-contracts.md`
- `.codex/steering/03-tech-stack.md`
- `.codex/steering/04-project-structure.md`
- `.codex/steering/05-dubstep-dj-strategy.md`
- `.codex/steering/07-analysis-pipeline.md`
- `.codex/steering/08-engineering-practices.md`
- `.codex/steering/09-roadmap.md`

## Runtime Model

Use two explicit development environments:

```text
Windows native
  -> CMake / JUCE / CTest
  -> base Python tests that do not require Linux-only MIR libraries

WSL / Linux
  -> Python 3.11 analysis virtualenv
  -> NumPy / SciPy / librosa / SoundFile / Essentia
  -> candidate MIR comparison backends
  -> real analysis tests
```

The process boundary remains:

```text
RepositoryManifest
  -> autodj-analysis analyze-batch
  -> analyzed-track.json + waveform.json
  -> future DJ / playback / desktop consumers
```

Native C++ modules must not import, link, or assume WSL. They consume JSON
artifacts later.

## Dependency Strategy

Update `analysis/worker-python/pyproject.toml` with optional extras instead of
making the base package heavy. The POC can use many libraries, but dependency
groups should make intent clear: base worker, core analysis, and exploratory
candidate backends.

Suggested shape:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0"
]
analysis = [
    "numpy>=1.26",
    "scipy>=1.11",
    "librosa>=0.10",
    "soundfile>=0.12",
    "audioread>=3.0"
]
analysis-wsl = [
    "numpy>=1.26",
    "scipy>=1.11",
    "librosa>=0.10",
    "soundfile>=0.12",
    "audioread>=3.0",
    "essentia>=2.1b6"
]
analysis-candidates = [
    # exact package names should be verified during implementation
    "madmom",
    "BeatNet",
    "msaf",
    "audioflux",
    "pyAudioAnalysis",
    "mir_eval",
    "torchaudio",
    "basic-pitch"
]
```

Exact lower bounds can be adjusted during implementation if installation
verification proves a better compatible set. Avoid strict pins unless needed;
the first goal is to find a compatible Python 3.11 stack.

Dependency smoke tests should explicitly import:

- `numpy`
- `scipy`
- `librosa`
- `soundfile`
- `essentia` in WSL analysis verification
- candidate backends that install cleanly enough to evaluate

If Essentia is unavailable on native Windows, that must not break base Windows
tests. Use pytest markers or dependency-gated tests.

## Candidate Library Survey

Before locking the implementation backend, create a small candidate matrix with:

- package/tool name,
- feature role,
- install command,
- license,
- supported runtime/platform notes,
- source URL,
- POC priority,
- mobile/native portability risk.

Initial candidates from current research:

- librosa: core Python MIR building blocks for audio loading, onset, tempo,
  chroma, recurrence, segmentation, and features. ISC license.
- Essentia: C++/Python MIR library with music extractor descriptors, BPM, beat
  positions, key estimation, rhythm, tonal, spectral, and loudness descriptors.
  AGPL/commercial licensing and Windows Python limitations require care.
- madmom: MIR library focused on onset, beat, downbeat, meter, and tempo
  tracking. Useful for comparison if Python/dependency compatibility works.
- BeatNet: AI-based beat, downbeat, tempo, and meter tracking. Useful for
  comparing downbeat quality.
- aubio or maintained aubio forks: onset, tempo, beat, pitch, MFCC, and command
  line tools. Licensing can affect redistribution.
- MSAF: music structure analysis framework for section boundary experiments.
- Vamp/QM plugins: tempo/beat tracker, bar/beat tracker, key detector, tonal
  change, segmenter, chromagram, MFCC, and related reference outputs.
- audioFlux: MIT-licensed C/Python audio and music feature extraction library;
  useful for feature extraction comparison and possible portability clues.
- pyAudioAnalysis: Apache-licensed feature extraction, classification, and
  segmentation baseline.
- torchaudio: PyTorch audio/signal processing and feature extraction, useful if
  ML models become part of the POC.
- Basic Pitch: Apache-licensed audio-to-MIDI/pitch transcription from Spotify;
  not core BPM analysis, but useful for pitch/melody experiments.
- mir_eval: evaluation metrics for beat, tempo, key, and other MIR outputs.

Do not force every candidate into the shipping implementation. The spec should
fail fast on installability, compare outputs where practical, and document why a
candidate is selected, deferred, or rejected.

## POC To Native Evidence

For every feature family that becomes part of the artifact, record:

- winning backend/library,
- alternative backends tested,
- exact parameters and analysis sample rate,
- generated fixture performance,
- known real-song behavior if manually tested,
- confidence heuristic,
- license and platform concern,
- future native strategy: reimplement, license native library, use mobile ML
  runtime, or defer.

## Proposed Python Modules

Keep modules small and testable:

```text
analysis/worker-python/src/autodj_analysis/
  audio_io.py        # decode/load audio into analysis samples
  features.py        # waveform, RMS, bass energy, onset features
  tempo.py           # BPM, beat grid, dubstep normalization
  structure.py       # rough sections and cue candidates
  waveform.py        # waveform artifact construction/write helpers
  batch.py           # orchestration integration from spec 003
```

Names can vary, but keep boundaries clear:

- `audio_io` owns third-party decode calls.
- `features` owns frame-level signal features.
- `tempo` owns BPM and beat markers.
- `structure` owns rough sections/cues.
- `batch` composes results and handles per-track failures.

## Data Objects

Suggested internal objects:

```python
@dataclass(frozen=True)
class DecodedAudio:
    samples: np.ndarray
    sample_rate: int
    duration_seconds: float
    channels: int | None
    source_path: Path

@dataclass(frozen=True)
class WaveformOverview:
    points: list[dict[str, float]]
    peak: float
    rms: float
    sample_rate: int
    duration_seconds: float

@dataclass(frozen=True)
class EnergyFeatures:
    global_energy: float
    curve: list[dict[str, float]]
    bass_energy_curve: list[dict[str, float]]
    onset_density_curve: list[dict[str, float]]

@dataclass(frozen=True)
class TempoFeatures:
    bpm: float
    normalized_bpm: float
    confidence: float
    beats: list[dict[str, float]]
    downbeats: list[dict[str, float]]
    beat_grid_confidence: float

@dataclass(frozen=True)
class StructureFeatures:
    sections: list[dict[str, object]]
    cue_points: list[dict[str, object]]
    warnings: list[str]
```

Backend result objects may also be useful so the POC can compare multiple
libraries before choosing the artifact output.

## Audio Loading

Use library loading for signal analysis, preferably through librosa/SoundFile.
Do not scatter `librosa.load()` calls through batch code.

Initial behavior:

- Load mono samples.
- Use a deterministic analysis sample rate, for example 22050 Hz, unless tests
  show native sample rate is needed for timing accuracy.
- Preserve ffprobe-derived container metadata from spec 003 under
  `source.providerMetadata.ffprobe`.
- Use decoded sample count for signal-analysis duration.

Expected errors:

- `audio_dependency_missing`
- `audio_decode_error`
- `audio_empty`
- `audio_unsupported_format`

## Waveform Artifact

Use adjacent cache storage:

```text
<cache-root>/tracks/<track-id>/waveform.json
```

Suggested shape:

```json
{
  "schemaVersion": "1.0.0",
  "trackId": "track-a",
  "analyzer": {
    "producer": "autodj_analysis.signal",
    "producerVersion": "0.2.0",
    "createdAtUtc": "2026-05-16T00:00:00Z",
    "sourceContentHash": "sha256:...",
    "parametersHash": "sha256:..."
  },
  "durationSeconds": 180.0,
  "sampleRate": 22050,
  "parameters": {
    "targetPointCount": 1024,
    "mode": "peak-rms"
  },
  "summary": {
    "peak": 0.92,
    "rms": 0.18
  },
  "points": [
    { "timeSeconds": 0.0, "min": -0.3, "max": 0.4, "rms": 0.12 }
  ]
}
```

There is no existing waveform schema in `core/contracts`; keep this artifact
plain and documented for now. A later contract spec can formalize it.

## Energy And Onset

Use librosa/SciPy features for a baseline:

- RMS energy per frame.
- Global energy from mean normalized RMS.
- Bass energy through a simple low-frequency band estimate or filter.
- Onset strength or onset envelope converted to time/value points.

Keep values normalized to `0.0` to `1.0` where practical so future strategy code
can compare tracks without knowing the backend.

## Tempo And Beat Grid

Use library-based baselines and compare them where practical. Candidates include
librosa, Essentia, madmom, BeatNet, aubio, and Vamp/QM plugins. The artifact
writer should select the best available result according to fixture accuracy,
confidence, and backend quality notes rather than blindly trusting the first
library call.

Dubstep normalization:

```text
if 65 <= bpm < 95:
    normalized = bpm * 2
elif 130 <= bpm <= 190:
    normalized = bpm
elif 95 <= bpm < 130:
    normalized = bpm
else:
    choose the closest musically plausible half/double value with low confidence
```

Generated fixture expectations:

- 140 BPM click fixture should be near 140.
- 70 BPM halftime fixture should normalize near 140.

Do not invent downbeats unless the fixture or analysis provides defensible
evidence.

## Rough Structure And Cues

Use conservative heuristics:

- Detect sustained high-energy regions as rough `drop` candidates.
- Detect rising energy before a high-energy region as rough `build` candidates.
- Use early low-energy regions as `intro` only when obvious.
- Use final low-energy regions as `outro` only when obvious.
- Snap cues to nearby beat markers when beat-grid confidence is adequate.

Confidence guidance:

- Generated fixtures with clear structure can be moderate confidence.
- Real songs should generally remain low to medium confidence until validated.
- Ambiguous tracks should emit warnings and fewer labels.

If MSAF, Essentia, librosa recurrence, or Vamp/QM segmenter outputs are
available, compare them against the heuristic output before deciding what to
write into `AnalyzedTrack`.

## Artifact Construction Changes

Update the spec 003 artifact builder:

- Replace placeholder `tempo` with `TempoFeatures`.
- Replace empty `beatGrid.beats` with real beat markers when available.
- Replace empty `sections` with rough sections when available.
- Replace placeholder `energy` with `EnergyFeatures`.
- Replace empty `cuePoints` with rough cues when available.
- Keep `key` as unknown unless a cheap and tested backend output is added.
- Keep `vocals` as unknown/low-confidence placeholder.
- Add `quality.warnings` for each weak or heuristic feature family.

Suggested producer constants:

```python
ANALYZER_PRODUCER = "autodj_analysis.signal"
ANALYZER_VERSION = __version__
DEFAULT_PARAMETERS_HASH = "sha256:signal-v1-librosa-essentia-baseline-v1"
```

Version/hash names can change during implementation, but they must cause spec
003 ffprobe-only artifacts to be rewritten.

## Cache Freshness

Freshness requires:

- `analyzed-track.json` has current analyzer provenance and parameters hash.
- `waveform.json` exists and has current analyzer provenance and parameters
  hash.
- Source content hash matches both artifacts where present.

If one artifact is stale, the batch result should report analysis work rather
than a skip.

## Testing Strategy

Use generated temporary audio only.

Fixture helpers:

- 140 BPM click track.
- 70 BPM halftime click/pulse track.
- Energy-ramp track with low/high regions.
- Silence or near-silence failure/low-confidence fixture.

Test groups:

- Base tests that can run on Windows without analysis extras.
- Analysis tests that require `[analysis]` or `[analysis-wsl]`.
- WSL smoke tests for Essentia availability.
- Candidate backend smoke tests, marked/skipped individually when optional
  backends are not installed.
- Library comparison reports or tests for generated fixtures.

Use pytest markers if useful:

```python
pytestmark = pytest.mark.analysis
```

Keep the existing boundary test but update the approved dependency list for this
spec. It should still reject local media and generated cache artifacts.

## Manual Testing

After automated generated fixtures pass, ask the user to run one known local
song through `analyze-batch` in the WSL analysis environment and report:

- detected BPM
- whether normalized BPM is musically plausible
- whether energy curve roughly follows the song
- whether any drop/build/mix cues are plausible
- any obvious false positives
- which backend combination produced the most believable result if multiple
  backends are compared

Manual feedback should be documented in the task verification note when it
influences implementation decisions.

## Risks

- Essentia installation may fail on WSL depending on Python, distro, or wheel
  availability.
- MP3 decoding may require system packages even when using Python libraries.
- Beat tracking on synthetic fixtures may be easier than real dubstep tracks.
- Rough section detection can produce misleading labels if confidence is too
  high.
- WSL paths can differ from Windows paths; path handling must preserve source
  URI identity and keep analysis path resolution explicit.
- POC libraries may have licenses that are unsuitable for closed-source mobile
  distribution without commercial licensing or reimplementation.
- A high-quality Python result may be hard to reproduce in native C++; the POC
  must capture enough evidence to make that future cost visible.

## Verification

Windows:

```powershell
.\.venv\Scripts\python -m pytest .\analysis\worker-python
.\.venv\Scripts\python -m autodj_analysis --help
.\.venv\Scripts\python -m autodj_analysis analyze-batch --help
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
```

WSL:

```powershell
wsl --status
wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && python3.11 --version"
wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"
```
