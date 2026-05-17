# MIR Library Survey And WSL Analysis Environment

Task 3 establishes the installable dependency shape for the Python/WSL proof of
concept analyzer. Python dependencies remain optional extras so native Windows
worker tests and C++ verification do not require Linux-only MIR packages.

## Selected Extras

`analysis` is the portable baseline for signal loading and feature prototyping:

```bash
python -m pip install -e './analysis/worker-python[dev,analysis]'
```

It includes NumPy, SciPy, librosa, SoundFile, and audioread. This is the default
set for generated fixture work that does not need Essentia.

`analysis-wsl` is the WSL/Linux checkpoint set:

```bash
python -m pip install -e './analysis/worker-python[dev,analysis-wsl]'
```

It duplicates the baseline set and adds Essentia. PyPI did not expose a final
`essentia>=2.1b6` release for Python 3.11 during Task 3 verification; the
installable WSL constraint is `essentia>=2.1b6.dev1389,<2.2`.

`analysis-candidates` is for immediate Task 4 smoke-test candidates that are
promising and not obviously blocked by platform or licensing:

```bash
python -m pip install -e './analysis/worker-python[analysis-candidates]'
```

It includes audioFlux, pyAudioAnalysis, and mir_eval. MSAF is documented below
but is not in this extra because import verification failed against the current
SciPy line.

## WSL Setup Commands

Run from Windows PowerShell:

```powershell
wsl --status
wsl --list --verbose
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && python3.11 --version"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && python3.11 -m venv .venv-analysis"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pip install -U pip setuptools wheel"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pip install -e './analysis/worker-python[dev,analysis-wsl]'"
```

Verification imports:

```powershell
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python - <<'PY'
from importlib.metadata import version
import numpy, scipy, librosa, soundfile, audioread, essentia
print('numpy', numpy.__version__)
print('scipy', scipy.__version__)
print('librosa', librosa.__version__)
print('soundfile', soundfile.__version__)
print('audioread', version('audioread'))
print('essentia', essentia.__version__)
PY"
```

## Candidate Matrix

| Library/tool | Feature role | Install path | License | Platform notes | POC value | Native/mobile risk | Task 3 decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| librosa | Core loading fallback, onset strength, RMS helpers, tempo/beat experiments, chroma, recurrence/segmentation prototypes | `analysis`, `analysis-wsl`; `pip install librosa` | ISC per PyPI | Cross-platform Python; docs recommend FFmpeg for broader audioread decoding | High for feature engineering and fixture baselines | Moderate: behavior is Python/NumPy-heavy but algorithms are documented enough to reimplement selected pieces | Approved baseline |
| Essentia | Reference MIR descriptors, BPM/beat positions, rhythm/tonal/spectral/loudness descriptors | `analysis-wsl`; `pip install 'essentia>=2.1b6.dev1389,<2.2'` | AGPLv3 for non-commercial use, commercial license available | Linux PyPI wheel verified in WSL; official docs say Windows Python bindings are not supported yet | High for reference-quality descriptors and future C++ comparison | Licensing-dependent: AGPL/commercial decision needed before product-critical closed-source distribution | Approved for WSL POC only |
| madmom | Beat, downbeat, tempo, meter comparison | Deferred manual path: `pip install madmom` or source install | Source code BSD; bundled models/data CC BY-NC-SA unless stated otherwise | Older package; BeatNet docs note madmom 0.16.1 issues on Python >=3.10 and NumPy >=1.24 | Medium if installable, especially downbeat comparisons | High: old Python ecosystem plus non-commercial model/data terms | Deferred |
| BeatNet | AI beat/downbeat/tempo/meter tracking | Deferred manual path: `pip install BeatNet` | Repository advertises CC-BY-4.0 | PyPI has Python 3 wheel; depends on librosa/madmom and may inherit madmom compatibility issues | High for downbeat comparison if import works | High: model/data terms and dependency friction need review before product use | Deferred until madmom compatibility is isolated |
| aubio | Onset, tempo, beat, pitch, MFCC comparison; possible native C path | Deferred manual path: `pip install aubio` or Ubuntu `apt install python3-aubio aubio-tools` | GPLv3-or-later per repository | C library supports Linux, Windows, macOS, iOS, Android; Python package may build native code | Medium as a lightweight tempo/onset comparison and C portability signal | Licensing-dependent: GPL affects redistribution unless isolated/replaced | Deferred for license review |
| MSAF | Music structure segmentation experiments | Deferred manual path: `pip install msaf` | MIT per PyPI | PyPI 0.1.80 installs on CPython 3.11, but importing it failed in Task 3 with `ImportError: cannot import name 'inf' from 'scipy'` against SciPy 1.17.1 | Medium if compatibility is repaired or isolated | Moderate: useful for reference, but final section labels likely need independent heuristics | Deferred |
| Vamp/QM plugins | External reference outputs for tempo, bar/beat, key, tonal change, structure | Manual install of Vamp host/plugins, not a Python extra | QM plugins GPL; Vamp Plugin Pack redistributed under AGPLv3 because of bundled licenses | Requires plugin host and native plugin placement outside pip | Medium as an external validator | Licensing-dependent and operationally heavy; not suitable as default Python package dependency | Documented/manual only |
| audioFlux | Fast feature extraction, transforms, onset/pitch/HPSS comparisons | `analysis-candidates`; `pip install audioflux` | MIT | Docs list Linux, macOS, Windows, iOS, Android; source builds for mobile exist | High as a permissive, mobile-aware feature extraction comparison | Moderate: promising native/mobile path, but APIs and parity need validation | Candidate smoke test |
| pyAudioAnalysis | Feature extraction, classification, segmentation baseline | `analysis-candidates`; `pip install pyAudioAnalysis` | Apache-2.0 per paper/repository | Python package; may bring ML/data dependencies depending on used modules | Medium for segmentation and feature comparison | Moderate: useful baseline, not likely final realtime/mobile implementation | Candidate smoke test |
| torchaudio | PyTorch audio transforms/features for ML-oriented experiments | Deferred manual path from PyTorch docs; install matching `torch`/`torchaudio` wheels | BSD-style PyTorch license; model/data licenses can differ | Binary pairing with PyTorch is version/platform-specific; project is in maintenance phase | Medium if ML feature extraction becomes necessary | Hard: large runtime, model/data licensing, mobile inference path must be explicit | Deferred |
| Basic Pitch | Pitch/transcription experiments; not core BPM/beat analysis | Deferred manual path: `pip install basic-pitch` | Apache-2.0 | Supports Python 3.11 and Ubuntu; default runtime differs by platform | Low for Task 3 core analysis, possible later key/melody aid | Hard/moderate: ML runtime and model behavior need product decision | Deferred |
| mir_eval | Evaluation metrics for beat, tempo, key, structure comparisons | `analysis-candidates`; `pip install mir_eval` | MIT | Pure Python with NumPy/SciPy dependency | High for scoring generated fixtures and candidate outputs | Easy: evaluation-only, not a shipping analysis backend | Candidate smoke test |

## Source URLs

- librosa install/license: https://librosa.org/doc/main/install.html and https://pypi.org/project/librosa/
- Essentia install/license/platform: https://essentia.upf.edu/installing.html and https://essentia.upf.edu/licensing_information.html
- madmom install/license: https://github.com/CPJKU/madmom
- BeatNet install/license notes: https://github.com/mjhydri/BeatNet and https://pypi.org/project/BeatNet/
- aubio install/platform/license: https://aubio.org/manual/latest/installing.html and https://github.com/aubio/aubio
- MSAF install/license: https://pypi.org/project/msaf/ and https://github.com/urinieto/msaf
- Vamp/QM plugins: https://isophonics.net/QMVampPlugins.html and https://vamp-plugins.org/pack.html
- audioFlux install/platform/license: https://libaudioflux.github.io/audioFlux/docs/installing.html and https://libaudioflux.github.io/audioFlux/
- pyAudioAnalysis license/role: https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0144610 and https://github.com/tyiannak/pyAudioAnalysis
- torchaudio install/runtime notes: https://docs.pytorch.org/audio/stable/installation.html and https://github.com/pytorch/audio
- Basic Pitch install/platform/license: https://github.com/spotify/basic-pitch
- mir_eval install/license: https://github.com/mir-evaluation/mir_eval

## 2026 Research Update: Beatgrid, Structure, And Automatic DJ Mixing

Researched 2026-05-17. The practical conclusion is that the project should not
hand-roll timing-critical beat and downbeat tracking from scratch. The POC
should keep the current deterministic/electronic-music cleanup layer, but place
it behind a backend interface that can compare our local implementation against
Rekordbox XML, madmom/BeatNet-style beat/downbeat trackers, and optional hosted
analysis providers.

### Beatgrid And Downbeat Tracking

The strongest open research signal is still hybrid ML plus probabilistic
sequence decoding: neural beat/downbeat activations, then a DBN, particle
filter, Viterbi, or similar temporal model to enforce plausible tempo/phase.
This matches what our current analyzer is missing when it gets close but not
perfect: local transients are easy to see, but the global grid phase needs a
model that reasons over the full metrical sequence.

- madmom remains a key reference implementation. It exposes RNN beat
  activations and DBN beat tracking that return beat positions in seconds, plus
  a downbeat tracker that returns beat positions and beat numbers inside the bar.
  Its model/data licensing is non-commercial unless separately licensed, so it
  is best used as an evaluation backend first.
- BeatNet is directly aligned with the POC need: joint beat, downbeat, tempo,
  and meter tracking with a CRNN and particle filtering. It is more attractive
  than a raw librosa-only path, but dependency friction needs an install spike
  because it can inherit madmom compatibility issues.
- Beat Transformer is a more recent research direction: demix audio into stems
  and run a Transformer over instrument-aware channels. The paper reports better
  beat/downbeat performance from demixed inputs, which is useful evidence that
  drums/bass/stem-aware analysis is worth prototyping for DJ material.

Recommended POC move: implement a `BeatGridBackend` contract with
`current_signal`, `rekordbox_xml`, and one ML/reference backend. Score against
the user-provided Rekordbox XMLs using first-beat error, median beat error,
95th-percentile beat error, and drift at cue points.

### Structure, Sections, And Cue Points

General music structure analysis is useful, but it does not map cleanly to DJ
semantics like "drop 1 start", "drop 2 end", or "mix-out" without domain rules.
MSAF provides a framework for segmentation and repeated-section grouping, while
newer deep-learning work predicts structural functions such as intro, verse,
chorus, bridge, outro, instrumental, and silence. Those labels are adjacent to
our needs, not a complete substitute.

For electronic/DJ workflows, cue detection papers focus on "switch points" for
transition construction rather than general song explanation. That is closer to
our app than generic verse/chorus labeling. We should use ML/segmentation to
propose candidates, then snap candidates to beat/downbeat/phrase boundaries and
rank them with energy, bass, onset density, vocal presence, and repeated-section
evidence.

Recommended POC move: keep heuristic cue generation, but split it into two
steps: candidate generation and beat/phrase-aligned ranking. Add a manual or
Rekordbox-imported cue overlay as gold data for evaluation.

### Stems And Semantic Features

Source separation is viable and useful, but too expensive to make mandatory in
the fast path. Demucs and Spleeter both provide mature stem separation paths for
vocals/drums/bass/other. Beat Transformer and Mosaikbox both support the idea
that stem-aware analysis can improve DJ-relevant decisions.

Recommended POC move: make stems an offline optional enrichment pass. Use drums
and bass to improve beat/downbeat confidence; use vocals to avoid vocal clashes;
use stem energy changes to rank drops, breakdowns, and mix points.

### Track Similarity And Set Planning

Large music embedding models such as MERT and Essentia's TensorFlow/Discogs
embeddings are better suited for similarity, mood, energy, genre, and broad
semantic retrieval than exact beatgrid placement. They can help answer "what
should play next?" but should not be trusted for sub-10ms grid alignment.

Recommended POC move: use embeddings for library browsing and track
compatibility, not as the timing source of truth.

### Hosted Analysis Providers

Hosted services are viable for a quick comparison path, but they should be
optional because they add cost, latency, privacy/licensing questions, and vendor
lock-in. Music AI advertises workflows for BPM and beat maps; Klangio advertises
beat/downbeat timings, BPM, and meter; Cyanite exposes BPM, key, mood, genre,
movement, energy level, and time-segmented descriptors. These are worth testing
as reference outputs, but Rekordbox XML import remains the strongest POC gold
path because it represents the DJ workflow the user already trusts.

### Automatic DJ Mixing

Recent automatic DJ systems support a hybrid direction, not a single model we
can drop in. The Drum and Bass auto-DJ system uses cue selection, beatmatching,
time-stretching, and crossfading. The cue-point paper targets electronic dance
music switch points. Mosaikbox combines MIR, source separation, precise
beat-grid estimation, and rule-based stem modification. GAN/differentiable DSP
transition work is interesting, but it is research-grade and should not control
the core POC experience yet.

Recommended product architecture:

1. Import/compare trusted metadata first: Rekordbox XML beatgrid and cues.
2. Add ML/reference beatgrid backends and evaluate them against the XMLs.
3. Keep deterministic phrase, BPM normalization, and electronic-music cleanup
   rules around the backend output.
4. Use stem/embedding/semantic models for suggestions and cue ranking, not for
   final timing without validation.
5. Make manual correction a first-class workflow; DJ tools work well partly
   because users can correct grids/cues quickly.

Primary research and implementation sources:

- madmom repository and docs: https://github.com/CPJKU/madmom and https://madmom.readthedocs.io/en/v0.16.1/modules/features/beats.html
- madmom paper: https://arxiv.org/abs/1605.07008
- BeatNet paper and implementation: https://arxiv.org/abs/2108.03576 and https://github.com/mjhydri/BeatNet
- Beat Transformer paper and implementation: https://arxiv.org/abs/2209.07140 and https://github.com/zhaojw1998/Beat-Transformer
- MSAF implementation: https://github.com/urinieto/msaf
- Structural-function analysis paper: https://arxiv.org/abs/2205.14700
- Automatic cue points for DJ mixing: https://arxiv.org/abs/2007.08411
- Drum and Bass automatic DJ system: https://link.springer.com/article/10.1186/s13636-018-0134-8
- Automatic DJ transitions with differentiable DSP/GANs: https://arxiv.org/abs/2110.06525
- Mosaikbox automatic mixing system: https://repositum.tuwien.at/handle/20.500.12708/212628 and https://github.com/robaerd/mosaikbox
- Demucs source separation: https://arxiv.org/abs/1909.01174 and https://github.com/facebookresearch/demucs
- Spleeter source separation: https://github.com/deezer/spleeter
- MERT music representation model: https://arxiv.org/abs/2306.00107 and https://github.com/yizhilll/MERT
- Essentia model catalog: https://essentia.upf.edu/models.html
- Music AI API reference: https://music.ai/docs/api/reference/
- Klangio API docs: https://api-docs.klang.io/
- Cyanite classifier docs: https://api-docs.cyanite.ai/docs/audio-analysis-v6-classifier/
