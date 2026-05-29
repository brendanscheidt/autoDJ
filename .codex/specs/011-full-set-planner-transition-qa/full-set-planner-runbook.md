# Spec 011 Full-Set Planner Runbook

This runbook documents the accepted full-set QA workflow after Spec 011.

The planner consumes existing `AnalyzedTrack` artifacts. It does not rerun
audio analysis. For the current POC, semantic sections come from
Rekordbox-labeled artifacts; automatic semantic detection is still treated as
experimental for high-risk drop switches.

## Default Inputs

PowerShell examples assume:

```powershell
$ProjectRoot = "C:\Users\Brendan\Dev\AudioProj"
$AudioFolder = "C:\Users\Brendan\Desktop\AutoDJTestDubstep"
$AnalysisRoot = "$ProjectRoot\.autodj-cache\transition-auditions\transition-audition-20260521-102954\analysis"
$WashoutSweep = "C:\Users\Brendan\Desktop\sweep.wav"
```

The analysis root can be replaced with any cache folder that contains
`tracks\<track-id>\analyzed-track.json`.

## Fast Analysis For New Batches

Routine POC set generation should not run the slow experimental semantic
models. The accepted workflow is:

1. Analyze BPM, beatgrid, key, waveform, and rough signal sections with the
   fast backend.
2. Apply Rekordbox-labeled semantic cues where available.
3. Run transition planning against those Rekordbox-truth semantic markers.

Use `--workers 2` whenever running `autodj-analysis analyze-batch` directly.
On the current Windows/WSL machine this measured faster than `--workers 3` or
`--workers 8`; the higher worker counts oversubscribe ffmpeg, SciPy/librosa, and
disk I/O.

```powershell
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && autodj-analysis analyze-batch '/mnt/c/path/to/repository-manifest.json' --out '/mnt/c/path/to/analysis' --section-backend current-autodj-signal --key-backend keyfinder --workers 2 --debug-waveform-points 32768 --json"
```

`tools\run-transition-audition-batch.ps1` now uses this fast path by default:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\run-transition-audition-batch.ps1 `
  -AudioFolder "C:\Users\Brendan\Desktop\AutoDJTestDubstep" `
  -RunName "transition-audition-$(Get-Date -Format yyyyMMdd-HHmmss)" `
  -AnalysisWorkers 2 `
  -AnalysisSectionBackend current-autodj-signal `
  -AnalysisKeyBackend keyfinder
```

The script asks `analyze-batch` to write `debug-waveform.json` during the same
decoded-audio pass as BPM/key/beatgrid analysis, so it no longer launches a
second per-track debug-waveform decode loop.

The 48-track `AutoDJTestDubstep` timing smoke run measured 379.96 seconds with
2 workers, the current signal backend, KeyFinder, ffmpeg decode, and inline
debug waveform generation. This is the accepted fast path until the remaining
tempo/energy extraction hotspots are optimized further.

Use `-AnalysisSectionBackend dubstep-phrase-hybrid` only for experiments that
explicitly compare automatic semantic section labeling. It runs the ML-backed
section candidates and is expected to be much slower on 48-track batches.

Use `-AnalysisKeyBackend selected-madmom-keyfinder` only for high-accuracy
offline key experiments. It can take minutes per track because the Madmom CNN
backend is very slow on full songs. Routine set-prep uses the in-house
KeyFinder backend so BPM/beatgrid/key/debug artifacts can be generated within
the POC latency target.

## Preview-First Workflow

Generate a deterministic preview pack before rendering a full WAV:

```powershell
cd C:\Users\Brendan\Dev\AudioProj

$RunName = "spec011-preview-$(Get-Date -Format yyyyMMdd-HHmmss)"

wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && autodj-analysis plan-set --run-name $RunName --track-count 16 --mode plan-preview --seed spec011-safe-drop-v3 --candidate-search-width 16 --max-consecutive-wash-outs 4 --max-tempo-adjustment-bpm 10 --min-stretched-drop-switch-nudge-confidence 0.85 --max-drop-switch-nudge-ms 18 --allow-drop-switch-tempo-stretch --max-rendered-alignment-correction-ms 30 --washout-sweep-uri 'C:/Users/Brendan/Desktop/sweep.wav'"
```

Important outputs:

- `.autodj-cache/full-set-poc/<run-name>/mix-plan-full-set.json`
- `.autodj-cache/full-set-poc/<run-name>/full-set-summary.json`
- `.autodj-cache/full-set-poc/<run-name>/candidate-report.json`
- `.autodj-cache/full-set-poc/<run-name>/validation-report.json`
- `.autodj-cache/full-set-poc/<run-name>/previews/index.json`
- `.autodj-cache/full-set-poc/<run-name>/previews/*/audition.wav`

Listen to preview WAVs first. Do not render a full set until the preview pack
is acceptable enough for a long-form audition.

## Render From An Accepted MixPlan

Rendering from an already accepted `mix-plan-full-set.json` avoids rerunning
pair search, nudge, and gain post-passes.

Do not render a full-set MixPlan whose `washout-sweep-fx` asset points at
`generated://autodj/fx/washout-sweep-v1.wav`. That URI is a renderer fallback,
not the accepted POC wash-out sound. Regenerate the plan with
`--washout-sweep-uri 'C:/Users/Brendan/Desktop/sweep.wav'` first.

```powershell
cd C:\Users\Brendan\Dev\AudioProj

$MixPlan = "C:\Users\Brendan\Dev\AudioProj\.autodj-cache\full-set-poc\spec011-drop-lookahead-gainv2-smoke-20260527-190044\mix-plan-full-set.json"
$Out = "C:\Users\Brendan\Dev\AudioProj\.autodj-cache\full-set-poc\spec011-full-render-checkpoint-20260527-2118\render"
$AssetRoot = "C:\Users\Brendan\Desktop\AutoDJTestDubstep"

$MixPlanWsl = (wsl.exe -d Ubuntu-24.04 -- wslpath -a ($MixPlan -replace "\\","/")).Trim()
$OutWsl = (wsl.exe -d Ubuntu-24.04 -- wslpath -a ($Out -replace "\\","/")).Trim()
$AssetRootWsl = (wsl.exe -d Ubuntu-24.04 -- wslpath -a ($AssetRoot -replace "\\","/")).Trim()

wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && autodj-analysis render-mixplan '$MixPlanWsl' --out '$OutWsl' --asset-root '$AssetRootWsl' --json"
```

Previous full-render checkpoint:

- Latest accepted-policy checkpoint:
  `.autodj-cache/full-set-poc/spec011-accepted-policy-full-checkpoint-20260529-092924`
- WAV:
  `.autodj-cache/full-set-poc/spec011-accepted-policy-full-checkpoint-20260529-092924/render/audition.wav`
- Render summary:
  `.autodj-cache/full-set-poc/spec011-accepted-policy-full-checkpoint-20260529-092924/render/render-summary.json`
- Preview index:
  `.autodj-cache/full-set-poc/spec011-accepted-policy-full-checkpoint-20260529-092924/previews/index.json`
- Full-set summary:
  `.autodj-cache/full-set-poc/spec011-accepted-policy-full-checkpoint-20260529-092924/full-set-summary.json`

The latest checkpoint is about 21 minutes and 42 seconds long and was rendered
from a 15-transition plan: 12 drop switches and 3 wash-outs. Validation passed,
all drop-switch gain verdicts were `strong`, and the selected nudge range stayed
inside +/-18 ms.

## Policy Notes

Current accepted planner behavior:

- Prefer drop switches when key, BPM/stretch, section anchors, nudge quality,
  and gain verdicts are acceptable.
- Use wash-outs to escape incompatible BPM/key/section conditions.
- Wash-outs use the user-rendered sweep asset at
  `C:\Users\Brendan\Desktop\sweep.wav`. Do not use the renderer's generated
  sine sweep for accepted set generation.
- Use SoundStretch for incoming-track tempo matching when explicitly enabled
  and inside the configured BPM gate.
- Reject risky drop switches with excessive absolute nudge or weak stretched
  nudge confidence.
- Full-set planning uses the accepted raw transient nudge path by default.
  Rendered-domain drop-switch proof is available with
  `--prove-rendered-drop-switch-alignment`, but it is intentionally opt-in
  because it is expensive and can stall on individual candidates.
- Keep drop-switch windows dry; validation rejects wet reverb/echo leakage.
- Stop/truncate outgoing placements so old tracks do not continue quietly under
  later transitions.

Known limitations:

- Rekordbox-labeled semantic cues remain the trusted POC oracle.
- Perceived loudness matching is improved but not perfect. The gain pass uses
  RMS, low-band, and drop peak matching, with renderer soft limiting. It is not
  a full LUFS/true-peak mastering chain yet.
- Full pair search can still be slow when the candidate pool is broad, but
  rendered-domain nudge proof is no longer forced on every selected drop switch.
  Prefer rendering from an accepted MixPlan when testing the full WAV path.
- Automatic drop semantic detection remains deferred until a future trained
  model or better cue provider meets the required accuracy.
