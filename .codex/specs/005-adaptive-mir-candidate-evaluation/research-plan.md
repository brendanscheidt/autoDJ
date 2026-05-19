# Research Plan

## Purpose

This document controls the exploratory phase of Spec 005. The goal is not to
collect interesting links; it is to identify candidate systems that can
materially improve AutoDJ's analysis quality or future product direction.

## Research Rules

- Prefer primary sources: academic papers, official repos, official docs, model
  cards, and provider API docs.
- For each candidate, capture:
  - feature role,
  - source links,
  - claimed outputs,
  - install/runtime path,
  - license and model-data terms,
  - local/offline viability,
  - hosted/API viability,
  - compute cost and expected processing time,
  - platform risk for Windows, WSL, and future mobile/native use,
  - whether it can be evaluated in this spec or deferred.
- Separate timing-critical systems from semantic recommendation systems. BPM
  and beatgrid need near-sample-accurate behavior; track similarity and set
  planning can tolerate softer ML outputs.
- Record negative findings. A candidate that is too slow, unavailable,
  non-commercial, unmaintained, or poorly aligned should still be documented so
  future agents do not re-research it.

## Required Research Areas

### BPM, Beatgrid, Downbeats, And Meter

Research neural, probabilistic, and hybrid MIR systems for:

- BPM estimation,
- beat positions,
- beat-grid phase,
- downbeats,
- meter,
- dynamic tempo handling,
- electronic music and dubstep/halftime behavior.

Minimum candidate families to include unless clearly disqualified:

- current AutoDJ analyzer,
- librosa,
- Essentia,
- madmom,
- BeatNet,
- Beat Transformer or similar demixed/stem-aware beat systems,
- aubio or maintained alternatives,
- hosted beat/BPM providers where official docs expose relevant outputs.

### Stem Separation

Research stem systems for future enrichment, especially:

- drums,
- bass,
- vocals,
- other/instrumental stems,
- processing time,
- GPU/CPU feasibility,
- whether stems can improve beatgrid, drop, break, and vocal-clash detection.

Minimum candidate families:

- Demucs,
- Spleeter,
- Open-Unmix or newer maintained equivalents,
- hosted stem providers.

Stem separation is likely deferred from implementation in this spec unless it
is needed to prove section analysis, but it must be documented for future specs.

### Semantic Track Sections

Research systems for segmenting and labeling:

- intro,
- verse,
- build,
- drop,
- break/breakdown,
- chorus/hook,
- bridge,
- outro,
- silence,
- high-energy and low-energy regions.

Include both academic structure-analysis systems and DJ/electronic-music
specific cue/switch-point systems. The current heuristic labeler is considered
too weak to preserve unless comparison proves otherwise.

### Optimal Mix Sections And Cue Points

Research systems for:

- mix-in and mix-out point selection,
- phrase alignment,
- switch points,
- cue point recommendation,
- vocal avoidance,
- energy trajectory,
- harmonic compatibility,
- transition risk scoring.

### Set Planning And Track Compatibility

Research systems for:

- next-track recommendation,
- track embeddings,
- mood/genre/energy similarity,
- key/harmonic compatibility,
- danceability,
- playlist or DJ set optimization.

This area is mostly future-spec material, but candidates should be documented
now to prevent repeat research.

### Transition Techniques

Research automatic DJ transition systems for:

- beatmatching,
- phrase-aligned crossfades,
- EQ/filter transitions,
- stem-based transitions,
- generated transition audio,
- rule-based versus ML-based transition planning.

Implementation is deferred unless a candidate directly informs BPM, beatgrid,
or section analysis.

## Research Deliverables

Create or update a research dossier in this spec folder with:

- a candidate matrix,
- a short recommendation per feature family,
- "evaluate now" versus "defer" decisions,
- explicit blockers,
- candidate benchmark plan,
- future-spec backlog notes.

The dossier should be strong enough that later specs can reuse it without
starting a new web-search pass.

