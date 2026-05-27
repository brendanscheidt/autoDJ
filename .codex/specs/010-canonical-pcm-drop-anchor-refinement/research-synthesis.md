# Research Synthesis

## Decision

Spec 010 treats exact drop timing as the project-critical risk. Key shifting is
still important, but it moves behind drop-anchor refinement because every
drop-switch, loop, double, or tempo-matched transition depends on the same
question: did AutoDJ choose the true first impact of the drop?

The two reports agree that a useful AutoDJ analyzer should not be just one BPM
number and should not be "nearest transient wins." The best near-term approach
is:

1. Decode once to canonical PCM.
2. Build timing-safe rhythmic views.
3. Export candidate evidence around labeled drops.
4. Score exact drop anchors with interpretable DSP features.
5. Prove the result through strict metrics and audition before changing the
   default transition path.

## Useful ML Report Findings

- Standard MIR beat and structure metrics are too loose for DJ use. A beat F1
  window around tens of milliseconds and section windows around fractions of a
  second can still sound bad when two dubstep kicks overlap.
- Public ML section systems can find neighborhoods and arrangement changes, but
  they should not be trusted for millisecond-accurate transition anchors without
  PCM-domain refinement.
- Raveform is relevant because it uses EDM-specific functional labels and
  beat/downbeat/segment annotations. It is a future dataset/model path, not a
  dependency for the first Spec 010 implementation.
- The current 48-song set is useful for regression and manual audition. It is
  too small to train a final drop model without overfitting.
- A narrow drop-anchor ranker is a better first learning target than full
  semantic section labeling. The dataset built here can support that later.

## Useful Non-ML DSP Report Findings

- BPM detection and beat placement are separate tasks.
- Canonical decoding is mandatory because MP3 decoder offsets can be large
  enough to ruin transition timing.
- Timing feature extraction must make frame alignment explicit. `librosa`
  defaults such as centered onset frames are acceptable for MIR, but suspicious
  for sample-level DJ timing.
- HPSS/percussive isolation should be the first cheap way to suppress harmonic
  smearing before onset and transient analysis.
- Multiband onset views matter in dubstep: kick/sub, body/snare, high/noise,
  and broadband energy do not fail in the same way.
- Onset backtracking, reassigned-time spectrogram features, and local
  cross-correlation are promising sub-frame refinement tools.
- Beatgrid refinement must be global or phase-constrained. Independent local
  snapping caused audible regressions earlier and should not be repeated.

## Techniques Selected For First Implementation

| Technique | Role | Why |
|---|---|---|
| Canonical PCM cache | Timeline foundation | Removes hidden decoder differences and gives every path one timing source. |
| Explicit timing provenance | Safety | Makes sample rate, hop length, STFT centering, and decoder identity inspectable. |
| HPSS/percussive branch | Local timing feature | Suppresses pads/vocals/bass smears and emphasizes rhythmic attacks. |
| Multiband onset envelopes | Candidate feature export | Separates kick/sub impact from body/noise/riser evidence. |
| Low-band jump and bass persistence | Drop-anchor scoring | Dubstep drops usually become sustained low-energy events, not isolated clicks. |
| Pre/post energy jump | Drop-anchor scoring | Captures release from build/break into drop impact. |
| Candidate dataset JSONL | Debug/evaluation | Lets us inspect every nearby transient and understand wrong picks. |
| Strict ms-level metrics | Acceptance | Project success depends on audible alignment, not MIR benchmark pass/fail. |

## Techniques Deferred

| Technique | Deferral Reason |
|---|---|
| Full custom ML model | The current 48-song set is too small for robust training. Build the candidate dataset first. |
| Raveform training/fine-tuning | Worth investigating later after local candidate/evaluation tooling exists. |
| Beat Transformer / demixed neural front ends | Potentially useful, but heavier than the immediate deterministic timing branch. |
| Full self-similarity section detector | Section labeling remains secondary while Rekordbox semantic truth is available. |
| Whole-track default beatgrid refit | Risky because previous local snapping regressed audible timing. Start with shadow artifacts only. |

## Verified Reference Pages

- All-In-One MP3 offset warning:
  https://github.com/mir-aidj/all-in-one
- Raveform EDM dataset:
  https://mir-aidj.github.io/raveform/
- Raveform dataset article:
  https://reference-global.com/article/10.5334/tismir.288
- librosa onset centering:
  https://librosa.org/doc/main/generated/librosa.onset.onset_strength.html
- librosa HPSS:
  https://librosa.org/doc/main/generated/librosa.effects.hpss.html
- librosa reassigned spectrogram:
  https://librosa.org/doc/main/generated/librosa.reassigned_spectrogram.html
- aubio onset methods:
  https://aubio.org/manual/latest/cli.html
- madmom DBN beat tracking:
  https://madmom.readthedocs.io/en/v0.14.1/modules/features/beats.html

