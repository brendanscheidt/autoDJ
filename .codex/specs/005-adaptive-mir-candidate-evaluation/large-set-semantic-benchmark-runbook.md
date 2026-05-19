# Large Set Semantic Benchmark Runbook

This runbook is for testing the selected semantic-section backend against a
larger Rekordbox export without asking Codex to run the expensive model pass.
Run these commands yourself in a new PowerShell terminal.

As of task 16, `dubstep-phrase-hybrid` is also the default semantic section
backend for normal `autodj-analysis analyze-batch` artifact generation. This
runbook still uses `autodj-analysis benchmark-sections` because it produces the
extra Rekordbox comparison report, `debug-waveform.json`, and copied
`source-audio.mp3` files that make manual viewer inspection easier.

The benchmark does not call OpenAI or any paid API. It runs local WSL/Python
analysis, All-In-One, and SongFormer from the `.venv-analysis` environment.
The cost is local GPU/CPU time and disk space. Running it yourself also avoids
spending Codex interaction credits on a long model job.

## Current Algorithm Notes

The selected/default semantic backend is `dubstep-phrase-hybrid`. As of the
latest iteration, that backend uses:

- The current AutoDJ BPM/beatgrid system with final dubstep BPM quantization.
  For dubstep, final BPMs are rounded to whole-number or `.5` values.
- All-In-One and SongFormer as section-boundary evidence providers.
- A conservative drop-entry anchor preference that favors a real energy/bass
  jump into a drop over a later high-energy marker inside an already-started
  drop.
- Turnaround-aware grouping so short mid-drop re-entries can be treated as
  internal drop anchors instead of always becoming separate top-level drops.

The goal for the current POC is not perfect full-song section labeling. A run is
useful if most tracks expose at least one musically correct `build -> drop` pair
with a clean beatgrid. That is enough to test transition planning without
overfitting the section detector to every unusual song structure.

Important truth boundary: Rekordbox XML is used to find source audio paths and
to build reference sections for comparison after candidate inference. The
candidate backends do not receive Rekordbox cue labels, reference section times,
or benchmark match results while they are generating BPM, beatgrid, sections, or
cue points.

Normal `analyze-batch` generation follows the same truth boundary. It receives
only repository-manifest source metadata and source audio. Rekordbox XML remains
outside the normal artifact-generation path.

## What The Command Uses

Current project root:

```powershell
C:\Users\Brendan\Dev\AudioProj
```

Current Rekordbox XML example:

```powershell
C:\Users\Brendan\Desktop\all_songs.xml
```

The XML is the only required input path. The benchmark reads each track's audio
file location from the Rekordbox XML `TRACK Location=...` field. That means your
new XML must point to audio files that exist on this machine, such as files under:

```powershell
C:\Users\Brendan\Desktop\Music
C:\Users\Brendan\Music\AutoDJTest
```

The output will be written under:

```powershell
C:\Users\Brendan\Dev\AudioProj\.autodj-cache\semantic-section-benchmark\<run-name>
```

Each track gets its own folder with:

- `analysis.wav`: normalized WAV used by the models and best file to load into the HTML debugger for timeline-accurate playback.
- `dubstep-phrase-hybrid\analyzed-track.json`: sections, cue points, beatgrid, tempo, and evaluation-facing artifact.
- `dubstep-phrase-hybrid\debug-waveform.json`: RGB/debug waveform for the HTML debugger.
- `dubstep-phrase-hybrid\source-audio.mp3`: copied source MP3 beside the JSON artifacts for easier drag-and-drop playback in the HTML debugger.
- `dubstep-phrase-hybrid\section-evaluation.json`: per-track comparison against Rekordbox cue-derived reference sections.
- `semantic-section-benchmark-summary.json`: aggregate report for the full XML export.
- `benchmark-console.log`: terminal output captured from the run.

## Before You Run

1. In Rekordbox, export a new XML containing the songs you want to test.
2. Make sure the songs have cue labels that describe section starts and ends.
3. Use names like these where possible:

```text
intro_start
verse_1_start
build_1_start
drop_1_start
drop_1_end
break_start
verse_2_start
build_2_start
drop_2_start
drop_2_end
outro_start
```

The benchmark can still create artifacts without perfect labels, but the numeric
comparison is only meaningful when the Rekordbox cues can be mapped to section
labels.

For a first large-set pass, use 10-20 songs before trying a full 100-song
playlist. The first song usually pays model load cost; after that, expect roughly
45-90 seconds per song on the current GPU path, but this can vary with song
length and machine load.

## Recommended Large-Set Command

Open a new PowerShell terminal and run this whole block.

Change only `$RekordboxXmlWindows` if your new export has a different filename.

```powershell
cd C:\Users\Brendan\Dev\AudioProj

$ProjectRootWindows = "C:\Users\Brendan\Dev\AudioProj"
$RekordboxXmlWindows = "C:\Users\Brendan\Desktop\dubstep_collection_rekordbox.xml"
$RunName = "large-semantic-$(Get-Date -Format yyyyMMdd-HHmmss)"
$OutRoot = ".autodj-cache/semantic-section-benchmark/$RunName"
$OutRootWindows = Join-Path $ProjectRootWindows ($OutRoot -replace "/", "\")
$RunScriptWindows = Join-Path $OutRootWindows "run-benchmark.sh"

New-Item -ItemType Directory -Force -Path $OutRootWindows | Out-Null

$ProjectRootForWslPath = $ProjectRootWindows -replace "\\", "/"
$RekordboxXmlForWslPath = $RekordboxXmlWindows -replace "\\", "/"
$RunScriptForWslPath = $RunScriptWindows -replace "\\", "/"
$ProjectRootWsl = (wsl.exe -d Ubuntu-24.04 -- wslpath -a "$ProjectRootForWslPath").Trim()
$RekordboxXmlWsl = (wsl.exe -d Ubuntu-24.04 -- wslpath -a "$RekordboxXmlForWslPath").Trim()
$RunScriptWsl = (wsl.exe -d Ubuntu-24.04 -- wslpath -a "$RunScriptForWslPath").Trim()

Write-Host ""
Write-Host "Starting AutoDJ semantic benchmark..."
Write-Host "Rekordbox XML: $RekordboxXmlWindows"
Write-Host "Output folder: $OutRootWindows"
Write-Host "Console log: $(Join-Path $OutRootWindows 'benchmark-console.log')"
Write-Host ""

$RunScript = @"
#!/usr/bin/env bash
set -o pipefail
cd '$ProjectRootWsl'
source .venv-analysis/bin/activate
: > '$OutRoot/benchmark-console.log'
log() { echo "`$@" | tee -a '$OutRoot/benchmark-console.log'; }
log "[AutoDJ] `$(date -Iseconds) Starting semantic benchmark"
log "[AutoDJ] Project root: $ProjectRootWsl"
log "[AutoDJ] Rekordbox XML: $RekordboxXmlWsl"
log "[AutoDJ] Output root: $OutRoot"
log "[AutoDJ] Candidate: dubstep-phrase-hybrid"
log "[AutoDJ] Writing console log to: $OutRoot/benchmark-console.log"
PYTHONUNBUFFERED=1 stdbuf -oL -eL autodj-analysis benchmark-sections '$RekordboxXmlWsl' --out '$OutRoot' --candidates dubstep-phrase-hybrid --json 2>&1 | tee -a '$OutRoot/benchmark-console.log'
status=`${PIPESTATUS[0]}
log "[AutoDJ] `$(date -Iseconds) Benchmark command finished with status `$status"
exit `$status
"@

$RunScript = $RunScript -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($RunScriptWindows, $RunScript, [System.Text.UTF8Encoding]::new($false))
wsl.exe -d Ubuntu-24.04 -- bash "$RunScriptWsl"

Write-Host ""
Write-Host "Benchmark finished. Output folder:"
Write-Host $OutRootWindows
```

What this does:

- `cd C:\Users\Brendan\Dev\AudioProj` puts PowerShell in the repo.
- `$RekordboxXmlWindows` is the Rekordbox XML to benchmark.
- `$RunName` creates a unique output folder so old artifacts are not overwritten.
- `$ProjectRootForWslPath` and `$RekordboxXmlForWslPath` convert backslashes to forward slashes before calling `wslpath`. This matters because raw Windows backslashes can be stripped while crossing from PowerShell into WSL.
- `wslpath` converts normalized Windows paths like `C:/Users/...` into WSL paths like `/mnt/c/Users/...`.
- The `Write-Host` lines print the output folder before the expensive benchmark starts.
- `$RunScript` writes the actual Bash commands into `run-benchmark.sh` inside the output folder. This is more reliable from PowerShell than passing a long multiline string through `bash -lc`.
- `source .venv-analysis/bin/activate` activates the Python analysis environment inside WSL.
- `PYTHONUNBUFFERED=1` and `stdbuf -oL -eL` ask Python and native tools to flush output line-by-line where possible.
- `2>&1 | tee -a ...` prints benchmark output in the terminal and also appends it to `benchmark-console.log` in the run folder.
- `autodj-analysis benchmark-sections` runs the benchmark.
- `--candidates dubstep-phrase-hybrid` runs only the selected fused section candidate. This avoids also running standalone All-In-One and standalone SongFormer comparison candidates.
- `--json` prints the summary when the run finishes.
- Each candidate folder will include `source-audio.mp3` if the source file is an MP3 and is available on disk. This is copied for debugger convenience; it is not extra analysis input.

The script does not need `--section-backend`. That flag belongs to
`analyze-batch`, while this benchmark command selects section candidates with
`--candidates`.

## Normal Analyze-Batch After Task 16

Use the benchmark command above when you want Rekordbox comparison metrics and
ready-to-open debug viewer artifacts.

Use normal `analyze-batch` when you want to populate the app's metadata cache
from a repository manifest. After task 16, no extra semantic flag is required:

```powershell
cd C:\Users\Brendan\Dev\AudioProj

$ProjectRootWindows = "C:\Users\Brendan\Dev\AudioProj"
$ManifestWindows = "C:\Users\Brendan\Dev\AudioProj\local-audio\some-repository\repository-manifest.json"
$CacheRoot = ".autodj-cache/analysis/$(Get-Date -Format yyyyMMdd-HHmmss)"

$ProjectRootWsl = (wsl.exe -d Ubuntu-24.04 -- wslpath -a ($ProjectRootWindows -replace "\\", "/")).Trim()
$ManifestWsl = (wsl.exe -d Ubuntu-24.04 -- wslpath -a ($ManifestWindows -replace "\\", "/")).Trim()

wsl.exe -d Ubuntu-24.04 -- bash -lc "cd '$ProjectRootWsl' && source .venv-analysis/bin/activate && autodj-analysis analyze-batch '$ManifestWsl' --out '$CacheRoot' --json"
```

Notes for normal `analyze-batch`:

- Default semantic section backend is `dubstep-phrase-hybrid`.
- The current default parameters hash is
  `sha256:signal-v2-waveform-energy-tempo-dubstep-phrase-hybrid-v1`, so stale
  pre-task-16 artifacts should not be treated as fresh unless you override
  `--parameters-hash` manually.
- Normal `analyze-batch` writes
  `tracks\<track-id>\section-backend-work\analysis.wav` for semantic model
  input when possible.
- Normal `analyze-batch` does not copy `source-audio.mp3` or create
  `debug-waveform.json`; those are benchmark/debug conveniences.
- If you intentionally want the old rough section heuristic for a quick smoke
  test, add `--section-backend current-autodj-signal`.
- If `dubstep-phrase-hybrid` cannot run or emits no usable sections, the
  artifact falls back to `current-autodj-signal` rough sections and records the
  reason in `quality.warnings`.

## Open The Output Folder

After the command finishes, run:

```powershell
Start-Process explorer.exe $OutRootWindows
```

To list each track folder:

```powershell
Get-ChildItem -Directory $OutRootWindows | Select-Object Name
```

## Inspect The Aggregate Summary

Run this after the benchmark finishes:

```powershell
$SummaryPath = Join-Path $OutRootWindows "semantic-section-benchmark-summary.json"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

$Summary.candidateSummary | Format-Table `
  candidate, ok, failed, matchedSectionCount, missingReferenceSectionCount, `
  falsePositiveSectionCount, missedDropCount, falsePositiveDropCount, `
  medianStartErrorMilliseconds, medianEndErrorMilliseconds, processingSeconds
```

You want to look especially at:

- `missedDropCount`: should be 0 or very low.
- `falsePositiveDropCount`: should be 0 or very low.
- `medianStartErrorMilliseconds`: lower is better; around 10-20 ms matched the current known test set.
- `medianEndErrorMilliseconds`: lower is better, but some verse/break/outro label disagreements can inflate section-level metrics even when drop timing is correct.

For the current POC, do not reject a run only because every drop was not found.
The practical question is whether most tracks have at least one correct build
into one correct drop. Tracks with brick-wall waveforms or light/non-standard
dubstep may still fail semantic detection even when BPM and beatgrid are usable.

To print per-track paths and metrics:

```powershell
$Summary.cases | ForEach-Object {
  $candidate = $_.candidates[0]
  [PSCustomObject]@{
    Track = $_.trackId
    Analysis = $candidate.analyzedTrackPath
    Waveform = $candidate.debugWaveformPath
    Audio = $candidate.audioPath
    Matched = $candidate.matchedSectionCount
    Missing = $candidate.missingReferenceSectionCount
    FalsePositive = $candidate.falsePositiveSectionCount
    MissedDrops = $candidate.missedDropCount
    FalseDrops = $candidate.falsePositiveDropCount
    MedianStartMs = $candidate.medianStartErrorMilliseconds
    MedianEndMs = $candidate.medianEndErrorMilliseconds
  }
} | Format-Table -AutoSize
```

To quickly find songs that need manual inspection:

```powershell
$Summary.cases | ForEach-Object {
  $candidate = $_.candidates[0]
  if ($candidate.missedDropCount -gt 0 -or $candidate.falsePositiveDropCount -gt 0) {
    [PSCustomObject]@{
      Track = $_.trackName
      MissedDrops = $candidate.missedDropCount
      FalseDrops = $candidate.falsePositiveDropCount
      Analysis = $candidate.analyzedTrackPath
      Waveform = $candidate.debugWaveformPath
      Audio = $candidate.audioPath
    }
  }
} | Format-Table -AutoSize
```

## Load A Track In The HTML Debugger

Open the debug viewer:

```powershell
Start-Process (Join-Path $ProjectRootWindows "tools\analysis-debug-viewer.html")
```

For each track you want to inspect, load these three files into the viewer:

1. `analyzed-track.json`
2. `debug-waveform.json`
3. `source-audio.mp3`

`source-audio.mp3` is copied into the same `dubstep-phrase-hybrid` folder as the
JSON files so you do not have to hunt down the original song path. If playback
ever appears offset from the visual artifacts, fall back to the parent track
folder's `analysis.wav`. The benchmark models and waveform artifacts are built
on that normalized WAV timeline.

Example layout for one track:

```text
C:\Users\Brendan\Dev\AudioProj\.autodj-cache\semantic-section-benchmark\<run-name>\<track-id>\analysis.wav
C:\Users\Brendan\Dev\AudioProj\.autodj-cache\semantic-section-benchmark\<run-name>\<track-id>\dubstep-phrase-hybrid\analyzed-track.json
C:\Users\Brendan\Dev\AudioProj\.autodj-cache\semantic-section-benchmark\<run-name>\<track-id>\dubstep-phrase-hybrid\debug-waveform.json
C:\Users\Brendan\Dev\AudioProj\.autodj-cache\semantic-section-benchmark\<run-name>\<track-id>\dubstep-phrase-hybrid\source-audio.mp3
```

The easiest workflow is:

1. Open the run folder in Explorer.
2. Open a track folder.
3. Open `dubstep-phrase-hybrid`.
4. Drag `analyzed-track.json`, `debug-waveform.json`, and `source-audio.mp3` into the viewer.
5. Use zoom/pan/playback to check whether drop cues and section boundaries line up musically.

The viewer now draws beat markers and cue markers with a light halo over the RGB
waveform. Bar lines are thicker than regular beat lines, and semantic sections
use different colors for `build`, `drop`, `break`, `verse`, `intro`, and
`outro`.

## Optional: Run Standalone Candidate Comparison

Only use this when you want to compare raw All-In-One and raw SongFormer against
the hybrid. It is slower because it writes standalone candidate artifacts and the
hybrid still invokes both models internally.

```powershell
cd C:\Users\Brendan\Dev\AudioProj

$ProjectRootWindows = "C:\Users\Brendan\Dev\AudioProj"
$RekordboxXmlWindows = "C:\Users\Brendan\Desktop\all_songs.xml"
$RunName = "large-semantic-comparison-$(Get-Date -Format yyyyMMdd-HHmmss)"
$OutRoot = ".autodj-cache/semantic-section-benchmark/$RunName"
$OutRootWindows = Join-Path $ProjectRootWindows ($OutRoot -replace "/", "\")
$RunScriptWindows = Join-Path $OutRootWindows "run-benchmark.sh"

New-Item -ItemType Directory -Force -Path $OutRootWindows | Out-Null

$ProjectRootForWslPath = $ProjectRootWindows -replace "\\", "/"
$RekordboxXmlForWslPath = $RekordboxXmlWindows -replace "\\", "/"
$RunScriptForWslPath = $RunScriptWindows -replace "\\", "/"
$ProjectRootWsl = (wsl.exe -d Ubuntu-24.04 -- wslpath -a "$ProjectRootForWslPath").Trim()
$RekordboxXmlWsl = (wsl.exe -d Ubuntu-24.04 -- wslpath -a "$RekordboxXmlForWslPath").Trim()
$RunScriptWsl = (wsl.exe -d Ubuntu-24.04 -- wslpath -a "$RunScriptForWslPath").Trim()

Write-Host ""
Write-Host "Starting AutoDJ semantic benchmark comparison..."
Write-Host "Rekordbox XML: $RekordboxXmlWindows"
Write-Host "Output folder: $OutRootWindows"
Write-Host "Console log: $(Join-Path $OutRootWindows 'benchmark-console.log')"
Write-Host ""

$RunScript = @"
#!/usr/bin/env bash
set -o pipefail
cd '$ProjectRootWsl'
source .venv-analysis/bin/activate
: > '$OutRoot/benchmark-console.log'
log() { echo "`$@" | tee -a '$OutRoot/benchmark-console.log'; }
log "[AutoDJ] `$(date -Iseconds) Starting semantic benchmark comparison"
log "[AutoDJ] Project root: $ProjectRootWsl"
log "[AutoDJ] Rekordbox XML: $RekordboxXmlWsl"
log "[AutoDJ] Output root: $OutRoot"
log "[AutoDJ] Candidates: all-in-one-unlocked,songformer,dubstep-phrase-hybrid"
log "[AutoDJ] Writing console log to: $OutRoot/benchmark-console.log"
PYTHONUNBUFFERED=1 stdbuf -oL -eL autodj-analysis benchmark-sections '$RekordboxXmlWsl' --out '$OutRoot' --candidates all-in-one-unlocked,songformer,dubstep-phrase-hybrid --json 2>&1 | tee -a '$OutRoot/benchmark-console.log'
status=`${PIPESTATUS[0]}
log "[AutoDJ] `$(date -Iseconds) Benchmark command finished with status `$status"
exit `$status
"@

$RunScript = $RunScript -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($RunScriptWindows, $RunScript, [System.Text.UTF8Encoding]::new($false))
wsl.exe -d Ubuntu-24.04 -- bash "$RunScriptWsl"

Write-Host ""
Write-Host "Benchmark finished. Output folder:"
Write-Host $OutRootWindows
```

## Troubleshooting

If PowerShell says the XML does not exist, check this path:

```powershell
Test-Path $RekordboxXmlWindows
```

If the benchmark says an audio file is missing, the XML probably points to a
file path that is not available from WSL. Confirm the file exists in Windows and
is not cloud-only:

```powershell
Get-Item "C:\Users\Brendan\Desktop\Music\Some Song.mp3"
```

If WSL cannot find Python dependencies, verify the venv from PowerShell:

```powershell
wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python --version && autodj-analysis --help'
```

If the terminal looks paused, wait. All-In-One demixing and SongFormer model
loading sometimes produce long quiet periods, especially on the first track.

If `source-audio.mp3` is missing from a candidate folder, the source file may not
have been an MP3 or may not have been available at copy time. Use the parent
track folder's `analysis.wav` in the HTML viewer instead:

```powershell
Get-ChildItem $OutRootWindows -Recurse -Filter analysis.wav | Select-Object FullName
```

If you want to cancel a run, press `Ctrl+C` in the PowerShell terminal. The
partial output folder can be deleted later if you do not need it.
