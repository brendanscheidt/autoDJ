# Deferred Candidates And Future Specs

Updated: 2026-05-19

This document is the handoff from Spec 005's research and benchmark work to
future implementation specs. It intentionally avoids re-opening candidate
selection for the current spec.

Current selected analysis stack:

- BPM and beatgrid: `current-autodj-signal`.
- Semantic sections: `dubstep-phrase-hybrid`.
- Weak fallback: `current-autodj-signal` rough sections, only when the selected
  section backend cannot run or emits no usable sections.

Ground rule for future specs: start from the selected stack above and use this
document plus `research-dossier.md` as the research baseline. Do not repeat the
full survey unless a candidate has materially changed, a license concern must
be resolved, or the product goal changes.

## Near-Term Follow-Up Specs

### Section Confidence, Correction, And Cue Ranking

Purpose:

- Improve practical section usefulness after `dubstep-phrase-hybrid`, without
  overfitting Spec 005 thresholds.
- Add user correction and confidence-aware planning so the DJ can work around
  imperfect sections.

Candidate inputs to revisit:

| Candidate | Why Deferred | Reopen When |
| --- | --- | --- |
| Automatic DJ cue switch points | Better fit for choosing mix-in/mix-out points than replacing section labels. Install path and dataset/code license still need follow-up. | A transition-planning spec needs cue ranking after sections exist. |
| Cue Point Estimation using Object Detection | Directly targets DJ cue points and phrase adherence, but package/install clarity was insufficient for first-wave implementation. | Public model/checkpoint and license path are confirmed. |
| MSAF | Useful boundary/repetition reference, but current SciPy/import compatibility was poor and labels are not DJ-specific. | A future task needs cheap boundary-only comparison. |
| Structural-function 7-class models | Good pop-form taxonomy reference, but lacks build/drop/break labels and a simple package path. | The project needs more robust intro/verse/outro labels, not drop anchors. |
| Cyanite 15-second segments | Good hosted semantic enrichment, but too coarse for beat-accurate sections. | Set planning needs commercial semantic tags and network use is acceptable. |

Implementation direction:

- Keep Rekordbox XML as evaluation-only truth, never as runtime input.
- Preserve `SectionBackend` contracts and selected artifact shape.
- Add confidence gates for transition planning:
  - high confidence: complex build/drop transitions;
  - medium confidence: phrase-aligned simple transitions;
  - low confidence: hard cut or reject track from generated set.
- Add manual correction UX later:
  - drag/nudge beatgrid;
  - edit cue labels;
  - split/merge/relabel sections;
  - export/import corrected metadata.

Primary source pointers:

- Automatic DJ cue/switch research and object-detection cue work are summarized
  in `research-dossier.md` under "Semantic Sections, Structure, And Cues" and
  "Mix Sections, Transition Techniques, And Automatic DJ Systems".

## Stem Separation And Vocal-Aware Mixing

Purpose:

- Enable vocal clash detection, acapella/instrumental layering, drop doubles
  with frequency masking, and stem-aware cue ranking.

Deferred candidates:

| Candidate | Outputs | Why Deferred | Future Role |
| --- | --- | --- | --- |
| Demucs | Vocals, drums, bass, other; two-stem vocal mode | Heavy GPU/PyTorch cost and stem quality is not required for Spec 005 completion. | First local stem candidate for vocal-aware transitions. |
| BS-RoFormer / Mel-Band RoFormer | Modern high-quality separation, often vocals/instrumental or multistem | Model zoo and checkpoint/license complexity. | Quality comparison against Demucs when stem sound quality matters. |
| Open-Unmix | Vocals, drums, bass, other | Useful research baseline, likely not best product quality. | Lightweight comparative baseline. |
| Spleeter | 2/4/5 stems | Older TensorFlow stack and lower expected quality than modern models. | Simple fallback/baseline if Demucs is too heavy. |
| AudioShake | Hosted stems and analysis | Upload cost/privacy/vendor dependency. | Product-quality reference or optional cloud path. |
| Music AI stems | Hosted workflow stems and analysis | Upload cost/privacy/vendor dependency. | External comparison path for local model quality. |
| zplane STEMS | Commercial native SDK | Paid/commercial terms need review. | Potential product/native path if licensing is acceptable. |

Recommended future spec shape:

1. Add optional stem cache keyed by source hash, model name/version, and
   settings.
2. Start with Demucs `--two-stems=vocals` for vocal/instrumental tests.
3. Add stem quality scoring before any transition depends on stems.
4. Emit vocal regions and vocal-confidence metadata into `AnalyzedTrack`.
5. Make stem extraction opt-in, resumable, and concurrency-limited.
6. Use stems to support:
   - vocal-over-instrumental transitions;
   - vocal clash avoidance;
   - bass/high-frequency complement scoring;
   - cleaner drop cue ranking.

Do not make stems mandatory for all transitions. The fallback should remain
phrase-aligned non-stem transitions.

Primary source pointers:

- Demucs: `https://arxiv.org/abs/1909.01174`,
  `https://github.com/facebookresearch/demucs`
- Spleeter: `https://github.com/deezer/spleeter`
- Additional stem candidates are summarized in `research-dossier.md`.

## Set Planning, Similarity, And Track Compatibility

Purpose:

- Choose track order and transition pairs, not just analyze individual tracks.
- Support energy arcs, harmonic compatibility, semantic compatibility, vocal
  clash risk, and library browsing.

Deferred candidates:

| Candidate | Outputs | Why Deferred | Future Role |
| --- | --- | --- | --- |
| Essentia TensorFlow / Discogs EffNet / MusiCNN | Embeddings, tags, mood, danceability, genre | Adds TensorFlow/model weight complexity; not needed for timing truth. | Local similarity/tagging baseline. |
| MERT | Self-supervised music embeddings | Heavy PyTorch model and license/model-card review required. | Strong future compatibility/mood embeddings. |
| CLAP / LAION-CLAP | Audio/text embeddings and zero-shot retrieval | Heavy local model, checkpoint/data terms require review. | Search, text prompts, semantic tags. |
| Cyanite similarity | Hosted similarity, BPM/key/genre/mood/voice filters | Commercial hosted API, network/cost/privacy. | Product reference or optional cloud enrichment. |
| MuLan | Joint audio/text embeddings | Public package/model availability unclear. | Reject for implementation until an official usable path exists. |

Recommended future spec shape:

1. Define track compatibility inputs:
   - BPM delta;
   - key/Camelot compatibility;
   - section availability;
   - energy curve and target set arc;
   - vocal presence;
   - frequency-band complementarity;
   - optional embeddings/tags.
2. Add a deterministic scoring layer first.
3. Use embeddings as additional evidence, not as opaque final decisions.
4. Keep hosted systems optional and cache results with provider/version.

Primary source pointers:

- Essentia model catalog:
  `https://essentia.upf.edu/documentation/models.html`
- Other candidates are summarized in `research-dossier.md` under
  "Set Planning, Similarity, And Track Compatibility".

## Transition Technique Generation

Purpose:

- Turn analysis metadata into musical deck commands, EQ/filter automation,
  looping, cuts, doubles, and stem-aware transitions.

Deferred systems and references:

| Candidate / Reference | Why Deferred | Future Role |
| --- | --- | --- |
| Drum and Bass automatic DJ system | Full automatic-DJ pipeline is too broad for Spec 005. | Strong architecture reference for genre-specific cue selection, EQ, track selection, and transition classes. |
| Mosaikbox | Heavy app/backend with Docker, MongoDB, KeyFinderService, and source separation. | Architecture reference, not a direct library dependency. |
| Automatic DJ cue switch points | More useful after section/cue contracts are stable. | Candidate cue ranker. |
| Cue Point Estimation using Object Detection | Needs install/license follow-up. | Candidate cue detection model. |
| DJ mix reverse engineering | Dataset/license review required. | Future training/evaluation data for transition strategy. |
| GAN/differentiable DSP transitions | Solves transition rendering, not core analysis correctness. | Later experimental audio rendering, not early DJ logic. |

Recommended future spec shape:

1. Start with deterministic transition templates from
   `.codex/steering/05-dubstep-dj-strategy.md`:
   - intro/outro blend;
   - build-to-drop swap;
   - loop-tighten into drop;
   - drop double;
   - frequency-complement drop double;
   - vocal predrop layer;
   - hard/impact cut.
2. Require high beatgrid confidence for loop tightening and drop doubles.
3. Require section confidence before planning complex semantic transitions.
4. Record rejected alternatives and risk flags in `MixPlan` annotations.
5. Use ML only for cue ranking or risk scoring until deterministic templates
   are proven insufficient.

Primary source pointers:

- Drum and Bass automatic DJ system:
  `https://link.springer.com/article/10.1186/s13636-018-0134-8`
- Differentiable DSP/GAN transition research:
  `https://arxiv.org/abs/2110.06525`

## Hosted And Commercial Provider Backlog

Use hosted systems as optional references or premium/cloud paths only. They
should not be mandatory for the desktop POC or the future offline mobile goal.

| Provider | Relevant Outputs | Main Risk | Future Use |
| --- | --- | --- | --- |
| Music AI | BPM/beat workflows, stems, transcription | Uploads, cost, provider dependency | External comparison when local timing/stem quality disappoints. |
| Klangio | Beat/downbeat timings, BPM, meter | Uploads, cost, provider dependency | Hosted timing reference. |
| Cyanite | BPM, key, mood, genre, voice, instruments, energy, 15s segments, similarity | Segment coarseness, network/cost/privacy | Set planning and semantic enrichment. |
| AudioShake | Stem separation, transcription, content analysis | Commercial hosted API | Stem quality reference. |
| Superpowered Analyzer | Native BPM, key, beatgrid, bars, waveform, compact music structure | Commercial/proprietary SDK | Strong native/mobile product candidate if licensing works. |

Future provider tasks must document:

- upload/privacy posture;
- per-track/per-minute cost;
- rate limits;
- terms for storing returned metadata;
- whether outputs are deterministic enough for regression tests;
- local fallback when the provider is unavailable.

## Native And Mobile Analyzer Backlog

Purpose:

- Decide how the Python POC becomes a product path on desktop and mobile.

Deferred candidates and paths:

| Candidate / Path | Why Deferred | Future Role |
| --- | --- | --- |
| Superpowered Analyzer | Commercial SDK, not an open research backend. | Strong commercial native/mobile analyzer option. |
| Essentia C++ | AGPL/commercial-license decision required. | Native descriptors and rhythm reference if licensed appropriately. |
| audioFlux C path | Needs evaluation; not part of first-wave research. | Possible native DSP/feature extraction backend. |
| Vamp/QM plugins | Plugin packaging and licensing overhead. | Desktop reference/validator, less likely mobile. |
| Homegrown C++ ports | Requires POC algorithm stabilization first. | Long-term offline/mobile ownership path. |
| Mobile-safe ML runtimes | Model conversion and latency unknown. | Later path for embeddings/stems/sections if deterministic heuristics are insufficient. |

Recommended future spec shape:

1. Identify which outputs must be generated on-device:
   - waveform;
   - energy curves;
   - BPM/beatgrid;
   - sections/cues;
   - key;
   - vocals/stems, only if product-critical.
2. Build golden fixtures from the Python POC.
3. Prototype one native feature family at a time.
4. Compare native output against Python fixtures with tolerances.
5. Resolve licensing before copying or porting any third-party behavior.

## Deferred Timing Alternatives

The selected timing backend remains `current-autodj-signal`. Do not reopen
timing unless a new failure class appears or a native/mobile requirement forces
a different implementation.

| Candidate | Reason Deferred |
| --- | --- |
| `beat-this` | Useful ML beat/downbeat comparison, but emitted sparse beat grids and no native BPM in the first benchmark. |
| `all-in-one` timing | Reasonable BPM on some songs but sparse/late grids and high runtime. |
| `essentia-rhythm` | Fast and native-adjacent, but less accurate beat phase and AGPL/commercial license risk. |
| BeatNet | Overlaps `beat-this`; madmom/offline dependency friction. |
| madmom primary path | Old dependency ecosystem and model/data license concerns. |
| Beat Transformer | Strong stem-aware research, but operationally heavier and needs demixed spectrogram pipeline. |
| BEAST | Online/streaming focus not needed for offline POC. |
| aubio | Lightweight but GPLv3-or-later and unlikely to beat selected grid quality. |
| QM Vamp | Good validator, packaging/licensing overhead. |
| standalone `librosa.beat` | Already used as one component; not strong enough alone. |

If timing is reopened, benchmark reports must include beat coverage and
reference-beat recall, not only nearest-beat median error.

## Future Spec Ordering Recommendation

Recommended sequence after Spec 005:

1. Playback engine skeleton and MixPlan execution, if not already complete.
2. First deterministic dubstep MixPlan generator using selected BPM/beatgrid and
   `dubstep-phrase-hybrid` sections.
3. Section correction/confidence calibration after real transition failures are
   observed.
4. Stem/vocal-aware transitions once simple transitions are musically useful.
5. Set planning and compatibility embeddings after transition templates exist.
6. Native/mobile analyzer feasibility after Python POC outputs stabilize.

This ordering keeps the project from spending weeks on heavier ML/stem systems
before proving the selected analysis metadata can drive a listenable mix.

## Verification Notes

This document is documentation-only. No code, schema, or benchmark behavior is
changed by this task. Per Requirement 8.7, no unit tests were added.
