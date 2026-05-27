# Design Document

## Correct Framing

Pitch-preserving tempo control is a playback/rendering capability first and a
planner expansion second.

The engine should not enforce musical taste. It should expose robust tempo
control. The Dubstep DJ strategy applies taste through configurable candidate
gates, scoring, warnings, and manual audition feedback.

## Rekordbox Master Tempo

Public Rekordbox/CDJ documentation describes Master Tempo as changing playback
speed without changing pitch. AlphaTheta/Pioneer feature text also describes an
improved algorithm intended to preserve the original sound more faithfully.

No public source found during this spec draft discloses the exact Rekordbox
algorithm, parameters, or third-party SDK. Treat Rekordbox as a quality bar, not
as a reproducible implementation.

## Candidate Assessment

### Rubber Band Library

Rubber Band is the strongest first POC candidate:

- C++ library plus command-line utility.
- Supports independent tempo and pitch changes.
- Suitable for offline rendering and possible native integration.
- GPL/commercial licensing means product distribution needs review.

Use first because it is practical to install and audition quickly.

### SoundTouch

SoundTouch is useful as a baseline:

- LGPL library.
- Implements tempo, pitch, and playback-rate controls.
- Uses WSOLA-like time-domain stretching.
- Likely less transparent on dense full-mix dubstep than higher-end options,
  but easy to test.

### Signalsmith Stretch

Signalsmith Stretch is attractive for product architecture:

- MIT.
- Header-only C++.
- Supports pitch/time processing.
- Good candidate for native integration and possible mobile portability.

Risk: it must be auditioned on full-mix dubstep transitions before assuming it
can replace Rubber Band or commercial SDKs.

### zplane elastique

zplane elastique is a serious commercial/pro reference candidate:

- Known as a high-quality time-stretch/pitch-shift family in professional audio
  products.
- Commercial SDK access/licensing is the main blocker.
- Evaluate if open/local candidates do not reach the listening bar.

### Superpowered

Superpowered is a strategic mobile/native candidate:

- C++ SDK for real-time, low-latency cross-platform audio.
- TimeStretching includes pitch shifting.
- Mobile performance story is strong.

Risk: commercial SDK and product dependency implications. Keep it behind the
same interface.

### Zynaptiq ZTX

ZTX is another commercial high-end option:

- C/C++ SDK.
- Desktop and mobile support.
- Strong claims around complex material, dynamic parameters, and formants.

Use as an escalation candidate if needed.

## Backend Interface Shape

Python POC interface:

```python
class TempoStretchBackend:
    name: str

    def stretch(
        self,
        audio: np.ndarray,
        sample_rate: int,
        source_bpm: float,
        target_bpm: float,
        preserve_pitch: bool = True,
        quality: str = "default",
    ) -> TempoStretchResult:
        ...
```

Result:

```json
{
  "ok": true,
  "backendName": "rubberband",
  "backendVersion": "4.0.0",
  "sourceBpm": 160.0,
  "targetBpm": 150.0,
  "ratio": 0.9375,
  "preservePitch": true,
  "qualityMode": "fine",
  "runtimeSeconds": 4.21,
  "warnings": []
}
```

C++ eventual interface:

```cpp
class ITempoPitchEngine {
public:
    virtual ~ITempoPitchEngine() = default;
    virtual void prepare(double sampleRate, int channels) = 0;
    virtual void setTempoRatio(double ratio) = 0;
    virtual void setPitchCents(double cents) = 0;
    virtual void process(...) = 0;
};
```

Spec 009 should implement enough in Python/offline rendering to audition
quality before committing to a native dependency.

## MixPlan Contract Direction

The existing playback model already lists `tempo` as a mixer/deck control in
steering. Spec 009 should make the contract explicit enough for renderers:

- Asset or placement may carry `sourceBpm`.
- Placement or command may carry `targetBpm`, `tempoRatio`, and
  `preservePitch`.
- Tempo automation keyframes can ramp a deck from one effective BPM to another.
- Transition annotations carry the tempo plan:
  - outgoing native BPM;
  - incoming native BPM;
  - transition target BPM;
  - per-deck BPM adjustment;
  - stretch backend;
  - quality warnings.

Backward compatibility requirement: existing MixPlans without tempo fields keep
identity playback.

## Source-Time Mapping

Use these definitions:

- `sourceSeconds`: seconds in the original decoded audio.
- `timelineSeconds`: seconds in the rendered MixPlan output.
- `effectiveBpm`: audible BPM after tempo stretching.
- `tempoRatio = targetBpm / sourceBpm`.

For a constant stretch:

```text
outputDuration = sourceDuration / tempoRatio
sourceSeconds = outputElapsedSeconds * tempoRatio
```

Beatgrid mapping:

```text
effectiveBeatTime = placementTimelineStart
                  + (sourceBeatTime - sourceStartSeconds) / tempoRatio
```

Tempo ramps complicate this. V1 should support:

- constant incoming stretch for transition auditions;
- outgoing BPM ramp before the transition when needed;
- deterministic integration of tempo automation for source-time lookup.

If ramp support is too risky for the first implementation, the task should
explicitly stop for a design decision rather than faking it.

## Planner BPM Gate

Config:

```json
{
  "maxTempoAdjustmentBpmPerDeck": 10.0,
  "allowTempoRamps": true,
  "preferNativeBpmMatches": true,
  "warnAbovePercentChange": 6.0
}
```

Candidate rule:

```text
candidate is tempo-eligible if:
  abs(outgoingNativeOrCurrentBpm - targetBpm) <= maxTempoAdjustmentBpmPerDeck
  and
  abs(incomingNativeBpm - targetBpm) <= maxTempoAdjustmentBpmPerDeck
```

If no preferred target exists, use the nearest shared target inside both ranges.
For a simple bridge, that is usually the midpoint between the two BPMs.

Examples:

- `140` and `150`, gate `10`: eligible at `145`, `150`, or `140` depending on
  set-tempo strategy.
- `140` and `160`, gate `10`: eligible at `150`.
- `140` and `162`, gate `10`: rejected by default because no shared target is
  within both per-deck windows.

For drop switches, the selected effective BPM at overlap must be exact for both
decks.

## Tempo Ramp Strategy

The user explicitly wants the current deck to be able to drift up or down before
mixing so a larger BPM gap can meet in the middle.

V1 behavior:

- Allow an outgoing tempo ramp only before the transition overlap.
- Prefer ramping during sections where the current track is already playing
  alone.
- Annotate the ramp in the MixPlan and debug report.
- Keep the incoming track at the shared target BPM for the overlap.

Do not silently ramp tempo during a dense build/drop if the plan did not request
it. Tempo drift is audible and must be explainable.

## Quality Diagnostics

For each stretched render, report:

- backend;
- ratio and BPM delta;
- render time;
- peak/headroom after stretch;
- transient-envelope comparison around drop/build anchors;
- beatgrid drift after stretch;
- warnings for large percentage changes;
- user verdict placeholder.

Subjective audition remains the final quality gate.

## CLI Shape

Backend smoke:

```powershell
autodj-analysis tempo-stretch-smoke `
  --audio "C:\Users\Brendan\Desktop\AutoDJTestDubstep\example.mp3" `
  --source-bpm 160 `
  --target-bpm 150 `
  --out .autodj-cache/tempo-stretch-smoke `
  --backends rubberband,soundtouch
```

Render one file:

```powershell
autodj-analysis stretch-audio `
  "song.wav" `
  --source-bpm 160 `
  --target-bpm 150 `
  --backend rubberband `
  --out stretched.wav `
  --report stretch-report.json
```

Render a stretched MixPlan:

```powershell
autodj-analysis render-mixplan mix-plan.json `
  --out .autodj-cache/rendered `
  --tempo-backend rubberband
```

Audition batch:

```powershell
autodj-analysis generate-tempo-match-auditions `
  --analysis-root .autodj-cache/analysis `
  --audio-folder "C:\Users\Brendan\Desktop\AutoDJTestDubstep" `
  --out .autodj-cache/tempo-match-auditions/<run> `
  --max-tempo-adjustment-bpm 10 `
  --backends rubberband,soundtouch
```

## Manual Gates

### Stretch Backend Smoke Verdict

Report which candidates are runnable locally and which are licensing/dependency
blocked before doing broad benchmarks.

### Stretch Quality Verdict

Render several real dubstep examples at multiple BPM deltas and ask the user to
listen before selecting the default backend.

### Tempo Planner Verdict

Generate tempo-matched drop switches through the planner and ask whether the
default BPM window and transition behavior are acceptable.

## Risks

- Large BPM changes can smear transients or flatten perceived drop impact.
- A backend that sounds good on vocals may fail on dense dubstep bass design.
- Commercial SDKs may be required for Rekordbox-like quality.
- Tempo ramps change the perceived set energy and can sound unnatural if placed
  poorly.
- Beatgrid/transient nudge logic must be rechecked after stretching because the
  source-time mapping changes.
- Rubber Band and keyfinder/libkeyfinder licensing both need productization
  review before commercial distribution.

