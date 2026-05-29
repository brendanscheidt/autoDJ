# DeepDub Perfect Drop-Switch Baseline

This file records the known-good full-set policy that produced manually verified
perfect drop-switch alignment on the 48-track DeepDub batch.

## Source Run

- Run root:
  `C:\Users\Brendan\Dev\AudioProj\.autodj-cache\full-set-poc\deep-dub-full-20260528-004848`
- Full WAV:
  `C:\Users\Brendan\Dev\AudioProj\.autodj-cache\full-set-poc\deep-dub-full-20260528-004848\render\audition.wav`
- MixPlan:
  `C:\Users\Brendan\Dev\AudioProj\.autodj-cache\full-set-poc\deep-dub-full-20260528-004848\mix-plan-full-set.json`
- Manual verdict: all selected drop switches were perfect.

## Locked Policy

The matching machine-readable policy is
`deep-dub-perfect-drop-switch-policy.json`.

Important gates:

- `--candidate-search-width 24`
- `--max-tempo-adjustment-bpm 10`
- `--allow-drop-switch-tempo-stretch`
- `--drop-switch-key-policy compatible`
- `--min-stretched-drop-switch-nudge-confidence 0.85`
- `--max-drop-switch-nudge-ms 18`
- `--max-rendered-alignment-correction-ms 30`
- `--washout-sweep-uri 'C:/Users/Brendan/Desktop/sweep.wav'`

## Reproduction Command

```powershell
$RunRoot = "C:\Users\Brendan\Dev\AudioProj\.autodj-cache\deep-dub-set\deep-dub-set-20260527-235312"
$RunName = "deep-dub-full-safe-baseline"

wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && autodj-analysis plan-set --run-name '$RunName' --track-count 48 --mode full-plan-preview-render --seed deep-dub-001 --analysis-root '.autodj-cache/deep-dub-set/deep-dub-set-20260527-235312/analysis' --audio-folder '/mnt/c/Users/Brendan/Desktop/DeepDubAutoDj' --candidate-search-width 24 --max-consecutive-wash-outs 48 --emergency-fallback allow-repeated-artist --max-tempo-adjustment-bpm 10 --allow-drop-switch-tempo-stretch --drop-switch-key-policy compatible --min-stretched-drop-switch-nudge-confidence 0.85 --max-drop-switch-nudge-ms 18 --max-rendered-alignment-correction-ms 30 --washout-sweep-uri 'C:/Users/Brendan/Desktop/sweep.wav'"
```

## Why This Is Locked

This policy selected only 8 drop switches out of 47 transitions, but the selected
drop switches were manually reported as perfectly aligned. Treat it as the safe
rollback point while experimenting with higher drop-switch yield.

Current hypothesis for increasing drop-switch count:

- Keep key compatibility and confidence gates.
- Experiment with a slightly larger nudge window, starting at 24 ms.
- Increase candidate search width so the planner can look past early wash-out
  fallbacks before selecting.
- Experiment with `--drop-switch-key-policy allow-unknown` separately from the
  safe baseline. That policy rejects confident Camelot clashes but allows
  unknown/low-confidence keys through audition.
- Do not relax multiple gates at once without a manual audition batch.
