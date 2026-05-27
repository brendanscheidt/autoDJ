# Timing-Sensitive Audio Path Audit

## Summary

The current system has several timing-sensitive paths that can decode or
resample audio differently. This is acceptable for broad analysis, but risky for
drop-switch alignment. The Spec 010 canonical PCM work should make the
canonical WAV the preferred source for every path below.

## Current Paths

| Path | Current Decoder / Sample Rate | Timing Risk | Spec 010 Action |
|---|---|---|---|
| Batch signal analysis | `soundfile.read` through `load_audio`, default target sample rate `22050` | BPM/beatgrid and debug artifacts are produced from a resampled mono signal, not necessarily the same timeline used by render/nudge. | Prefer canonical PCM and record canonical artifact path/provenance. Revisit sample rate after canonical timing cache is in place. |
| Current signal backend | `CurrentSignalBackend.load_track_audio()` calls `load_audio()` with default `22050` | Same as batch analysis; implicit analysis-rate resampling. | Allow caller to provide canonical decoded audio or canonical path. |
| Debug waveform CLI | `load_audio(..., target_sample_rate=args.sample_rate)`, default `22050` | Visual waveform may not match render/nudge sample source exactly. | Add canonical input option or let canonical root drive the source. |
| Semantic section backend working WAV | `_write_section_analysis_audio()` writes `analysis.wav` from already decoded analysis audio | Good that it normalizes for backend use, but it inherits the current decoded/resampled timeline. | Write from canonical PCM instead when available. |
| All-In-One backend | Warns about MP3 decoder differences; may run against source path or temporary analysis WAV depending caller | Known 20-40ms MP3 decoder offset class. | Feed canonical WAV whenever running timing/structure comparisons. |
| SongFormer backend | Reported as source-path timing risk in warnings | Same decoder consistency concern. | Feed canonical WAV for future comparisons. |
| CUE-DETR | Direct `librosa.load(..., sr=sample_rate)` | Uses librosa decoder/resampling and independent timeline. | Treat research-only unless canonical WAV is passed. |
| Tempo/nudge post-pass | `mixplan_nudge` loads plan audio via renderer helper, usually at `44100` | Uses a different sample rate and decoding path than analysis. This is the most important mismatch for transition alignment. | Prefer canonical PCM and report fallback when using direct source decode. |
| Offline renderer | `_load_audio` uses WAV reader for WAV, otherwise `load_audio(..., sample_rate)` | Rendering may decode MP3 directly instead of the analysis timeline. | Prefer canonical PCM or canonicalized derived assets for render/audition. |
| Tempo stretch | Uses FFmpeg/SoundStretch intermediate WAV flow | Usually stable after stretch, but source BPM validation still relies on upstream artifacts. | Record canonical source and rerun lightweight BPM/beat validation after stretch. |
| Key analysis | Uses decoded audio from current signal analysis | Key is less timing-sensitive, but it should still prefer canonical PCM for consistency. | Prefer canonical PCM when batch path is updated. |

## Current Centering / Frame Alignment Risks

- `librosa.onset.onset_strength(...)` calls in `tempo.py` and `features.py` do
  not explicitly set `center=False`.
- `cue_detr.py` uses `librosa.load` and mel features directly; this path is
  research-only for now.
- Existing feature artifacts generally do not record enough frame-alignment
  provenance for millisecond debugging.

## Immediate Engineering Implication

Do not try to tune a few nudge constants until decoder/timeline provenance is
fixed. The next code task should create canonical PCM artifacts and expose them
through CLI/reporting. Only after that should the richer timing feature branch
be trusted.

