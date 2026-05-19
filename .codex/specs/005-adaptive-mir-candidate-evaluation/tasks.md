# Implementation Plan

## Execution Rules

- Before starting any task, read `kiro.json`, `requirements.md`, `design.md`,
  `research-plan.md`, and the required steering docs listed in `kiro.json`.
- This spec is adaptive. Do not mark downstream implementation tasks complete
  until the research, benchmark, and manual-verdict gates have produced
  evidence.
- Prefer primary sources during research: papers, official repositories,
  official documentation, provider docs, and model cards.
- Keep real audio, Rekordbox exports, generated artifacts, and local benchmark
  outputs out of git unless a task explicitly creates sanitized documentation.
- Use the current AutoDJ BPM/beatgrid analyzer as the incumbent baseline.
- Treat the current heuristic section labeler as disposable unless evidence
  shows it remains useful.
- Stop at manual checkpoint tasks and ask the user to inspect the generated
  artifacts before making final selection decisions.
- Do not run benchmark tasks against a candidate that has only graceful
  unavailable behavior. A candidate is benchmark-eligible only after it has a
  real install, model/package access where applicable, a real smoke test, and
  implemented outputs for the specific benchmark lane.
- Do not treat section-only candidates as timing candidates. If a researched
  tool does not actually emit BPM/beatgrid data on real audio through the
  installed runtime, remove it from timing benchmarks instead of filling results
  with failures.
- If a task is blocked, leave it unchecked and add a short blocker note with
  command output, source links, or missing decision context.

## Tasks

- [x] 1. Complete deep MIR and AutoDJ research dossier
  - Read `research-plan.md` and existing
    `.codex/specs/004-real-audio-analysis-baseline/mir-library-survey.md`.
  - Research BPM, beatgrid, downbeat, meter, stem separation, semantic section,
    cue point, mix-section, transition, set-planning, and track-compatibility
    systems.
  - Use primary sources wherever possible.
  - Create a research dossier in this spec folder with candidate matrices.
  - Record installability, license/model-data terms, runtime/platform risk,
    compute cost, expected outputs, and AutoDJ fit.
  - Mark each candidate as `evaluate-now`, `defer`, or `reject`.
  - Do not implement candidate backends in this task except small install
    probes needed to judge feasibility.
  - Research-gate note:
    - Added
      `.codex/specs/005-adaptive-mir-candidate-evaluation/research-dossier.md`
      with primary-source research, candidate matrices, first-wave
      recommendations, benchmark plan, deferred future-spec backlog, and source
      URLs.
    - First-wave `evaluate-now` candidates are: current AutoDJ signal backend
      as incumbent, `beat-this` for modern beat/downbeat ML comparison,
      `all-in-one` for joint timing and functional section analysis,
      `essentia-rhythm` for a fast/native-reference timing comparison, and
      `songformer` for semantic sections.
    - BPM/beatgrid remains a strong incumbent and must be replaced only with
      measured improvement or clear operational benefit.
    - The current heuristic section labeler remains only a weak fallback; the
      next tasks should not preserve it as the main section architecture.
    - Stem separation, set planning, transition techniques, hosted providers,
      embeddings, and commercial native SDKs are documented for future specs
      unless they directly unblock selected timing/section candidates.
    - No code was changed in this task, so no unit tests were added; validation
      was limited to spec-document sanity checks.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 7.1_

- [x] 2. Refine requirements, design, and tasks after research gate
  - Update `requirements.md` with evidence-driven candidate requirements.
  - Update `design.md` with the selected candidate backend architecture.
  - Update this `tasks.md` with concrete backend spike tasks for the
    `evaluate-now` candidates.
  - Keep deferred set-planning, transition, and stem-rendering candidates
    documented for future specs.
  - Add a research-gate note summarizing the decision basis.
  - Research-gate refinement note:
    - Requirements now lock the first implementation wave to
      `current-autodj-signal`, `essentia-rhythm`, `beat-this`, and
      `all-in-one` for timing, plus `all-in-one` and `songformer` for semantic
      sections unless later evidence amends the spec.
    - Design now defines backend isolation, optional dependency behavior,
      candidate provenance, timeline normalization, benchmark status, and the
      conservative DJ section label mapping policy.
    - This task list now splits candidate work into separate bounded tasks so
      failed optional libraries cannot destabilize the incumbent analyzer.
    - No production code changed in this task, so no unit tests were added;
      validation is limited to spec-document checks.
  - _Requirements: 1.5, 2.1, 2.2, 2.3, 6.2, 7.1, 7.4_

- [x] 3. Add backend contracts for tempo, beatgrid, and sections
  - Introduce small internal interfaces or protocols for tempo, beatgrid, and
    section analysis.
  - Add shared result/provenance structures for backend name, model details,
    parameters, dependency versions, processing time, warnings, and structured
    errors.
  - Add an `AnalysisContext` or equivalent that carries source path, decoded
    analysis audio path, duration, and ffprobe/start-time metadata.
  - Add backend registry or selection helpers that avoid candidate-specific
    conditionals in batch orchestration.
  - Keep optional dependency imports out of top-level package imports.
  - Add tests proving orchestration can swap backend implementations without
    feature-specific conditionals and that unavailable backends fail
    structurally.
  - Implementation note:
    - Added `autodj_analysis.backends` with tempo, beatgrid, and section
      protocols; shared `AnalysisContext`, `FeatureBundle`,
      `CandidateProvenance`, candidate result dataclasses, beat/section shapes,
      structured backend errors, and a named backend registry.
    - The new backend contract package imports only stdlib and existing worker
      modules, so exploratory candidate libraries remain optional and are not
      imported at package import time.
    - Added `test_backends.py` coverage for registry swapping, structured
      missing/duplicate registry errors, optional-dependency unavailable
      results, serialization shape, and validation failures.
    - Verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`
  - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6, 2.7, 2.8, 8.1, 8.6_

- [x] 4. Add Rekordbox ground-truth evaluation harness
  - Use the existing Rekordbox XML parser or extend it as needed.
  - Add benchmark code that compares candidate outputs against Rekordbox XML.
  - Report BPM error, first-beat offset, median beat error, high-percentile
    beat error, cue-adjacent drift, section/cue boundary error where mappable,
    and processing time.
  - Normalize MP3/WAV timeline behavior through decoded WAV input or a single
    explicit offset policy.
  - Preserve candidate downbeat/bar outputs in reports even if they are not the
    primary scoring metric.
  - Ensure benchmark outputs can be written to ignored local paths.
  - Add tests with synthetic or fixture-style XML data; do not commit real
    songs or user Rekordbox exports.
  - Implementation note:
    - Added `autodj_analysis.evaluation` with a Rekordbox ground-truth report
      harness that consumes analyzed-track JSON plus the existing Rekordbox XML
      parser.
    - Reports now include candidate status/provenance summary, BPM and
      normalized BPM error, first-beat offset, median and p95 nearest-beat
      error, cue-adjacent drift, cue boundary errors, section boundary errors,
      downbeat preservation, processing time, and explicit timeline-offset
      policy metadata.
    - Added `autodj-analysis evaluate-rekordbox` so benchmark reports can be
      written to ignored local paths without committing media or XML exports.
    - Added synthetic XML/artifact tests for metric accuracy, timeline offset
      normalization, missing candidate boundaries, report writing, and CLI
      execution.
    - Verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 3.7, 3.8, 8.4_

- [x] 5. Wrap current AutoDJ signal backend as incumbent
  - Adapt the current tempo, beatgrid, waveform/debug metadata, and weak
    section behavior to the contracts from task 3.
  - Preserve the existing `AnalyzedTrack`, `waveform.json`, and
    `debug-waveform.json` artifact shapes.
  - Record incumbent provenance and parameters in candidate results.
  - Add regression tests proving current artifact composition still works
    through the backend contract.
  - Implementation note:
    - Added `autodj_analysis.backends.current_signal` as the incumbent
      `current-autodj-signal` adapter for tempo, beatgrid, semantic-section,
      waveform, and debug-waveform behavior.
    - Routed the default batch `analyze_track_signal` path through the
      incumbent backend while preserving existing `AnalyzedTrack`,
      `waveform.json`, and `debug-waveform.json` artifact shapes.
    - Candidate contract results now record incumbent backend/model
      provenance, dependency versions where installed, parameters,
      processing time, warnings, and structured unavailable/failure errors.
    - Added regression coverage for contract conversion, structured
      unavailable behavior, section feature handoff, debug waveform shape,
      backend registry registration, and legacy artifact composition through
      the backend adapter.
    - Verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`
  - _Requirements: 2.1, 2.2, 2.3, 2.5, 5.1, 5.5_

- [x] 6. Add `essentia-rhythm` timing candidate
  - Implement `essentia-rhythm` behind the tempo and beatgrid contracts.
  - Record Essentia dependency version, algorithm parameters, license notes,
    processing time, and unavailable/error status.
  - Keep the backend optional so missing Essentia does not break package import
    or incumbent analysis.
  - Add tests for unavailable behavior and any pure mapping/scoring logic.
  - Implementation note:
    - Added `autodj_analysis.backends.essentia_rhythm` with an optional
      `essentia-rhythm` tempo and beat-grid backend built around Essentia
      `RhythmExtractor2013`.
    - The adapter imports Essentia only at execution time, resamples to the
      configured 44.1 kHz analysis rate when needed, normalizes BPM into the
      existing dubstep tempo model, maps Essentia ticks into beat markers, and
      leaves downbeats empty with an explicit warning.
    - Candidate provenance records backend/model identity, Essentia and NumPy
      versions where available, method/sample-rate/tempo-range parameters,
      raw confidence, estimate/interval counts, processing time, and the
      AGPL/commercial licensing note.
    - Added structured unavailable and failed behavior so missing Essentia,
      import errors, or invalid runtime output do not affect package import or
      the incumbent analyzer.
    - Added tests for runtime dependency loading, feature-to-contract mapping,
      unavailable dependency serialization, beat-grid precondition handling,
      and registry registration.
    - Verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`
  - _Requirements: 2.1, 2.2, 2.6, 2.7, 5.1, 5.6, 8.6_

- [x] 7. Spike `beat-this` timing candidate
  - Install or probe `beat-this` in the WSL analysis environment.
  - Implement it behind the beatgrid contract when package/model access works.
  - Capture beat, downbeat, model, dependency, CPU/GPU, and processing-time
    provenance.
  - Prefer packaged inference first; avoid DBN/madmom mode unless a benchmark
    shows it is needed.
  - Add tests for adapter shape and structured unavailable behavior.
  - Implementation note:
    - Installed `beat-this==1.1.0` into `.venv-analysis` with the CUDA-enabled
      PyTorch/Torchaudio stack now present in WSL.
    - Ran a real backend smoke through the packaged `Audio2Beats` model on
      CUDA. It produced beat and downbeat output, so this is benchmark-eligible
      for the timing lane.
    - Added `autodj_analysis.backends.beat_this_backend` with an optional
      `beat-this` beat-grid backend using the packaged `Audio2Beats` API on
      already-decoded analysis samples.
    - The backend records checkpoint/model name, requested/effective device,
      CUDA availability, DBN and float16 settings, model-load time, inference
      time, dependency versions where installed, downbeats, beat counts, and a
      model/license review warning.
    - The default adapter keeps DBN disabled to avoid the extra madmom risk,
      and it does not register as a tempo backend because Beat This emits beats
      and downbeats, not a BPM estimate.
    - Added a dedicated optional `beat-this` package extra instead of making
      the heavy dependency part of the default or broad candidate extras.
    - Added tests for runtime dependency loading, auto CPU/GPU device
      selection, prediction-to-contract mapping, structured unavailable
      behavior, runtime failure serialization, and registry registration.
    - Current real smoke status:
      `beatCount=10`, `downbeatCount=6`, `effectiveDevice=cuda`,
      `beat-this=1.1.0`, `torch=2.12.0`, `torchaudio=2.11.0`.
    - Verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`
  - _Requirements: 2.2, 2.6, 2.7, 3.7, 5.1, 5.6, 8.6_

- [x] 8. Spike `all-in-one` timing and section candidate
  - Adaptive outcome: All-In-One is operational for timing and semantic
    sections on real music in this environment.
  - Install or probe `all-in-one` in the WSL analysis environment.
  - Implement timing outputs behind tempo/beatgrid contracts when practical.
  - Implement functional segment boundaries/labels behind the section contract.
  - Record NATTEN, madmom, FFmpeg, model, MP3/WAV timeline, and processing
    behavior.
  - Add tests for adapter mapping, label conversion, and unavailable behavior.
  - Implementation note:
    - Installed and smoke-tested the real `allin1==1.1.0` runtime in
      `.venv-analysis`, including Demucs, CPJKU `madmom`, CUDA-enabled
      PyTorch/Torchaudio, TorchCodec, and a locally built `natten==0.21.6`.
    - NATTEN `0.14.6` exposes the legacy API expected by All-In-One but does
      not compile cleanly against the local PyTorch 2.12 stack, so the adapter
      installs a small compatibility shim over NATTEN `0.21.6` before importing
      All-In-One.
    - The local NATTEN `0.21.6` source build also needed CUDA 13 build wheels
      plus venv-local CUDA library symlinks so CMake could resolve `cudart`.
      Treat this as an operational setup requirement, not a hidden benchmark
      assumption.
    - The real smoke executes Demucs, spectrogram extraction, and model
      inference successfully for functional sections.
    - The first synthetic click-fixture smoke emitted sections but no beats;
      that is an invalid capability test for timing. A real-song smoke on
      `BackspinBass.mp3` emitted `bpm=140.0`, `beatCount=273`, and
      `downbeatCount=69`, so All-In-One is benchmark-eligible for timing.
    - Added `autodj_analysis.backends.all_in_one_backend` with an optional
      `all-in-one` section adapter around the documented `allin1.analyze()`
      Python API.
    - The adapter records model, requested/effective device, CUDA availability,
      FFmpeg availability/path, MP3/WAV timeline mode, byproduct directories,
      dependency availability/versions, processing time, and license/timeline
      warnings.
    - The adapter prefers `AnalysisContext.analysis_audio_path` for timeline
      consistency because upstream documents MP3 decoder offset risk; source
      MP3 mode is still supported but warned.
    - Functional labels are mapped conservatively: `intro`, `verse`, `break`,
      and `outro` pass through, while `chorus`, `bridge`, `inst`, `solo`,
      `start`, and `end` become `unknown` until energy/bass/phrase evidence can
      promote them in a later label-policy task.
    - Added a dedicated optional `all-in-one` package extra and tests for API
      mapping, cached runner behavior, source-MP3 timeline warnings,
      structured unavailable behavior, runtime failure serialization, label
      conversion, unsupported timing output, and registry registration.
    - Added spike details to
      `.codex/specs/005-adaptive-mir-candidate-evaluation/research-dossier.md`.
    - Current real smoke status:
      synthetic fixture: `sectionStatus=ok`, `sectionCount=2`,
      `tempoStatus=failed` with `all_in_one_missing_bpm`,
      `beatGridStatus=failed` with `all_in_one_missing_beats`.
    - Current real-song smoke status on `BackspinBass.mp3`:
      `tempoStatus=ok`, `bpm=140.0`, `beatGridStatus=ok`, `beatCount=273`,
      `downbeatCount=69`, `sectionStatus=ok`, `sectionCount=9`,
      `allin1=1.1.0`, `demucs=4.0.1`, `madmom=0.17.dev0`,
      `natten=0.21.6`, `torch=2.12.0+cu130`.
    - Verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`
  - _Requirements: 2.1, 2.2, 2.3, 2.6, 2.7, 3.6, 5.6, 6.2, 6.6, 8.6_

- [x] 9. Spike `songformer` availability for semantic sections
  - Verify repository/package path, model weights, license/model terms, and a
    minimal inference path if available.
  - If available, implement a section backend adapter and record provenance.
  - If unavailable or unclear, document the exact blocker and continue without
    blocking timing work.
  - Add tests for adapter shape or structured unavailable behavior.
  - Implementation note:
    - Researched primary sources for SongFormer: arXiv paper, official GitHub
      repository, Hugging Face model card, repository requirements, and
      repository license.
    - Confirmed the model/code are public, but there is no normal PyPI package:
      `python -m pip index versions songformer` returned no matching
      distribution.
    - Installed the runtime stack that is available from package indexes:
      `transformers==4.51.3`, `huggingface-hub==0.30.2`, CUDA-enabled
      PyTorch/Torchaudio, TorchVision, TorchCodec, `muq`, `msaf`,
      `ema-pytorch`, `x-transformers`, and related dependencies.
    - Official install path is a GitHub checkout with submodules, Python 3.10
      conda environment, `pip install -r requirements.txt`, checkpoint/model
      downloads from Hugging Face, and `trust_remote_code=True` loading through
      `transformers.AutoModel`.
    - Downloaded the official Hugging Face model snapshot and smoke-tested the
      documented custom-code inference path with `trust_remote_code=True`.
    - Added a SciPy compatibility shim for `msaf`, which still expects
      `scipy.inf` on modern SciPy.
    - Pinned Transformers/Hugging Face dependencies to the version range that
      loads the official model on this machine. Newer Transformers 5.x failed
      during model load with a meta-device tensor error.
    - Added `autodj_analysis.backends.songformer_backend` as an optional
      semantic-section backend adapter. It supports injected runners for tests
      and the documented Hugging Face custom-code inference path for real
      execution.
    - The adapter records repo/revision/local model directory, requested and
      effective device, CUDA availability, expected 24 kHz model sample rate,
      model-load/inference timing, dependency versions/availability,
      `trust_remote_code`, and license/install notes.
    - The backend registers only as a section backend because SongFormer emits
      functional segment boundaries/labels, not BPM, beatgrid, or cue points.
    - Label mapping remains conservative: direct `intro`, `verse`, `build`,
      `break`/`breakdown`, and `outro` pass through, while `chorus`, `bridge`,
      `inst`, `instrumental`, `pre-chorus`, `silence`, and `solo` map to
      `unknown` until a later evidence layer can promote them.
    - Added a dedicated optional `songformer` extra for the public runtime
      dependencies that can be installed from package indexes; the Hugging Face
      custom-code model snapshot is downloaded at runtime/cache time.
    - Added tests for runner mapping, cached prediction behavior, source
      timeline warning, structured unavailable dependency behavior, runtime
      failure serialization, label conversion, and registry registration.
    - Added spike details to
      `.codex/specs/005-adaptive-mir-candidate-evaluation/research-dossier.md`.
    - Current real smoke status:
      `sectionStatus=ok`, `sectionCount=1`, `sourceLabels=["verse"]`,
      `transformers=4.51.3`, `huggingface-hub=0.30.2`, `torch=2.12.0`,
      `muq=0.1.0`, `msaf=0.1.80`.
    - Verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python"`
  - _Requirements: 2.3, 2.6, 2.7, 6.2, 6.3, 6.7, 8.6_

- [x] 10. Benchmark first-wave timing candidates against Rekordbox XML
  - Run `current-autodj-signal`, `essentia-rhythm`, `beat-this`, and
    `all-in-one` timing outputs.
  - Use the known local songs and Rekordbox exports without committing media or
    generated artifacts.
  - Report BPM error, first-beat offset, median beat error, 95th percentile
    beat error, cue-adjacent drift, downbeat/bar notes, processing time,
    dependency/model load time, and candidate status.
  - Generate viewer-ready artifacts for each plausible candidate.
  - Implementation notes:
    - Added `autodj-analysis benchmark-timing` and reusable benchmark runner
      code under `autodj_analysis.evaluation.timing_benchmark`.
    - Added benchmark tests for summary/artifact generation, beat-only BPM
      derivation, unavailable-candidate reporting, case loading, and CLI
      wiring.
    - Fixed the Essentia runtime configuration so `RhythmExtractor2013`
      receives integer tempo bounds and runs successfully in the timing lane.
    - Generated ignored local benchmark artifacts at
      `.autodj-cache/timing-benchmark/run-2026-05-17`.
    - All four first-wave candidates ran against BackspinBass, headache,
      VERTIGO, and new-feelings with Rekordbox XML references.
    - Aggregate result snapshot:
      `current-autodj-signal ok=4 medianBeatMs=13.5 p95BeatMs=13.5 bpmError=0.0 processingSeconds=32.914254`;
      `essentia-rhythm ok=4 medianBeatMs=22.67425 p95BeatMs=90.7129 bpmError=0.115646 processingSeconds=11.10169`;
      `beat-this ok=4 medianBeatMs=13.054 p95BeatMs=54.2777 derivedBpmError=37.934461 processingSeconds=16.925067`;
      `all-in-one ok=4 medianBeatMs=23.6115 p95BeatMs=41.439 bpmError=0.0 processingSeconds=198.72792`.
    - Caveats before selection: `beat-this` is beat-only in this integration,
      so its BPM is derived from emitted beat intervals and should not be
      treated as a native tempo estimate; `all-in-one` is much slower than the
      other timing candidates; manual waveform/listening inspection remains
      required before backend selection.
    - Verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python/tests"`
  - _Requirements: 3.1, 3.2, 3.4, 3.6, 3.7, 3.8, 5.1, 5.3, 5.7_

- [x] 11. Manual checkpoint: BPM and beatgrid verdict
  - STOP: Ask the user to inspect the generated candidate artifacts in
    `tools/analysis-debug-viewer.html` and/or Rekordbox.
  - Record the user verdict, inspected songs, accepted candidate, rejected
    candidates, and any visual/listening caveats under this task.
  - Do not perform final BPM/beatgrid selection until this verdict is recorded.
  - Verdict notes:
    - User manually inspected the Task 10 artifacts in the debug viewer against
      Rekordbox XML exports and agreed with the benchmark interpretation.
    - Inspected songs/artifacts: BackspinBass, headache, VERTIGO, and
      new-feelings under `.autodj-cache/timing-benchmark/run-2026-05-17`.
    - Accepted timing backend: `current-autodj-signal` for both BPM and
      beatgrid.
    - Rejected timing replacements:
      `all-in-one` had comparable BPM on most songs but sparse/late beat grids
      and high runtime; `beat-this` placed some emitted beats close to
      Rekordbox but emitted incomplete/sparse grids and no native BPM;
      `essentia-rhythm` was fast but less accurate in phase/beat alignment and
      carries AGPL/commercial-license review risk.
    - Visual caveat: canvas alignment bugs from Spec 004 made very small offsets
      hard to judge visually at first, so final interpretation used Rekordbox
      XML metrics plus manual viewer/listening judgment.
    - Post-verdict metric caveat: nearest candidate-beat median error can make
      sparse outputs look better than a complete beat grid. Beat coverage and
      reference-beat recall must be considered for future timing comparisons.
  - _Requirements: 4.1, 4.2, 4.3, 5.2, 5.7_

- [x] 12. Select and integrate BPM/beatgrid backend
  - Compare incumbent and candidate metrics against Rekordbox XML plus the
    manual verdict from task 11.
  - Include processing time, install friction, license risk, platform risk, and
    fallback behavior.
  - Integrate the selected backend into default artifact generation.
  - Document selected parameters, confidence behavior, limitations, and
    fallback path.
  - Add regression tests for selected backend orchestration and artifact
    compatibility.
  - Selection notes:
    - Selected backend: `current-autodj-signal`.
    - Integration status: already the default `analyze-batch` artifact path via
      `analyze_track_signal` and `CurrentSignalBackend`; no default behavior
      change was needed.
    - Parameters/provenance: `electronic_quantized_grid` timing stack,
      tempo hop length `512`, normalized electronic-music BPM handling for
      halftime/doubletime cases, backend/model provenance recorded in candidate
      contract outputs and legacy artifacts.
    - Confidence behavior: tempo and beat-grid confidence are emitted from the
      current signal analyzer; low-confidence or unavailable dependencies
      produce structured warnings/errors instead of silently switching to a
      weaker optional candidate.
    - Limitations: downbeats remain intentionally empty until defensible
      evidence exists; raw BPM can be halftime while `normalizedBpm` is the
      DJ-facing tempo; semantic sections remain weak and are handled by later
      tasks.
    - Fallback path: retain `essentia-rhythm`, `beat-this`, and `all-in-one` as
      explicit comparison/experimental backends only. Do not auto-fallback from
      selected timing to them for production artifacts.
    - Operational comparison: `current-autodj-signal` matched normalized BPM and
      beat count on all four known songs and had complete reference-beat recall;
      `all-in-one` was much slower, `beat-this` lacked native BPM and emitted
      sparse grids, and `essentia-rhythm` was fast but less accurate and has
      licensing risk.
    - Added evaluator metrics for beat coverage, reference-beat recall, and
      candidate precision so future benchmark summaries expose sparse-grid
      failure modes.
    - Added regression coverage that the default track signal analyzer routes
      through the selected `CurrentSignalBackend`, plus sparse-grid evaluator
      tests proving median nearest-beat error alone is insufficient.
    - Verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python/tests/test_rekordbox_evaluation.py analysis/worker-python/tests/test_timing_benchmark.py analysis/worker-python/tests/test_current_signal_backend.py"`
  - _Requirements: 4.3, 5.2, 5.3, 5.4, 5.5, 5.6, 7.3, 8.1_

- [x] 13. Define and test semantic section label policy
  - Implement the project section vocabulary: `intro`, `verse`, `build`,
    `drop`, `break`, `outro`, and `unknown`.
  - Implement conservative mapping helpers for pop-form labels emitted by
    candidates such as `all-in-one` or `songformer`.
  - Require supporting evidence before promoting `chorus` to `drop` or
    `bridge`/`instrumental` to `build`/`break`.
  - Add unit tests for mapping rules, confidence downgrades, and unknown/fallback
    behavior.
  - Implementation notes:
    - Added shared `autodj_analysis.section_labels` policy with
      `PROJECT_SECTION_LABELS`, `SectionMappingEvidence`,
      `SectionLabelMapping`, `normalize_section_label`, and
      `map_section_label`.
    - Canonical vocabulary is `intro`, `verse`, `build`, `drop`, `break`,
      `outro`, and `unknown`; repeated drops are represented as ordered `drop`
      sections/IDs rather than labels like `drop1`.
    - `breakdown` and `break/verse` normalize to canonical `break`.
    - Pop-form labels such as `chorus`, `hook`, and `refrain` remain
      low-confidence `unknown` unless energy, bass, onset, and phrase evidence
      supports promotion to `drop`.
    - Contextual labels such as `pre-chorus`, `pre-drop`, `bridge`,
      `instrumental`, and `solo` require energy-slope evidence before promotion
      to `build` or low-energy evidence before promotion to `break`.
    - Updated `songformer` and `all-in-one` adapters to use the shared mapping
      policy instead of duplicated backend-local rules.
    - Recorded future transition-analysis guidance in steering:
      second-build drop swaps, vocal/acapella predrop layering with loop
      tightening, drop chopping, and frequency-complement drop doubles.
    - Verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python/tests/test_section_labels.py analysis/worker-python/tests/test_songformer_backend.py analysis/worker-python/tests/test_all_in_one_backend.py"`
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.6, 6.8, 8.1_

- [x] 14. Benchmark first-wave semantic section candidates
  - Run `all-in-one`, `songformer` if available, and the current heuristic
    fallback on known songs.
  - Compare boundaries to Rekordbox cues where mappable and record missed drops,
    false positive drops, confidence behavior, and processing time.
  - Generate viewer-ready artifacts with candidate section overlays.
  - Keep the heuristic labeler as a weak fallback only unless evidence and user
    verdict say otherwise.
  - Implementation notes:
    - Added multi-track Rekordbox XML loading through `load_rekordbox_tracks`
      so one export can contain all four labeled known-song cases.
    - Added `autodj-analysis benchmark-sections`, backed by the new semantic
      benchmark runner, to derive reference sections from Rekordbox cue names
      like `intro_start`, `build_1_start`, `drop_1_start`, and `drop_1_end`.
    - Generated viewer-ready `analyzed-track.json` and `debug-waveform.json`
      artifacts plus per-candidate `section-evaluation.json` files under:
      `.autodj-cache/semantic-section-benchmark/run-2026-05-18`.
    - Ran the benchmark against
      `C:\Users\Brendan\Desktop\all_songs.xml`, which includes BackspinBass,
      headache, VERTIGO, and new-feelings.
    - All three candidates ran successfully on all four tracks:
      `current-autodj-signal`, `all-in-one`, and `songformer`.
    - Aggregate section results:
      `current-autodj-signal` matched 11 sections, missed 13 references, had
      3 false positives, missed 2 drops, had 1 false positive drop, and median
      start/end errors of 6843 ms / 5714 ms.
      `all-in-one` matched 7 sections, missed 17 references, had 9 false
      positives, missed 7 drops, had 0 false positive drops, and median
      start/end errors of 37 ms / 7033 ms.
      `songformer` matched 8 sections, missed 16 references, had 11 false
      positives, missed 7 drops, had 0 false positive drops, and median
      start/end errors of 100 ms / 5131 ms.
    - Processing totals were about 0.002 seconds for the current heuristic,
      250 seconds for All-In-One, and 79 seconds for SongFormer.
    - Outcome: none of the section candidates is ready to select as-is.
      All-In-One and SongFormer can find some broad functional boundaries but
      miss most Rekordbox-labeled drops under the conservative section mapping.
      The current heuristic detects some drops but has poor section boundaries
      and remains only a weak fallback.
    - Next gate is task 15: user manual inspection in the HTML viewer before
      any section backend is selected or integrated.
    - Verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python/tests/test_semantic_benchmark.py analysis/worker-python/tests/test_cli.py analysis/worker-python/tests/test_rekordbox_xml.py analysis/worker-python/tests/test_section_labels.py analysis/worker-python/tests/test_songformer_backend.py analysis/worker-python/tests/test_all_in_one_backend.py"`
    - Real benchmark command:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && autodj-analysis benchmark-sections /mnt/c/Users/Brendan/Desktop/all_songs.xml --out .autodj-cache/semantic-section-benchmark/run-2026-05-18 --json"`
  - _Requirements: 3.3, 4.1, 6.1, 6.2, 6.3, 6.4, 6.5, 6.8_

- [x] 15. Manual checkpoint: semantic section verdict
  - STOP: Ask the user to inspect section boundaries and labels in generated
    artifacts.
  - Record the user verdict, accepted labels, rejected labels, inspected songs,
    and examples under this task.
  - Do not finalize section selection until this verdict is recorded.
  - Partial manual note, 2026-05-18:
    - User inspected All-In-One section overlays and reported that the markers
      often line up with musically meaningful dubstep sections such as verse,
      build, and drop, but the labels are wrong or too generic
      (`verse`/`unknown`) because All-In-One emits pop-form labels.
    - User reported that SongFormer JSON artifacts were not visible during
      manual testing; follow-up found that the files exist under each per-track
      `songformer` directory, so manual SongFormer inspection remains pending.
    - User later inspected SongFormer and reported that it performed about as
      well as All-In-One: useful markers at energy/structure changes, but the
      same label gap where builds/drops are emitted as pop-form or unknown
      section labels instead of DJ labels.
    - Product strategy note: treat All-In-One as a promising boundary/anchor
      candidate, and treat SongFormer similarly, not as final labelers. The
      next semantic attempt should use the selected AutoDJ BPM/beatgrid plus
      candidate boundaries and dubstep phrase heuristics. Drop-start
      identification is the key anchor; likely build starts are 4, 8, 16, or
      32 bars before the drop, and likely drop ends are phrase lengths after
      the drop start, followed by a break/verse region.
    - Follow-up experiment, 2026-05-18: added `dubstep-phrase-hybrid`, which
      fuses All-In-One unlocked boundaries, SongFormer boundaries, selected
      AutoDJ beatgrid timing, energy jump, bass energy, onset density, and
      phrase-position heuristics. It snaps boundaries to bars, treats 1-8 bar
      low-energy gaps inside a drop as dubstep turnarounds instead of second
      drops, infers builds backward by 4/8/16/32 bars, and infers drop ends
      from phrase-length plus sustained energy/bass fall evidence.
    - Real artifact runs:
      `.autodj-cache/semantic-section-benchmark/run-2026-05-18-hybrid-v2`
      contains standalone `all-in-one-unlocked`, standalone `songformer`, and
      hybrid comparison artifacts. After tightening the turnaround/exit anchor
      filter, `.autodj-cache/semantic-section-benchmark/run-2026-05-18-hybrid-v3`
      contains final hybrid-only artifacts for viewer inspection.
    - v3 aggregate: `dubstep-phrase-hybrid` ran successfully on all 4 songs,
      matched 19 sections, missed 5 references, had 5 false positives, missed
      0 drops, had 0 false-positive drops, and had median start/end errors of
      about 14 ms against Rekordbox. Remaining misses are mainly coarse
      `intro`/`verse`/`break` label granularity, not drop/build timing.
    - Focused failure-tuning follow-up, 2026-05-19: after BPM quantization,
      full-period beatgrid phase search, span-capped drop grouping, and
      conservative drop-entry anchor preference, the focused 10-track benchmark
      output under
      `.autodj-cache/semantic-section-benchmark/focused-failure-tuning/run-after-span-capped-grouping`
      matched 23 sections, missed 33 references, had 39 false positives,
      missed 8 drops, had 6 false-positive drops, and had median start/end
      errors of about 31 ms / 52 ms. This is not production-perfect section
      labeling, but it is materially better than the prior focused passes and
      generally exposes at least one useful `build -> drop` pair on most
      tested songs.
    - User verdict, 2026-05-19: the latest artifacts look substantially better.
      Most songs catch at least one correct build/drop pair, which is sufficient
      for the near-term POC because the DJ can transition into or away from a
      song without needing every drop in the song to be perfectly labeled.
      Known misses remain acceptable for this gate: `HARDEST MFS` likely fails
      because the waveform is close to a brick of sound, and `This Way` still
      treats a large inter-drop break as a turnaround in one case. These should
      be handled later by confidence-aware mixing strategy and fallback rules
      rather than more overfitted section-threshold tuning now.
    - Debugger/manual-review support was updated in
      `tools/analysis-debug-viewer.html`: beat/bar/cue markers now draw with a
      light halo over the RGB waveform, and semantic section bands are colored
      by section type. Benchmark candidate folders now include
      `source-audio.mp3` beside `analyzed-track.json` and
      `debug-waveform.json` for easier drag-and-drop playback review.
    - Runbook update, 2026-05-19:
      `.codex/specs/005-adaptive-mir-candidate-evaluation/large-set-semantic-benchmark-runbook.md`
      now documents the current algorithm notes, copied source-audio artifact,
      manual-inspection workflow, quick failure-filter PowerShell snippet, and
      the truth boundary: Rekordbox XML is used for source paths and
      post-inference comparison only, not leaked into candidate generation.
    - Final task-15 outcome: select `dubstep-phrase-hybrid` as the semantic
      section candidate to carry forward into integration, with honest
      low/experimental confidence and known limitations around dense
      brick-wall tracks, light/non-standard dubstep, and long inter-drop breaks.
  - _Requirements: 4.1, 4.2, 4.3, 6.2, 6.5_

- [x] 16. Integrate selected semantic section backend
  - Integrate the selected section backend into artifact generation.
  - Keep confidence honest and warnings explicit.
  - Preserve debug viewer compatibility.
  - Add tests for contract shape, fallback behavior, and representative section
    mappings.
  - Completion notes, 2026-05-19:
    - Integrated selected semantic backend `dubstep-phrase-hybrid` into the
      normal `analyze-batch` artifact path. `SignalAnalysisResult` now carries
      an optional `SectionCandidateResult`, and `build_analyzed_track_artifact`
      prefers that selected result for `sections` and `cuePoints` while keeping
      the existing artifact/debug-viewer shapes.
    - Added `--section-backend` to `autodj-analysis analyze-batch`. The default
      is `dubstep-phrase-hybrid`; `current-autodj-signal` remains available as
      an explicit rough-section fallback path.
    - Normal artifact generation writes a per-track normalized
      `section-backend-work/analysis.wav` for semantic models when possible.
      If the selected backend cannot be constructed, fails, or emits no usable
      sections, artifact generation falls back to `current-autodj-signal`
      rough sections and records the reason in `quality.warnings`.
    - Updated the default parameters hash to invalidate stale section artifacts:
      `sha256:signal-v2-waveform-energy-tempo-dubstep-phrase-hybrid-v1`.
    - Updated the analyzed-track schema enum to allow the project section label
      `break`, matching the semantic section vocabulary used by the selected
      backend and viewer.
    - Added regression coverage for selected-section artifact mapping,
      fallback-to-current behavior, CLI help, the `break` contract label, and
      the current-signal explicit fallback path.
    - Verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python/tests/test_batch.py analysis/worker-python/tests/test_cli.py analysis/worker-python/tests/test_contract_shape.py analysis/worker-python/tests/test_dubstep_phrase_hybrid.py analysis/worker-python/tests/test_semantic_benchmark.py -q"`
      -> 40 passed.
    - Also verified with:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python/tests/test_features.py analysis/worker-python/tests/test_structure.py analysis/worker-python/tests/test_tempo.py analysis/worker-python/tests/test_current_signal_backend.py analysis/worker-python/tests/test_backends.py -q"`
      -> 37 passed.
    - Syntax verification:
      `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m compileall -q analysis/worker-python/src/autodj_analysis"`
      -> passed.
  - _Requirements: 2.3, 2.5, 6.2, 6.3, 6.4, 6.5, 8.1_

- [x] 17. Document deferred candidates and future specs
  - Summarize candidates deferred for stem separation, set planning, transition
    techniques, hosted providers, embeddings, and native/mobile work.
  - Add enough source/context detail that future specs do not need to repeat
    the full research pass.
  - Update roadmap or steering docs if the future path changed.
  - Completion notes, 2026-05-19:
    - Added
      `.codex/specs/005-adaptive-mir-candidate-evaluation/deferred-candidates-and-future-specs.md`
      as the future-spec handoff document. It records the selected Spec 005
      baseline (`current-autodj-signal` timing and `dubstep-phrase-hybrid`
      sections), then organizes deferred work by section/cue ranking, stem
      separation, set planning/embeddings, transition techniques, hosted
      providers, native/mobile analysis, and deferred timing alternatives.
    - The handoff records why each candidate was deferred, when it should be
      reopened, likely future role, and primary source pointers where the
      dossier already captured them.
    - Updated `research-dossier.md` so future agents start from the new
      deferred-candidates handoff before repeating research.
    - Updated `.codex/steering/09-roadmap.md` to reflect the Spec 005 selected
      analysis paths and to place deferred candidates into later roadmap
      phases for stems, set planning, transition generation, section cleanup,
      and native/mobile feasibility.
    - Documentation-only task; no code, schema, runtime behavior, or benchmark
      script changed. Per Requirement 8.7, no unit tests were added.
  - _Requirements: 1.4, 7.4, 7.5_

- [x] 18. Update README and steering with selected approach
  - Update README analysis status and setup notes as needed.
  - Update steering docs for selected BPM/beatgrid and section-analysis
    direction.
  - Record any new dependency, licensing, platform, or runtime constraints.
  - Completion notes, 2026-05-19:
    - Updated `README.md` current status to record Spec 005's selected
      analysis stack: `current-autodj-signal` for BPM/beatgrid and
      `dubstep-phrase-hybrid` for semantic sections, with the old rough section
      heuristic retained only as fallback.
    - Updated README analysis commands and setup notes to describe the default
      `analyze-batch` semantic backend, the explicit
      `--section-backend current-autodj-signal` smoke-test fallback, the full
      WSL extras needed for selected semantic sections
      (`analysis-wsl`, `all-in-one`, `songformer`), and the benchmark runbook
      for Rekordbox/manual-viewer comparison.
    - Updated `.codex/steering/README.md` core decisions so future agents see
      the selected timing/section paths before editing analysis or DJ strategy.
    - Updated `.codex/steering/03-tech-stack.md` to replace broad exploratory
      candidate language with the selected timing/section stack, comparison-only
      candidates, WSL/Python 3.11 runtime expectation, heavy optional
      dependency isolation, and licensing/productization caveats for All-In-One,
      SongFormer, FFmpeg-related behavior, and optional future stem/provider
      systems.
    - Updated `.codex/steering/07-analysis-pipeline.md` to document
      `dubstep-phrase-hybrid` as the default section backend, its boundary and
      phrase-evidence strategy, fallback behavior, cache/debug artifact layout,
      and the Rekordbox truth boundary.
    - Documentation-only task; no code, schema, runtime behavior, or benchmark
      script changed. Per Requirement 8.7, no unit tests were added.
  - _Requirements: 7.2, 7.3, 7.5_

- [x] 19. Run full verification and close adaptive gates
  - Run relevant WSL Python tests.
  - Run viewer syntax verification if the viewer changed.
  - Run CMake configure/build/CTest if native contracts or repository behavior
    changed.
  - Confirm research, benchmark, and manual-verdict gates have notes in this
    file.
  - Confirm all generated local artifacts remain outside git.
  - Completion notes, 2026-05-19:
    - Reviewed the spec overview, `requirements.md`, and `design.md` before
      closing this task. Requirement 8 requires WSL Python verification, viewer
      syntax verification when touched, native configure/build/CTest when
      contract or repository surfaces changed, runnable benchmarks without
      committed real music, and exact manual-verdict artifact notes.
    - Research gate notes are present in tasks 1-2 and
      `research-dossier.md`, including candidate survey results, installability,
      licensing/platform notes, and the future-spec backlog.
    - Benchmark gate notes are present in tasks 10 and 14, with timing and
      semantic benchmark commands, metrics, generated ignored artifact paths,
      and candidate eligibility caveats.
    - Manual verdict gate notes are present in task 11 for BPM/beatgrid and
      task 15 for semantic sections. The inspected artifact folders and user
      verdicts are recorded under those tasks.
    - Full WSL Python suite:
      `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python -q"`
      -> 219 passed, 9 warnings in about 148 seconds. Warnings were from
      optional/model dependencies and the generated-audio real-analysis path,
      not assertion failures.
    - Viewer syntax verification:
      `node -e "const fs=require('fs'); const html=fs.readFileSync('tools/analysis-debug-viewer.html','utf8'); const scripts=[...html.matchAll(/<script\\b[^>]*>([\\s\\S]*?)<\\/script>/gi)].map(m=>m[1]); for (const [i, script] of scripts.entries()) { try { new Function(script); } catch (error) { error.message = 'script #' + (i + 1) + ': ' + error.message; throw error; } } console.log('checked scripts:', scripts.length);"`
      -> checked scripts: 1.
    - Native configure/build:
      `cmake --preset debug` -> passed.
      `cmake --build --preset debug` -> passed.
    - Native CTest:
      first `ctest --preset debug` run reported 6/7 tests passed because
      `autodj_repository_boundaries` found generated local artifacts physically
      present under ignored `.autodj-cache/` and `local-audio/` folders. To
      verify the native suite without deleting review artifacts, those two
      ignored folders were temporarily moved outside the repo, the same CTest
      preset was rerun, and the folders were restored afterward. Clean native
      result: `ctest --preset debug` -> 7/7 tests passed.
    - Generated local artifact git status: normal
      `git status --short -- .autodj-cache local-audio` prints no tracked or
      untracked entries. `git status --ignored --short -- .autodj-cache local-audio`
      reports both folders as ignored, and `.gitignore` contains
      `.autodj-cache/` and `local-audio/`.
    - Residual local cleanup note: because the ignored generated review
      artifacts were restored, a future direct `ctest --preset debug` from the
      current workspace will trip the repository-boundary test again unless
      `.autodj-cache/` and `local-audio/` are temporarily moved or removed
      first. They remain outside git, but the native repository-boundary test
      checks physical workspace contents too.
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
