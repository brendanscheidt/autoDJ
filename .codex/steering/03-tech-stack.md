# Tech Stack

## Summary Recommendation

Build the MVP as a desktop-first app with a portable C++ playback core and a
Python offline analysis worker.

```text
Desktop app / workbench:      C++20 + JUCE
Build system:                 CMake + CMakePresets + CTest
Playback engine:              C++20, JUCE audio primitives, swappable DSP backends
Time-stretch/pitch-shift:     Abstract interface; evaluate Superpowered/Rubber Band later
Analysis POC worker:          Python 3.10/3.11
Analysis POC libraries:       Essentia, librosa, madmom/BeatNet, aubio,
                               MSAF, Vamp/QM plugins, audioFlux, torchaudio,
                               pyAudioAnalysis, mir_eval, Basic Pitch as useful
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

Use Python 3.10 or 3.11 initially. Some MIR libraries lag newest Python
versions, so do not jump to 3.12+ until dependency compatibility is verified.

For each analysis feature that proves valuable, record:

- library/backend used,
- relevant parameters,
- output confidence behavior,
- generated-fixture expectations,
- known failure modes,
- licensing/platform constraints,
- portability estimate for a future C++ implementation.

## Essentia

Use Essentia as a primary POC/reference analysis library.

Useful capabilities:

- BPM and beat position extraction.
- Key estimation.
- Rhythm, tonal, spectral, loudness, and high-level descriptors.
- Command-line extractor that can emit JSON/YAML.
- C++ implementation with Python bindings, giving a future path to native
  integration if needed.

MVP use:

- Run Essentia from Python or CLI for baseline descriptors.
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
- BeatNet: AI-based real-time/offline beat, downbeat, tempo, and meter tracking;
  useful for comparing beat/downbeat quality.
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
- torchaudio: PyTorch audio/signal processing and feature extraction; useful if
  ML-based models become part of the POC.
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

Do not bind the architecture to a specific implementation yet. Define an engine
interface first:

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

Recommended MVP path:

- Build the player with an identity/no-op or simple resampling backend first.
- Keep tempo matching conservative.
- Add a high-quality backend only when deck playback and automation are stable.

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

- Essentia.
- librosa.
- madmom/BeatNet or another beat/downbeat comparison backend.
- MSAF or another section-analysis comparison backend.
- mir_eval for analysis quality evaluation.
- FFmpeg tools.
- Demucs optional stem separation.

Explicitly swappable:

- Time-stretch/pitch-shift backend.
- Metadata cache implementation before SQLite migration.
- Mobile UI framework.
- Downbeat/section detection models.
