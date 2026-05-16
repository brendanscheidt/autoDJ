# Analysis Pipeline

## Purpose

The analysis pipeline turns local audio files into `AnalyzedTrack` artifacts that
DJ strategies can use. It runs offline and can be slow. Playback should never
depend on live analysis.

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

- Essentia baseline.
- librosa experiments.
- Optional madmom downbeat model.

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

- Intro/build/drop/breakdown/outro regions.
- Confidence per section.

MVP approach:

- Use energy curve changes, onset density, low-frequency energy, and phrase
  boundaries.
- Find high-energy plateaus as drop candidates.
- Find rising energy before drops as build candidates.
- Find low-energy openings/closings as intro/outro candidates.
- Snap section boundaries to beat/downbeat markers when confidence is adequate.

This can be heuristic at first. It must expose confidence and be inspectable in
the UI.

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
      essentia-raw.json
      stems/
        vocals.wav
        instrumental.wav
```

Do not commit `.autodj-cache/`.

Fixture artifacts can live under `fixtures/metadata/` and `fixtures/plans/`.

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

If a model is nondeterministic, document that in the artifact provenance.

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

