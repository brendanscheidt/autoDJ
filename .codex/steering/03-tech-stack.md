# Tech Stack

## Summary Recommendation

Build the MVP as a desktop-first app with a portable C++ playback core and a
Python offline analysis worker.

```text
Desktop app / workbench:      C++20 + JUCE
Build system:                 CMake + CMakePresets + CTest
Playback engine:              C++20, JUCE audio primitives, swappable DSP backends
Time-stretch/pitch-shift:     Abstract interface; Spec 009 evaluates Rubber Band,
                               SoundTouch, Signalsmith Stretch, Superpowered,
                               zplane elastique, and related SDKs
Analysis POC worker:          Python 3.11 in WSL for the full MIR stack;
                               lightweight Windows Python for dev/test only
Selected timing backend:      current-autodj-signal
Trusted POC semantic source:  Rekordbox XML hot-cue labels
Experimental section backend: dubstep-phrase-hybrid
Analysis POC libraries:       librosa/soundfile/audioread/scipy/numpy baseline;
                               All-In-One and SongFormer for semantic evidence;
                               Essentia, Beat This, and other MIR tools as
                               comparison/deferred candidates
Production mobile analysis:   Native/mobile-portable C++ or licensed native
                               libraries derived from the winning POC behavior
Stem separation:              Demucs for MVP experiments
Audio decoding for analysis:  FFmpeg CLI/tools first, library integration later
Metadata cache:               JSON artifacts first, SQLite later
Contracts:                    Versioned JSON schemas
Mobile future:                Reuse C++ core; wrap with native UI, Flutter, or JUCE mobile
```

## Platform Direction

Start desktop-first and mobile-aware.

Desktop-first gives faster iteration on the hard product question: whether the
generated set sounds musically credible. Mobile should influence architecture
constraints, but not lead the MVP.

Mobile-aware means:

- Playback core is C++ and avoids desktop-only assumptions.
- Contracts are file/schema based, not UI-framework dependent.
- Analysis and stem generation are isolated from real-time playback.
- Time-stretch/effect backends are behind interfaces.
- The UI does not own the engine model.

## C++20

Use C++20 for shared domain and playback code.

Reasons:

- Native performance for real-time audio.
- Direct access to mature audio/DSP libraries.
- Portable to desktop and mobile.
- Good fit for JUCE, Superpowered, Oboe, and platform audio APIs.

Avoid overusing templates or complex metaprogramming in shared domain code.
Contracts should stay obvious and easy to bind from other languages later.

## JUCE

Use JUCE for the desktop app and initial playback surface.

Why:

- Cross-platform native application support across Windows, macOS, Linux, iOS,
  and Android.
- Audio device handling, audio processing helpers, file decoding utilities, GUI
  framework, and native tooling integration.
- CMake integration is supported.
- It allows a single C++ workbench that can later inform mobile reuse.

MVP use:

- Desktop UI shell.
- Audio device management.
- Basic deck playback.
- DSP primitives where adequate.
- Waveform/transport visualization.

Keep a clear boundary between `core/playback` and the JUCE desktop UI so future
mobile wrappers can reuse the engine.

Licensing note: JUCE has GPL/commercial licensing considerations. Review before
commercial distribution.

Sources:

- JUCE home/platform overview: https://juce.com/
- JUCE repository overview: https://github.com/juce-framework/JUCE
- JUCE tutorials: https://juce.com/learn/tutorials/

## CMake

Use CMake as the primary build system.

Reasons:

- Works with JUCE.
- Supports Visual Studio, Ninja, Xcode, and CI.
- Allows separate core libraries, tests, and app targets.
- Keeps desktop and future mobile native code organized.

Use `CMakePresets.json` so common commands are stable:

```powershell
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
```

## Python Analysis Worker / POC Analyzer

Use Python heavily for the proof-of-concept analysis engine and stem separation
experiments.

Reasons:

- Best ecosystem for music information retrieval experiments.
- Faster iteration on heuristics and ML models.
- Easier integration with Demucs, librosa, and research libraries.
- Analysis is offline for the desktop POC, so real-time constraints do not
  require C++ yet.

Important product constraint:

- Python is not assumed to be the final mobile analysis runtime.
- A full offline mobile app must eventually analyze local phone audio on device.
- Treat the Python worker as a POC/reference analyzer that discovers the best
  algorithms and feature combinations, produces golden artifacts, and informs a
  later native/mobile-portable analyzer.
- An all-in-one Windows desktop app may bundle or launch a Python worker during
  the POC/productization phase, but mobile should not depend on WSL or CPython.

Prefer a CLI/process boundary first:

```text
autodj-analysis analyze <input-file> --out <artifact-dir>
autodj-analysis analyze-batch <manifest.json> --out <cache-dir>
```

The C++ app can invoke the worker or consume artifacts generated externally.

Use Python 3.11 in WSL for the full analysis environment. Some MIR libraries lag
newest Python versions, so do not jump to 3.12+ until dependency compatibility
is verified. Windows Python can run lightweight tests and rough-section smoke
paths. Heavy semantic candidate backends should be treated as WSL/Linux
research runtimes unless a later packaging task proves otherwise.

Current selected analysis stack:

- BPM/beatgrid: `current-autodj-signal`, the project-owned electronic-music
  timing stack.
- Trusted POC semantic source: Rekordbox XML hot-cue labels normalized into the
  `AnalyzedTrack` section/cue contract.
- Key: `selected-madmom-keyfinder`, a production confidence-gate ensemble that
  chooses `madmom-cnn-key` at confidence `>= 0.30` and otherwise falls back to
  `keyfinder`.
- Experimental automatic sections: `dubstep-phrase-hybrid`, which fuses
  All-In-One and SongFormer boundary evidence with selected
  beatgrid/energy/bass/onset features and dubstep phrase heuristics.
- Fallback: `current-autodj-signal` rough sections only when the caller accepts
  low-confidence automatic sections.

Current full WSL extras:

```text
analysis-wsl, all-in-one, songformer
```

The experimental semantic path pulls in PyTorch/Torchaudio, TorchCodec, NATTEN,
Demucs, CPJKU madmom, Transformers 4.51.x, Hugging Face Hub 0.30.x, MuQ, MSAF,
and related model/runtime packages. Keep those optional and isolated from
package import; missing heavy dependencies should produce structured
unavailable/fallback behavior, not break lightweight tooling.

For each analysis feature that proves valuable, record:

- library/backend used,
- relevant parameters,
- output confidence behavior,
- generated-fixture expectations,
- known failure modes,
- licensing/platform constraints,
- portability estimate for a future C++ implementation.

## Selected Analysis Backends

### current-autodj-signal

Use `current-autodj-signal` as the selected BPM and beatgrid backend for the
POC.

Why:

- Project-owned and deterministic.
- Matched the known Rekordbox BPM/beatgrid cases better than the evaluated
  timing candidates.
- Emits complete beat grids, while several ML candidates looked deceptively good
  only on nearest-beat error because they emitted sparse grids.
- Keeps production artifacts free of timing fallback ambiguity.

Do not auto-fallback from selected timing to Essentia, Beat This, or All-In-One
timing without a new benchmark and manual user verdict.

### dubstep-phrase-hybrid

Use `dubstep-phrase-hybrid` as the best current automatic semantic section
candidate, not as the trusted transition-planning oracle.

Why:

- All-In-One and SongFormer both found useful boundaries but weak/wrong
  pop-form labels for dubstep.
- The hybrid layer uses those boundaries as evidence and maps them through
  beat/bar, energy, bass, onset, and dubstep phrase heuristics.
- It exposes useful build/drop pairs for transition planning while keeping
  confidence and warnings honest.

Runtime caveats:

- Heavy WSL/Linux ML dependency stack.
- Model/data/license terms still require productization review before
  commercial distribution.
- Long dense tracks, light/non-standard dubstep, and long inter-drop breaks are
  known failure classes; transition planning should stay confidence-aware.
- Manual Rekordbox XML labels should override this backend when available for
  audition-quality set planning.

## Essentia

Use Essentia as a comparison/reference analysis library, not as the selected
timing backend.

Useful capabilities:

- BPM and beat position extraction.
- Key estimation.
- Rhythm, tonal, spectral, loudness, and high-level descriptors.
- Command-line extractor that can emit JSON/YAML.
- C++ implementation with Python bindings, giving a future path to native
  integration if needed.

POC use:

- Run Essentia from Python or CLI for baseline descriptors and future native
  portability comparison.
- Store raw extractor outputs for debugging.
- Normalize key fields into `AnalyzedTrack`.

Sources:

- Music extractor descriptors: https://essentia.upf.edu/streaming_extractor_music.html
- Algorithms overview: https://essentia.upf.edu/documentation/algorithms_overview.html
- Licensing: https://essentia.upf.edu/licensing_information.html

## librosa

Use librosa heavily for prototyping and secondary analysis.

Useful capabilities:

- Beat and tempo experiments.
- Onset strength.
- Chroma features.
- Recurrence/structure experiments.
- Fast Python iteration for feature engineering.

MVP use:

- Generate experimental section and energy features.
- Compare/validate beat-related results against Essentia.
- Prototype heuristics before porting any stable logic.

Source:

- Beat and tempo docs: https://librosa.org/doc/latest/beat.html

## Additional POC Analysis Libraries

Evaluate additional libraries when they may improve analysis quality. Do not
limit the POC to one library if a combination produces better artifacts.

Candidates:

- madmom: beat, downbeat, tempo, and MIR models; BSD-licensed source unless
  otherwise indicated, but older ecosystem and model/dependency compatibility
  must be checked.
- Beat This: modern ML beat/downbeat comparison backend. Useful for benchmark
  evidence, but not selected because it emitted sparse grids and no native BPM
  in the Spec 005 integration.
- BeatNet: AI-based real-time/offline beat, downbeat, tempo, and meter tracking;
  deferred because it overlaps Beat This and carries dependency friction.
- aubio or maintained aubio forks: onset, tempo, beat, pitch, MFCC, and command
  line tools; GPL licensing can affect redistribution decisions.
- MSAF: music structural segmentation experiments; useful for section boundary
  POC work.
- Vamp/QM plugins: tempo/beat, bar/beat, key, tonal change, and segmentation
  plugins; useful as a reference and potential native/plugin path.
- audioFlux: MIT-licensed audio/music feature extraction library with C/Python
  implementation and broad transform/feature support.
- pyAudioAnalysis: Apache-licensed feature extraction, classification, and
  segmentation library; useful as a comparison baseline.
- All-In-One: joint timing/functional section model. It remains useful as an
  automatic section-boundary evidence source, but is not selected for timing.
- SongFormer: semantic section model. It remains useful as an automatic
  section-boundary evidence source.
- torchaudio: PyTorch audio/signal processing and feature extraction; needed by
  several ML candidates.
- Basic Pitch: Apache-licensed audio-to-MIDI/pitch transcription from Spotify;
  not a core BPM solution, but useful for melody/pitch experiments.
- mir_eval: evaluation metrics for beat, tempo, key, and other MIR tasks; use it
  to compare candidate outputs against generated fixtures and curated references.

Every candidate must be checked for installability, license, runtime/platform,
artifact quality, and future mobile/native implications before it becomes a
production dependency.

## madmom

Treat madmom as optional for beat/downbeat experiments.

Useful capabilities:

- Beat and downbeat tracking models.
- Music information retrieval algorithms that may improve phrase alignment.

Caveats:

- Older ecosystem and potential install friction on modern Python.
- Model licensing/commercial constraints need review.
- Should not block the foundation build.

Source:

- Downbeat tracking docs: https://madmom.readthedocs.io/en/v0.16/modules/features/downbeats.html

## Demucs

Use Demucs for MVP stem separation experiments.

Useful capabilities:

- Vocal, drums, bass, and other stem separation.
- Two-stem vocal extraction mode.
- Good enough to test acapella/instrumental transition ideas.

Caveats:

- The original repository was archived on January 1, 2025 and is read-only.
- The maintainer notes that the project is not actively maintained.
- CPU processing can be slow; GPU support is helpful.
- Stem quality is not guaranteed and must be scored before use in transitions.
- Commercial/product use needs licensing and model/data review.

MVP use:

- Optional offline step.
- Cache stems on disk.
- Use stems only when quality/confidence clears a threshold.

Source:

- Demucs repository and maintenance notice: https://github.com/facebookresearch/demucs

## FFmpeg

Use FFmpeg tools for broad audio decoding/transcoding in the analysis pipeline.

Useful capabilities:

- Broad file/container/codec support.
- `ffprobe` for metadata inspection.
- Conversion to normalized WAV/PCM for analysis.

MVP use:

- Invoke `ffprobe` and `ffmpeg` from the Python worker when needed.
- Avoid deep libav integration until there is a clear need.

Licensing note: FFmpeg builds vary by enabled codecs and can be LGPL or GPL
depending on configuration. Review distribution implications before shipping.

Sources:

- FFmpeg documentation index: https://www.ffmpeg.org/documentation.html
- libavformat docs: https://ffmpeg.org/libavformat.html

## SQLite

Use JSON files first and SQLite once artifacts need querying.

Why SQLite later:

- Single local database file.
- Good fit for metadata cache, migrations, and local app state.
- Native C/C++ API and broad platform support.
- JSON fields can be stored when useful, while keeping indexes for common
  queries.

MVP sequence:

1. Start with versioned JSON artifacts under a cache directory.
2. Add SQLite once repository and analyzer state need robust invalidation,
   querying, and migrations.

Sources:

- SQLite docs: https://sqlite.org/docs.html
- SQLite C/C++ API introduction: https://www.sqlite.org/cintro.html

## Time-Stretch And Pitch-Shift Backends

Do not bind the architecture to a specific implementation until Spec 009
auditions real dubstep transitions. Define an engine interface first:

```cpp
class ITimeStretchEngine {
public:
    virtual ~ITimeStretchEngine() = default;
    virtual void prepare(double sampleRate, int channels) = 0;
    virtual void setRate(double rate) = 0;
    virtual void setPitchCents(double cents) = 0;
    virtual void process(...) = 0;
};
```

Candidates:

- Superpowered: strong mobile-focused C++ audio SDK with time stretching,
  pitch shifting, decoders, effects, mixing, and music analysis.
- Rubber Band: high-quality time-stretch/pitch-shift library with
  GPL/commercial licensing.
- SoundTouch: simpler tempo/pitch/rate library, useful for experiments.
- zplane elastique: commercial pro-grade option, evaluate if quality demands it.
- Signalsmith Stretch: MIT header-only C++ pitch/time library, attractive for
  native integration if quality is acceptable.
- Zynaptiq ZTX: commercial high-end C/C++ SDK for time-stretching,
  pitch-shifting, and formant-aware processing.

Current MVP path:

- Spec 009 should add pitch-preserving tempo control before broad set planning.
- Engine/manual MixPlans may request arbitrary stretch ratios, subject to
  backend capability and explicit quality warnings.
- Automatic planner selection should default to a configurable
  `maxTempoAdjustmentBpmPerDeck = 10.0`, allowing a total 20 BPM bridge when
  both decks can meet at an exact shared transition BPM.
- Start with local/offline audition quality before committing to a native/mobile
  runtime dependency.
- Spec 010 now handles canonical PCM/drop-anchor timing refinement because exact
  drop timing became the project-critical risk. The inverse tool, key shifting
  without changing BPM, remains the next planned pitch/time toolbox spec after
  the timing work.

Sources:

- Superpowered overview: https://superpowered.com/audio-overview
- Superpowered TimeStretching docs: https://docs.superpowered.com/reference/latest/time-stretching?lang=cpp
- Rubber Band: https://breakfastquay.com/rubberband/
- SoundTouch: https://www.surina.net/soundtouch/

## Mobile Future

The mobile path should reuse the C++ engine and eventually include an offline
native/mobile-portable analysis path.

Possible UI shells:

- Native Swift/Kotlin UI with C++ engine bindings: best platform feel and audio
  control, but more duplicated UI work.
- Flutter UI with C++ FFI/native plugin: strong cross-platform UI, bridge
  complexity around audio state.
- JUCE mobile app: same C++ framework, potentially fastest if the UI is
  acceptable.

Mobile audio considerations:

- Android low-latency audio should use Oboe/AAudio concepts if going native.
- iOS has AVAudioEngine and Core Audio options, but a custom C++ core still
  needs careful audio session and buffer management.
- On-device ML for stems/analysis may need ExecuTorch or another mobile
  inference runtime later, but the MVP should remain offline desktop.
- If Python POC algorithms prove product-critical, later specs must either port
  their behavior to C++/mobile-safe libraries or make an explicit licensing and
  packaging decision for native third-party libraries.

Sources:

- Android low-latency audio guidance: https://developer.android.com/games/sdk/oboe/low-latency-audio
- Apple AVAudioEngine: https://developer.apple.com/documentation/AVFAudio/AVAudioEngine
- ExecuTorch overview: https://docs.pytorch.org/get-started/executorch/

## Dependency Decision Levels

Firm for MVP:

- C++20.
- CMake.
- JUCE desktop app.
- Python analysis worker.
- JSON contract artifacts.

Likely for MVP:

- librosa.
- soundfile/audioread/scipy/numpy analysis baseline.
- current-autodj-signal timing.
- Rekordbox XML semantic labels for current planning/audition truth.
- dubstep-phrase-hybrid sections in WSL as automatic candidate/fallback output.
- All-In-One and SongFormer as automatic-section evidence providers.
- Essentia, Beat This, and other candidates as explicit comparison/deferred
  paths only.
- mir_eval or equivalent metrics for analysis quality evaluation.
- FFmpeg tools.
- Demucs optional stem separation.

Explicitly swappable:

- Time-stretch/pitch-shift backend.
- Metadata cache implementation before SQLite migration.
- Mobile UI framework.
- Downbeat/section detection models.
