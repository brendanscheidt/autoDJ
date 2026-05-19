# Analysis Pipeline

## Purpose

The analysis pipeline turns local audio files into `AnalyzedTrack` artifacts that
DJ strategies can use. It runs offline and can be slow. Playback should never
depend on live analysis.

During the POC, the Python analysis worker may rely heavily on best-in-class MIR
libraries to find the strongest analysis approach. Long term, the mobile product
must be able to analyze local phone audio offline, so successful POC algorithms
need portability notes, fixture expectations, and a path toward native C++ or
mobile-safe library implementation.

Spec 005 selected the current analysis direction:

- BPM/beatgrid: `current-autodj-signal`.
- Semantic sections: `dubstep-phrase-hybrid`.
- Section fallback: `current-autodj-signal` rough sections only when the
  selected semantic backend cannot run or emits no usable sections.

`dubstep-phrase-hybrid` uses the selected beatgrid, energy/bass/onset curves,
All-In-One structural boundaries, SongFormer structural boundaries, and
dubstep phrase heuristics. It is the default `analyze-batch` semantic backend
for the POC. Rekordbox XML remains evaluation truth only and must not be passed
into normal artifact generation.

## MVP Pipeline

```text
RepositoryTrack
  -> Decode/Probe
  -> Loudness/Waveform
  -> BPM/Beat Grid
  -> Key
  -> Section Detection
  -> Energy Curves
  -> Vocal Detection
  -> Optional Stem Separation
  -> Cue Candidate Generation
  -> AnalyzedTrack JSON
  -> Metadata Cache
```

## Stage Details

### Decode / Probe

Inputs:

- Local WAV/MP3 file path.

Outputs:

- Duration.
- Sample rate.
- Channel count.
- Codec/container metadata.
- Optional normalized analysis WAV.

Implementation:

- Use `ffprobe` for metadata.
- Use `ffmpeg` to produce normalized PCM/WAV when libraries need it.

### Loudness / Waveform

Outputs:

- Integrated loudness if available.
- Peak level.
- Waveform overview points for UI.
- RMS/energy windows.

Waveform previews should be cached separately from the full audio file.

### BPM / Beat Grid

Outputs:

- Raw BPM.
- Normalized BPM.
- Beat positions.
- Downbeat positions if available.
- Confidence.

Recommended sources:

- Selected implementation: `current-autodj-signal`, the project-owned
  electronic-music timing stack using normalized BPM handling and deterministic
  beat-grid synthesis.
- Comparison-only timing backends: `essentia-rhythm`, `beat-this`, and
  `all-in-one`. Do not auto-fallback to these for production artifacts unless a
  later benchmark and manual verdict replaces the selected backend.
- Future benchmark metrics must include beat coverage and reference-beat recall
  in addition to nearest candidate-beat median/p95 error, because sparse beat
  outputs can otherwise look deceptively strong.
- mir_eval or equivalent metrics remain useful for generated fixtures and
  curated references.

The beat grid is one of the most important artifacts. Loop tightening, phrase
alignment, and drop swaps should require high confidence.

### Key

Outputs:

- Tonic.
- Mode.
- Camelot notation if mapped.
- Confidence.
- Candidate keys.

Key confidence should influence transition type. Avoid long melodic/vocal blends
when key confidence is low.

### Section Detection

Outputs:

- Intro/verse/build/drop/break/outro regions.
- Confidence per section.
- Ordered drop instances should use repeated `drop` sections with stable IDs or
  indices, not labels such as `drop1` or `drop2`.

Selected POC approach:

- Use `dubstep-phrase-hybrid` as the default section backend.
- Use All-In-One and SongFormer as boundary evidence providers, not as final
  DJ-label authorities.
- Promote pop-form labels such as chorus/bridge/instrumental only with
  supporting energy, bass, onset, and phrase-position evidence.
- Infer dubstep builds and drop ends from beat/bar phrase lengths where
  evidence supports it.
- Treat short low-energy gaps inside drops as possible turnarounds rather than
  automatic second drops.
- Normalize breakdown/break-verse provider labels to `break`.
- Snap boundaries to beat/bar markers when confidence is adequate.
- Preserve honest warnings and confidence; do not emit fake high-confidence
  `drop` labels from weak evidence.

Fallback:

- If `dubstep-phrase-hybrid` cannot run or emits no usable sections,
  `analyze-batch` falls back to `current-autodj-signal` rough sections and
  records the reason in `quality.warnings`.
- `--section-backend current-autodj-signal` is acceptable for quick smoke tests
  without heavy semantic ML dependencies, but it is not the selected section
  path.

Deferred comparison systems:

- MSAF, Essentia/librosa recurrence helpers, Vamp/QM, automatic cue switch
  research, cue object detection, Cyanite segments, and other hosted/provider
  systems are future-spec material unless a new benchmark/manual verdict
  reopens section selection.

### Energy Curves

Outputs:

- Overall energy curve.
- Bass energy curve.
- Onset density curve.
- Section-level means and peaks.

Energy curves drive set energy arc and transition template selection.

### Vocal Detection

Outputs:

- Vocal presence regions.
- Confidence.

MVP options:

- Use stem separation when available.
- Estimate vocal presence from separated vocal stem energy.
- Use spectral/ML heuristics later.

The DJ strategy needs vocal clash risk more than perfect lyric detection.

### Stem Separation

Outputs:

- Optional paths for vocals, drums, bass, other, and instrumental stems.
- Stem quality estimates when available.

MVP:

- Use Demucs offline.
- Start with `--two-stems=vocals` for acapella/instrumental tests.
- Cache stem files by source hash and model settings.

Do not require stems for every transition. Stem-based transitions should be
optional and gated by quality.

### Cue Candidate Generation

Outputs:

- Mix-in points.
- Mix-out points.
- Drop starts.
- Build starts.
- Loop candidates.
- Vocal starts/ends.

Cue candidates should reference both seconds and beat indexes when possible.

## Cache Key

An analysis artifact is valid only for the same:

- Track ID.
- Source content hash.
- Analyzer version.
- Analyzer parameters.
- Stem model/version when stems are included.
- Schema version.

If any of these change, reanalysis is required.

## Artifact Storage

Initial layout:

```text
.autodj-cache/
  tracks/
    <track-id>/
      analyzed-track.json
      waveform.json
      section-backend-work/
        analysis.wav
      stems/
        vocals.wav
        instrumental.wav
```

Do not commit `.autodj-cache/`.

Fixture artifacts can live under `fixtures/metadata/` and `fixtures/plans/`.

Benchmark/debug runs may also create candidate folders containing
`debug-waveform.json`, `section-evaluation.json`, and copied `source-audio.mp3`.
Those are inspection artifacts, not required normal cache outputs.

## Confidence Model

Every uncertain output should have confidence.

Recommended usage:

- `>= 0.85`: safe for complex transitions.
- `0.65 - 0.85`: use simple phrase-aligned transitions.
- `0.45 - 0.65`: hard cuts or exclude from set.
- `< 0.45`: reject from AutoDJ planning unless user overrides.

These thresholds are starting points, not product truth.

## Performance

Analysis can be parallelized by track, but individual CPU/GPU-heavy steps should
avoid oversubscribing the machine.

Guidance:

- Use a bounded worker pool.
- Run stem separation with explicit concurrency limits.
- Make jobs resumable.
- Write intermediate artifacts atomically.
- Surface progress in the UI.

## Determinism

Analysis should be reproducible when possible.

Store:

- Tool versions.
- Model names.
- Parameters.
- Source hash.
- Random seed if any.
- Backend/library identity for each major feature family.
- Portability notes for algorithms expected to move into a native analyzer.

If a model is nondeterministic, document that in the artifact provenance.

## POC To Native Port Path

For each feature family, the Python POC should produce enough evidence for a
future C++/mobile implementation:

- decoded signal assumptions,
- frame size and hop size,
- filters/transforms used,
- library function or model used,
- confidence calculation,
- generated fixture expected output,
- known false positives/false negatives,
- whether the behavior is easy, moderate, hard, or impractical to port.

Do not copy incompatible open-source code into a closed-source native analyzer.
Use licenses correctly, buy commercial licenses where appropriate, or re-create
behavior from documented algorithms and independently written implementation.

## Debuggability

The UI should be able to show:

- Waveform.
- Beat/downbeat grid.
- Section labels.
- Energy curves.
- Vocal regions.
- Cue candidates.
- Stems present/missing.
- Confidence values.

If a generated transition sounds bad, the first debugging question should be:
"Was the analysis wrong, or was the DJ decision wrong?"
