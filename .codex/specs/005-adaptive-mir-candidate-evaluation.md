# Spec 005: Adaptive MIR Candidate Evaluation

> Kiro-style execution package:
> `.codex/specs/005-adaptive-mir-candidate-evaluation/`
>
> This is an adaptive research-gated spec. Use the folder's `kiro.json`,
> `requirements.md`, `design.md`, `tasks.md`, and `research-plan.md` when
> executing work. The initial tasks are intentionally exploratory; later
> implementation requirements must be refined after candidate research,
> benchmark results, and manual user verdicts.

## Purpose

Find and prove the best practical analysis stack for AutoDJ's timing and
semantic understanding. The spec begins with a deeper research pass across
academic and industry MIR systems for BPM, beatgrid, downbeats, stem separation,
semantic track sections, DJ cue points, transition planning, set planning, and
mixing techniques. The implementation path then adapts based on measured
candidate quality against Rekordbox XML ground truth and manual inspection in
the debug waveform viewer.

The spec is considered complete only after the project has a strong BPM and
beatgrid system plus a materially better section-analysis system for intro,
verse, build, drop, break, and outro style labels. Broader set planning,
transition technique generation, and stem-enriched mixing decisions should be
documented for future specs but are not required to ship in this spec.

## Adaptive Execution Model

This spec is not fully locked on day one. It has three explicit gates:

1. **Research Gate:** complete and document a thorough candidate survey.
2. **Benchmark Gate:** place current and candidate subsystems behind interfaces
   and compare outputs against Rekordbox XML on known songs.
3. **Selection Gate:** the user manually reviews artifacts in the HTML viewer
   and/or Rekordbox before final backend choices are locked.

Agents must not pretend the final implementation choices are known before those
gates complete.

Timing gate status: Tasks 10-12 selected `current-autodj-signal` as the BPM and
beatgrid backend after Rekordbox XML benchmarking and manual review. Section
analysis remains open for later tasks.

## Immediate Success Criteria

- A research dossier exists with primary-source links, installability notes,
  license/platform constraints, and future-spec candidates.
- BPM and beatgrid candidates can be swapped behind a small backend interface.
- Section-analysis candidates can be swapped behind a small backend interface.
- Candidate outputs are scored against Rekordbox XML ground truth.
- The user has explicit manual-test stop points before final backend selection.
- The selected BPM/beatgrid path is at least as good as the current analyzer on
  the known-song set.
- The selected section path is substantially better than the current heuristic
  section labels, which should be treated as disposable.

## Deferrals

- Production set planning.
- Final transition technique generation.
- Stem-separation-driven mix rendering.
- Mobile/native production analyzer.
- Hosted-provider commitment beyond optional evaluation.
- Any real music committed to git.
