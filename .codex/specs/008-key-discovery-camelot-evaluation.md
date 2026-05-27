# Spec 008: Key Discovery And Camelot Evaluation

> Detailed implementation folder:
> `.codex/specs/008-key-discovery-camelot-evaluation/`

## Overview

Develop an in-house key detection pipeline for AutoDJ, evaluate it against
Rekordbox `TRACK Tonality` ground truth, and then feed the selected detector's
Camelot output into transition planning.

Rekordbox is not the production key source. It is the labeled reference used to
score candidate detectors, tune preprocessing, and decide whether our own output
is good enough for DJ planning.

## Why Now

Spec 006 and Spec 007 proved that timing alone is not enough. Drop switches,
build blends, vocal overlays, and future stem transitions also need harmonic
compatibility. The user's Rekordbox XML already contains Camelot labels for the
same tracks we use for auditioning, which gives us a practical evaluation set.

The goal is not to copy Rekordbox. The goal is to find a robust detector stack
that agrees with Rekordbox often enough, exposes confidence honestly, and can
eventually run locally without depending on a DJ library export.

## Candidate Detector Families

Evaluate multiple local backends before selecting the production path:

- Essentia `KeyExtractor`, including EDM-oriented profile tuning where useful.
- madmom CNN key recognition, if installable in the WSL analysis environment.
- libkeyfinder or keyfinder CLI as a DJ-focused native/library candidate.
- librosa chroma/CQT/CENS plus Krumhansl/Temperley/Shaath/Faraldo-style key
  profiles as a project-owned baseline.
- Ensemble strategies that combine the above by confidence, agreement, and
  Camelot-distance penalties.

Rekordbox XML `Tonality` is used only for evaluation, regression fixtures, and
manual comparison reports.

## Primary Goals

- Add a modular key detector interface in the Python analysis worker.
- Implement and benchmark multiple candidate key detectors on the Rekordbox
  labeled dubstep set.
- Convert detector outputs into normalized tonic/mode/Camelot fields.
- Score candidates against Rekordbox truth using exact, adjacent, relative,
  parallel, and miss categories.
- Tune preprocessing and EDM-specific profiles until accuracy is musically
  useful.
- Select a default detector or ensemble and record the decision with metrics.
- Expose selected key metadata to C++ planning and compatibility scoring.

## Success Target

The target is at least 90% musically acceptable Camelot agreement on the user's
Rekordbox-labeled dubstep set before key becomes a hard planning gate.

Use two metrics:

- strict exact key accuracy;
- DJ-usable compatibility accuracy, where exact, relative, and adjacent Camelot
  relationships are counted separately and reported clearly.

If strict exact accuracy remains below target but DJ-usable compatibility is
high, the planner may use key as a preference signal but not a hard rejection
signal.

## Compatibility Policy After Detector Selection

Only after a detector/ensemble is selected:

- Drop-switch build blends should prefer exact, relative, or adjacent Camelot
  pairs.
- Reverb exits and hard cuts should warn on clashes but not block.
- Future vocal/stem overlays may require stricter key compatibility.

## Explicit Non-Goals

- Do not treat Rekordbox key labels as production metadata.
- Do not add key sync, pitch shifting, or time stretching in this spec.
- Do not require paid hosted services for the default POC path.
- Do not make key compatibility a hard rejection until detector accuracy and
  confidence calibration are accepted.
- Do not solve chord progression or local modulation detection beyond optional
  debug reporting.

## Initial Research References

- Essentia KeyExtractor documentation:
  https://essentia.upf.edu/reference/std_KeyExtractor.html
- madmom CNN key recognition documentation:
  https://madmom.readthedocs.io/en/v0.16.1/modules/features/key.html
- libkeyfinder repository:
  https://github.com/mixxxdj/libkeyfinder
- librosa chroma feature documentation:
  https://librosa.org/doc/main/feature.html
- Genre-agnostic CNN key classification paper:
  https://arxiv.org/abs/1808.05340
- EDM key estimation thesis:
  https://zenodo.org/records/1154586
- MIREX audio key detection results:
  https://music-ir.org/mirex/wiki/2018%3AAudio_Key_Detection_Results

## Completion Criteria

- Rekordbox `Tonality` labels can be imported into a benchmark truth table.
- At least two independent key detector backends run on local audio.
- A baseline project-owned chroma/profile detector exists for portability.
- Candidate outputs are normalized to Camelot and compared against truth.
- A benchmark report identifies per-track agreement, common failure modes, and
  processing time.
- A selected detector or ensemble populates `AnalyzedTrack.key`.
- C++ planning can read selected key metadata and emit compatibility reasons.
- Documentation records which backends were tried, why the selected path won,
  and which detector work is deferred.
