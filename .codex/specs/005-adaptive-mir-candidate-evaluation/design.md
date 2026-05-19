# Design Document

## Overview

Spec 005 moves analysis development from one-off heuristic improvements to an
evidence-driven candidate evaluation loop. The implementation should make BPM,
beatgrid, and section analysis polymorphic, then compare current and candidate
backends against Rekordbox XML and manual waveform/listening review.

The final selected implementation may still include simple deterministic
logic. The goal is not "use ML because it is ML"; the goal is to prove which
combination gives the best DJ-useful results at acceptable processing cost.

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

## Adaptive Spec Flow

```text
research-plan.md
  -> research dossier and candidate matrix
  -> interface/refactor design refinement
  -> candidate backend spike tasks
  -> Rekordbox benchmark reports
  -> user manual verdict checkpoint
  -> selected backend integration
  -> docs and steering updates
```

Later tasks may update this design after the research gate. That is expected.
Agents must record why the design changed and what evidence drove the change.

## Research Gate Outcome

The research gate selected a deliberately small first wave:

| Candidate | Role in this spec |
| --- | --- |
| `current-autodj-signal` | Incumbent BPM/beatgrid/debug baseline. This remains the backend to beat. |
| `essentia-rhythm` | Fast local/native-reference BPM and beat candidate. Useful for speed and portability comparison. |
| `beat-this` | Focused modern ML beat/downbeat candidate with a clean Python package path. |
| `all-in-one` | Joint BPM, beat, downbeat, boundary, and functional-section candidate. Heavy but operational on real music in this environment. |
| `songformer` | Semantic section candidate. The installed Hugging Face custom-code model path is operational for section analysis. |

Deferred systems remain in the dossier for future specs: stem separation,
set planning, transition generation, hosted providers, commercial native SDKs,
and lower-priority timing alternatives. Implementation tasks should not expand
the first wave unless this design is amended with new evidence.

## Backend Architecture

Prefer a small internal package layout like this unless the existing codebase
strongly points to a better local convention:

```text
analysis/worker-python/src/autodj_analysis/
  backends/
    base.py
    registry.py
    current_signal.py
    essentia_rhythm.py
    beat_this_backend.py
    all_in_one_backend.py
    songformer_backend.py
  evaluation/
    rekordbox_ground_truth.py
    metrics.py
    report.py
```

The concrete filenames can change. The architectural requirement is that
candidate-specific imports and execution logic stay isolated from batch
orchestration and artifact composition.

Heavy optional dependencies must not be imported at package import time. Each
candidate backend should perform dependency checks at execution time and return
a structured unavailable/error result when the dependency, model file, GPU
support, or executable is missing.

## Backend Interface Direction

The current modules should move toward contracts like:

```python
class TempoBackend(Protocol):
    name: str

    def analyze_tempo(self, audio: DecodedAudio, context: AnalysisContext) -> TempoCandidateResult:
        ...

class BeatGridBackend(Protocol):
    name: str

    def analyze_beat_grid(
        self,
        audio: DecodedAudio,
        tempo: TempoCandidateResult,
        context: AnalysisContext,
    ) -> BeatGridCandidateResult:
        ...

class SectionBackend(Protocol):
    name: str

    def analyze_sections(
        self,
        audio: DecodedAudio,
        features: FeatureBundle,
        beat_grid: BeatGridCandidateResult,
        context: AnalysisContext,
    ) -> SectionCandidateResult:
        ...
```

The exact names can change, but the design intent is fixed:

- backend results include provenance, confidence, warnings, parameters, and
  processing time;
- backend errors are structured and serializable;
- batch orchestration selects a backend by configuration or explicit argument;
- evaluation can run multiple backends over the same decoded audio and compare
  results without changing artifact composition;
- Rekordbox XML can be loaded as a reference result for scoring.

Suggested shared result components:

```python
@dataclass(frozen=True)
class AnalysisContext:
    track_id: str
    source_path: Path
    duration_seconds: float
    analysis_audio_path: Path
    ffprobe_start_time_seconds: float | None
    temp_dir: Path

@dataclass(frozen=True)
class CandidateProvenance:
    backend_name: str
    backend_version: str | None
    model_name: str | None
    model_version: str | None
    dependency_versions: dict[str, str]
    parameters: dict[str, JsonValue]
    processing_seconds: float
    warnings: list[str]
```

Candidate outputs should then wrap domain data:

- tempo: raw BPM, normalized BPM, confidence, candidates;
- beatgrid: beat times, optional downbeats/bars, confidence, offset metadata;
- sections: label, start/end seconds, confidence, source label, mapping notes.

The selected backend still has to produce the existing `AnalyzedTrack` and
waveform/debug JSON shapes so `tools/analysis-debug-viewer.html` remains useful.

## Timeline Normalization

Timing comparison must avoid hiding MP3 decoder offsets in individual
backends. The shared context should expose the source path, decoded analysis
audio path, duration, and any ffprobe/start-time offset. Benchmark tasks should
prefer one of these modes:

1. Decode each track once to a temporary WAV and pass that same file or samples
   to all candidates that support WAV.
2. If a candidate must analyze the original MP3, record that fact and apply the
   same offset policy during benchmark comparison.

This is required because `all-in-one` documents MP3 decoder offsets and the
Spec 004 viewer work already exposed millisecond-level display/timeline risk.

## Candidate Backend Notes

`current-autodj-signal`:

- Wrap existing tempo, beatgrid, waveform, and section behavior first.
- Preserve current artifact compatibility.
- Treat the section labels as weak baseline/fallback only.

`essentia-rhythm`:

- Use as a timing comparison and possible speed/native path.
- Keep AGPL/commercial licensing notes in benchmark output.
- Do not make it mandatory for package import or tests.

`beat-this`:

- Evaluate beat/downbeat timing accuracy against Rekordbox XML.
- Prefer packaged execution first; avoid DBN/madmom paths unless needed.
- Record model name/size and CPU/GPU behavior.

`all-in-one`:

- Evaluate both timing and functional sections.
- Record MP3/WAV timeline mode, model/dependency load time, and NATTEN/madmom
  dependency behavior.
- Map functional labels to AutoDJ labels through the section mapping policy;
  never promote `chorus` to high-confidence `drop` without additional evidence.

`songformer`:

- First task is availability only: repository, package path, model weights,
  license/model terms, and minimal inference.
- If availability is unclear, document the blocker and do not block the rest of
  the spec.

## Evaluation Data Model

Known-song evaluation should avoid committing media. Use local paths provided
by the user and write benchmark reports to ignored local locations unless a
task creates a sanitized summary.

Suggested local inputs:

```text
C:\Users\Brendan\Desktop\backspin.xml
C:\Users\Brendan\Desktop\headache.xml
C:\Users\Brendan\Desktop\vertigo.xml
C:\Users\Brendan\Desktop\new_feelings.xml
```

Suggested benchmark metrics:

- BPM absolute error,
- normalized BPM absolute error,
- first-beat offset milliseconds,
- nearest-beat median absolute error,
- nearest-beat 95th percentile absolute error,
- beat drift at cue points,
- section/cue boundary error where cue labels can be mapped,
- processing time,
- dependency/model load time,
- CPU/GPU requirement,
- artifact size.

Benchmark reports should also include structured candidate status:

```text
ok | unavailable | failed | deferred
```

This lets optional backends fail cleanly without breaking incumbent analysis.

## Candidate Selection Policy

The incumbent BPM/beatgrid analyzer is strong and should not be replaced for
novelty alone. The current section heuristic is weak and should be replaced or
substantially redesigned.

Selection requires:

- benchmark evidence,
- manual user verdict,
- cost/runtime assessment,
- license/platform assessment,
- clear fallback behavior.

The selected BPM/beatgrid backend may remain `current-autodj-signal` if no
candidate beats it. The selected section backend should not be the current
heuristic labeler unless every researched candidate is unavailable or worse and
that decision is explicitly accepted by the user.

### BPM / Beatgrid Selection Result

Task 11 manual review and Task 12 selection chose `current-autodj-signal` as
the BPM and beatgrid backend. It remains the default `analyze-batch` path
through `analyze_track_signal` and `CurrentSignalBackend`.

Selection rationale:

- it matched normalized Rekordbox BPM on the known songs;
- it emitted complete beat grids with one beat per Rekordbox reference beat;
- its stable offset/error profile was more trustworthy than sparse ML outputs;
- it is project-owned, local, deterministic, and license-safe;
- it preserves the existing `AnalyzedTrack` and debug-viewer artifact shape.

Rejected timing replacements:

- `beat-this` is useful as a comparison backend, but the installed integration
  emits beats/downbeats without native BPM and produced sparse grids on the
  known songs;
- `all-in-one` remains useful for section/downbeat experiments, but its timing
  outputs were sparse/late and the runtime is high;
- `essentia-rhythm` is fast and useful as a reference backend, but it did not
  beat the incumbent alignment and has AGPL/commercial-license risk.

Future timing benchmarks must report reference-beat recall and beat coverage in
addition to nearest candidate-beat median error, because sparse beat outputs can
look artificially strong under nearest-neighbor-only scoring.

## Section Label Policy

The project-facing label vocabulary for this spec is:

```text
intro, verse, build, drop, break, outro, unknown
```

For dubstep transition planning, repeated drops should be represented as
multiple `drop` sections with stable IDs/order such as `section-drop-001`,
`section-drop-002`, and `section-drop-003`, not as separate label strings.
`break` is the canonical label for post-drop break/breakdown/break-verse
regions. A low-energy region that is genuinely verse-like may remain `verse`,
but `break/verse` provider labels should normalize to `break` for DJ planning.

Many candidates emit pop-form labels such as `chorus`, `bridge`, or
`instrumental`. Map these labels conservatively:

- `intro` and `outro` can map directly when boundaries are plausible.
- `verse` can map directly unless energy evidence suggests a build or break.
- `chorus` can become `drop` only with supporting energy, bass, onset, and
  phrase-boundary evidence.
- `bridge` or `instrumental` can become `break` or `build` only with energy
  slope/context evidence.
- uncertain labels should remain `unknown` or low confidence.

The goal is useful DJ structure, not reproducing pop-song form labels.
Successful future transition systems will also need harmonic compatibility,
vocal/stem confidence, frequency-band complementarity, phrase/bar counts until
the next drop, and loopable pre-drop material. Those are downstream strategy
inputs; this task only defines the section vocabulary and mapping policy.

## Manual Test Checkpoints

Tasks should create explicit stop points such as:

```text
STOP: Generate artifacts for known songs and ask Brendan to inspect them in
tools/analysis-debug-viewer.html. Do not select the final backend until the
manual verdict is recorded under this task.
```

This is part of the spec, not a failure to automate. The user is the final
judge for musical alignment and usefulness.

## Documentation Outputs

Expected docs by the end of the spec:

- research dossier with candidate matrix,
- benchmark report summary,
- manual verdict notes,
- selected backend design,
- deferred future-spec backlog,
- README/steering updates for chosen analysis approach.
