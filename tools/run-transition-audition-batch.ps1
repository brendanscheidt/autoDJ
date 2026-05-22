param(
    [string]$ProjectRoot = "C:\Users\Brendan\Dev\AudioProj",
    [string]$AudioFolder = "C:\Users\Brendan\Desktop\AutoDJTestDubstep",
    [string]$ExistingAnalysisRoot = "",
    [string]$RunName = "transition-audition-$(Get-Date -Format yyyyMMdd-HHmmss)",
    [int]$DropSwitchCount = 10,
    [int]$ReverbExitCount = 10,
    [double]$MinNudgeConfidence = 0.58,
    [double]$MaxNudgeAnchorDisagreementMs = 30.0,
    [bool]$ForceAnalysis = $true,
    [switch]$RequireStrongNudge,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

function To-WslPath([string]$Path) {
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    return (wsl.exe -d Ubuntu-24.04 -- wslpath -a ($fullPath -replace "\\", "/")).Trim()
}

function Invoke-WslAnalysis([string]$Command) {
    wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && $Command"
    if ($LASTEXITCODE -ne 0) {
        throw "WSL command failed with exit code $LASTEXITCODE`: $Command"
    }
}

function New-SafeTrackId([string]$Name, [hashtable]$UsedIds) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($Name).ToLowerInvariant()
    $base = [regex]::Replace($base, "[^a-z0-9]+", "-").Trim("-")
    if ([string]::IsNullOrWhiteSpace($base)) {
        $base = "track"
    }
    $candidate = $base
    $suffix = 2
    while ($UsedIds.ContainsKey($candidate)) {
        $candidate = "$base-$suffix"
        $suffix += 1
    }
    $UsedIds[$candidate] = $true
    return $candidate
}

function Read-JsonFile([string]$Path) {
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Write-JsonFile([string]$Path, $Value) {
    $json = $Value | ConvertTo-Json -Depth 64
    [System.IO.File]::WriteAllText($Path, $json, [System.Text.UTF8Encoding]::new($false))
}

function NumberOrZero($Value) {
    if ($null -eq $Value) {
        return 0.0
    }
    return [double]$Value
}

function SourceAtTimeline($Placement, [double]$TimelineSeconds) {
    $placementTimelineStart = NumberOrZero $Placement.timelineStartSeconds
    $placementSourceStart = NumberOrZero $Placement.sourceStartSeconds
    if ($TimelineSeconds -lt $placementTimelineStart) {
        return [Math]::Max(0.0, $placementSourceStart)
    }
    return [Math]::Max(0.0, $placementSourceStart + ($TimelineSeconds - $placementTimelineStart))
}

function Add-LaneKeyframe([hashtable]$Lanes, [string]$Deck, [string]$Control, [double]$SourceSeconds, [double]$Value, [string]$Interpolation) {
    $key = "$Deck|$Control"
    if (-not $Lanes.ContainsKey($key)) {
        $Lanes[$key] = [ordered]@{
            deck = $Deck
            control = $Control
            keyframes = @()
        }
    }
    $clamped = [Math]::Max(0.0, [Math]::Min(1.0, $Value))
    $Lanes[$key].keyframes += [ordered]@{
        sourceSeconds = [Math]::Round($SourceSeconds, 6)
        value = [Math]::Round($clamped, 6)
        interpolation = if ([string]::IsNullOrWhiteSpace($Interpolation)) { "linear" } else { $Interpolation }
    }
}

function Test-NudgeQuality($NudgeSummary, [double]$MinConfidence, [double]$MaxAnchorDisagreementMs) {
    if ($null -eq $NudgeSummary -or $NudgeSummary.ok -ne $true) {
        return $false
    }
    if ((NumberOrZero $NudgeSummary.confidence) -lt $MinConfidence) {
        return $false
    }
    $nudges = @($NudgeSummary.anchorNudges | ForEach-Object { NumberOrZero $_.nudgeSeconds })
    if ($nudges.Count -ge 2) {
        $min = ($nudges | Measure-Object -Minimum).Minimum
        $max = ($nudges | Measure-Object -Maximum).Maximum
        if ((($max - $min) * 1000.0) -gt $MaxAnchorDisagreementMs) {
            return $false
        }
    }
    return $true
}

function Get-NudgeAnchorDisagreementMs($NudgeSummary) {
    if ($null -eq $NudgeSummary) {
        return 0.0
    }
    $nudges = @($NudgeSummary.anchorNudges | ForEach-Object { NumberOrZero $_.nudgeSeconds })
    if ($nudges.Count -lt 2) {
        return 0.0
    }
    $min = ($nudges | Measure-Object -Minimum).Minimum
    $max = ($nudges | Measure-Object -Maximum).Maximum
    return ($max - $min) * 1000.0
}

function New-AuthoringSessionFromMixPlan(
    [string]$MixPlanPath,
    [string]$SessionPath,
    [hashtable]$ArtifactsByTrackId,
    [string]$SessionId,
    [string]$TransitionFamily,
    [string]$Notes
) {
    $plan = Read-JsonFile $MixPlanPath
    if (-not $plan.transitions -or $plan.transitions.Count -lt 1) {
        throw "MixPlan has no transition: $MixPlanPath"
    }
    $transition = $plan.transitions[0]
    $fromPlacement = @($plan.tracks | Where-Object { $_.placementId -eq $transition.fromPlacementId })[0]
    $toPlacement = @($plan.tracks | Where-Object { $_.placementId -eq $transition.toPlacementId })[0]
    if ($null -eq $fromPlacement -or $null -eq $toPlacement) {
        throw "MixPlan transition placements are missing: $MixPlanPath"
    }

    $fromInfo = $ArtifactsByTrackId[[string]$fromPlacement.trackId]
    $toInfo = $ArtifactsByTrackId[[string]$toPlacement.trackId]
    if ($null -eq $fromInfo -or $null -eq $toInfo) {
        throw "Missing artifact info for session export: $($fromPlacement.trackId) -> $($toPlacement.trackId)"
    }

    $origin = NumberOrZero $transition.timelineStartSeconds
    $deckMapByPlanDeck = @{}
    $deckMapByPlanDeck[[string]$fromPlacement.deck] = "a"
    $deckMapByPlanDeck[[string]$toPlacement.deck] = "b"
    $placementBySessionDeck = @{
        a = $fromPlacement
        b = $toPlacement
    }

    $deckAOrigin = SourceAtTimeline $fromPlacement ([Math]::Max($origin, $(NumberOrZero $fromPlacement.timelineStartSeconds)))
    $deckBOrigin = SourceAtTimeline $toPlacement ([Math]::Max($origin, $(NumberOrZero $toPlacement.timelineStartSeconds)))
    $deckBDelay = [Math]::Max(0.0, $(NumberOrZero $toPlacement.timelineStartSeconds) - $origin)

    $lanes = @{}
    foreach ($command in @($plan.commands)) {
        if ([string]$command.type -ne "automate") {
            continue
        }
        $control = [string]$command.control
        if ($control -eq "crossfader" -or $null -eq $command.deck) {
            continue
        }
        $sessionDeck = $deckMapByPlanDeck[[string]$command.deck]
        if ([string]::IsNullOrWhiteSpace($sessionDeck)) {
            continue
        }
        $placement = $placementBySessionDeck[$sessionDeck]
        foreach ($keyframe in @($command.keyframes)) {
            $sourceSeconds = SourceAtTimeline $placement $(NumberOrZero $keyframe.at)
            Add-LaneKeyframe $lanes $sessionDeck $control $sourceSeconds $(NumberOrZero $keyframe.value) ([string]$keyframe.interpolation)
        }
    }

    $anchors = @()
    if ($transition.sourceAnchors) {
        foreach ($property in $transition.sourceAnchors.PSObject.Properties) {
            $anchor = $property.Value
            $deck = if ([string]$anchor.trackId -eq [string]$fromPlacement.trackId) { "a" } elseif ([string]$anchor.trackId -eq [string]$toPlacement.trackId) { "b" } else { "" }
            if ([string]::IsNullOrWhiteSpace($deck)) {
                continue
            }
            $semanticRef = ""
            if ($anchor.sectionId) {
                $semanticRef = [string]$anchor.sectionId
            } elseif ($anchor.cueId) {
                $semanticRef = [string]$anchor.cueId
            }
            $anchors += [ordered]@{
                name = [string]$property.Name
                deck = $deck
                sourceSeconds = [Math]::Round((NumberOrZero $anchor.sourceSeconds), 6)
                semanticRef = $semanticRef
            }
        }
    }

    foreach ($lane in $lanes.Values) {
        $lane.keyframes = @($lane.keyframes | Sort-Object sourceSeconds)
    }

    $session = [ordered]@{
        schemaVersion = "1.0.0"
        sessionId = $SessionId
        createdAtUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        transitionFamily = $TransitionFamily
        notes = $Notes
        decks = @(
            [ordered]@{
                deck = "a"
                trackId = [string]$fromPlacement.trackId
                audioPath = [string]$fromInfo.sourceAudioPath
                analyzedTrackPath = [string]$fromInfo.analyzedTrackPath
                debugWaveformPath = [string]$fromInfo.debugWaveformPath
                centerSeconds = [Math]::Round($deckAOrigin, 6)
                previewStartDelaySeconds = 0.0
                zoomSeconds = 64.0
            },
            [ordered]@{
                deck = "b"
                trackId = [string]$toPlacement.trackId
                audioPath = [string]$toInfo.sourceAudioPath
                analyzedTrackPath = [string]$toInfo.analyzedTrackPath
                debugWaveformPath = [string]$toInfo.debugWaveformPath
                centerSeconds = [Math]::Round($deckBOrigin, 6)
                previewStartDelaySeconds = [Math]::Round($deckBDelay, 6)
                zoomSeconds = 64.0
            }
        )
        anchors = $anchors
        lanes = @($lanes.Values)
    }
    Write-JsonFile $SessionPath $session
}

function Invoke-PythonCli([string]$Subcommand, [string[]]$Arguments) {
    $joined = @($Subcommand) + $Arguments
    $escaped = $joined | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }
    Invoke-WslAnalysis ("autodj-analysis " + ($escaped -join " "))
}

function Get-ArtifactSourceUri($Artifact) {
    if ($null -ne $Artifact.source -and -not [string]::IsNullOrWhiteSpace([string]$Artifact.source.sourceUri)) {
        return [string]$Artifact.source.sourceUri
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$Artifact.sourceUri)) {
        return [string]$Artifact.sourceUri
    }
    return ""
}

function Resolve-SourceAudioPath([string]$TrackDir, $Artifact, [string]$AudioFolder) {
    $copied = @(Get-ChildItem -LiteralPath $TrackDir -File -Filter "source-audio.*" -ErrorAction SilentlyContinue | Sort-Object Name)
    if ($copied.Count -gt 0) {
        return $copied[0].FullName
    }

    $sourceUri = Get-ArtifactSourceUri $Artifact
    if (-not [string]::IsNullOrWhiteSpace($sourceUri)) {
        if ([System.IO.Path]::IsPathRooted($sourceUri) -and (Test-Path -LiteralPath $sourceUri)) {
            return [System.IO.Path]::GetFullPath($sourceUri)
        }

        $audioFolderCandidate = Join-Path $AudioFolder $sourceUri
        if (Test-Path -LiteralPath $audioFolderCandidate) {
            return [System.IO.Path]::GetFullPath($audioFolderCandidate)
        }
    }

    throw "Could not resolve source audio for analyzed track in $TrackDir. Expected source-audio.* beside the artifacts, or a sourceUri that exists under $AudioFolder."
}

function Read-ExistingAnalysisRows([string]$AnalysisRoot, [string]$AudioFolder) {
    $tracksRoot = Join-Path $AnalysisRoot "tracks"
    if (-not (Test-Path -LiteralPath $tracksRoot)) {
        throw "Existing analysis root does not contain a tracks folder: $tracksRoot"
    }

    $rows = @()
    $trackDirs = @(Get-ChildItem -LiteralPath $tracksRoot -Directory | Sort-Object Name)
    foreach ($trackDir in $trackDirs) {
        $analyzedTrackPath = Join-Path $trackDir.FullName "analyzed-track.json"
        $waveformPath = Join-Path $trackDir.FullName "waveform.json"
        $debugWaveformPath = Join-Path $trackDir.FullName "debug-waveform.json"
        if (-not (Test-Path -LiteralPath $analyzedTrackPath)) {
            continue
        }
        if (-not (Test-Path -LiteralPath $debugWaveformPath)) {
            throw "Existing analysis track is missing debug-waveform.json: $($trackDir.FullName)"
        }

        $artifact = Read-JsonFile $analyzedTrackPath
        $sourceAudioPath = Resolve-SourceAudioPath $trackDir.FullName $artifact $AudioFolder
        $sourceUri = Get-ArtifactSourceUri $artifact
        $fileName = if ([string]::IsNullOrWhiteSpace($sourceUri)) {
            [System.IO.Path]::GetFileName($sourceAudioPath)
        } else {
            [System.IO.Path]::GetFileName($sourceUri)
        }
        $rows += [pscustomobject]@{
            trackId = $trackDir.Name
            fileName = $fileName
            audioPath = $sourceAudioPath
            sourceAudioPath = $sourceAudioPath
            analyzedTrackPath = $analyzedTrackPath
            waveformPath = $waveformPath
            debugWaveformPath = $debugWaveformPath
            bpmKey = "{0:0.###}" -f $(NumberOrZero $artifact.tempo.normalizedBpm)
            contentHash = if ($artifact.analysis -and $artifact.analysis.sourceContentHash) { [string]$artifact.analysis.sourceContentHash } else { "" }
        }
    }

    if ($rows.Count -lt 2) {
        throw "Existing analysis root must contain at least two analyzed tracks: $AnalysisRoot"
    }
    return $rows
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$AudioFolder = [System.IO.Path]::GetFullPath($AudioFolder)
$OutputRoot = Join-Path $ProjectRoot ".autodj-cache\transition-auditions\$RunName"
$UsingExistingAnalysis = -not [string]::IsNullOrWhiteSpace($ExistingAnalysisRoot)
$AnalysisRoot = if ($UsingExistingAnalysis) {
    [System.IO.Path]::GetFullPath($ExistingAnalysisRoot)
} else {
    Join-Path $OutputRoot "analysis"
}
$TransitionsRoot = Join-Path $OutputRoot "transitions"
$SessionsRoot = Join-Path $OutputRoot "sessions"
$ManifestDir = Join-Path $OutputRoot "manifest"

if ($UsingExistingAnalysis) {
    New-Item -ItemType Directory -Force -Path $TransitionsRoot, $SessionsRoot | Out-Null
} else {
    New-Item -ItemType Directory -Force -Path $AnalysisRoot, $TransitionsRoot, $SessionsRoot, $ManifestDir | Out-Null
}

if (-not $SkipBuild) {
    Push-Location $ProjectRoot
    try {
        cmake --build --preset debug --target autodj_mixplan_poc autodj_desktop
        if ($LASTEXITCODE -ne 0) {
            throw "CMake build failed"
        }
    } finally {
        Pop-Location
    }
}

$MixPlanTool = Join-Path $ProjectRoot "build\debug\core\dj\Debug\autodj_mixplan_poc.exe"
$AutoDjExe = Join-Path $ProjectRoot "build\debug\apps\autodj-desktop\autodj_desktop_artefacts\Debug\AutoDJ.exe"
if (-not (Test-Path -LiteralPath $MixPlanTool)) {
    throw "Missing planner tool: $MixPlanTool"
}

if ($UsingExistingAnalysis) {
    Write-Host "Using existing analysis root: $AnalysisRoot"
    $trackRows = @(Read-ExistingAnalysisRows $AnalysisRoot $AudioFolder)
    Write-Host "Loaded analyzed tracks: $($trackRows.Count)"
} else {
    $supported = @(".mp3", ".wav", ".flac", ".m4a", ".aif", ".aiff", ".ogg")
    $audioFiles = @(Get-ChildItem -LiteralPath $AudioFolder -File | Where-Object { $supported -contains $_.Extension.ToLowerInvariant() } | Sort-Object Name)
    if ($audioFiles.Count -lt 2) {
        throw "Need at least two audio files in $AudioFolder"
    }

    $usedIds = @{}
    $trackRows = @()
    foreach ($file in $audioFiles) {
        $trackId = New-SafeTrackId $file.Name $usedIds
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
        $trackRows += [pscustomobject]@{
            trackId = $trackId
            fileName = $file.Name
            audioPath = $file.FullName
            sourceAudioPath = ""
            analyzedTrackPath = Join-Path $AnalysisRoot "tracks\$trackId\analyzed-track.json"
            waveformPath = Join-Path $AnalysisRoot "tracks\$trackId\waveform.json"
            debugWaveformPath = Join-Path $AnalysisRoot "tracks\$trackId\debug-waveform.json"
            bpmKey = ""
            contentHash = "sha256:$hash"
        }
    }

    $manifest = [ordered]@{
        schemaVersion = "1.0.0"
        repositoryId = "autodj-transition-audition-batch"
        producer = "tools/run-transition-audition-batch.ps1"
        producerVersion = "1.0.0"
        createdAtUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        source = @{
            repositoryType = "local"
            rootUri = To-WslPath $AudioFolder
        }
        tracks = @($trackRows | ForEach-Object {
            [ordered]@{
                trackId = $_.trackId
                repositoryId = "autodj-transition-audition-batch"
                sourceUri = $_.fileName
                contentHash = $_.contentHash
                title = [System.IO.Path]::GetFileNameWithoutExtension($_.fileName)
                formatHint = $_.fileName.Split(".")[-1].ToLowerInvariant()
            }
        })
    }
    $ManifestPath = Join-Path $ManifestDir "repository-manifest.json"
    Write-JsonFile $ManifestPath $manifest

    $manifestWsl = To-WslPath $ManifestPath
    $analysisWsl = To-WslPath $AnalysisRoot
    $forceArg = if ($ForceAnalysis) { " --force" } else { "" }
    Invoke-WslAnalysis "autodj-analysis analyze-batch '$manifestWsl' --out '$analysisWsl'$forceArg --section-backend dubstep-phrase-hybrid --json | tee '$analysisWsl/analyze-summary.json'"

    foreach ($row in $trackRows) {
        $trackDir = Split-Path -Parent $row.analyzedTrackPath
        New-Item -ItemType Directory -Force -Path $trackDir | Out-Null
        $sourceCopy = Join-Path $trackDir ("source-audio" + [System.IO.Path]::GetExtension($row.audioPath).ToLowerInvariant())
        Copy-Item -LiteralPath $row.audioPath -Destination $sourceCopy -Force
        $row.sourceAudioPath = $sourceCopy

        $sourceCopyWsl = To-WslPath $sourceCopy
        $debugWsl = To-WslPath $row.debugWaveformPath
        Invoke-WslAnalysis "autodj-analysis debug-waveform '$sourceCopyWsl' --out '$debugWsl' --track-id '$($row.trackId)' --points 32768"

        $artifact = Read-JsonFile $row.analyzedTrackPath
        $row.bpmKey = "{0:0.###}" -f $(NumberOrZero $artifact.tempo.normalizedBpm)
    }
}

$artifactsByTrackId = @{}
foreach ($row in $trackRows) {
    $artifactsByTrackId[$row.trackId] = $row
}

function Try-CreateTransition([string]$Kind, [int]$Index, $Outgoing, $Incoming) {
    $safeName = "{0}-{1:000}-{2}-to-{3}" -f $Kind, $Index, $Outgoing.trackId, $Incoming.trackId
    $transitionDir = Join-Path $TransitionsRoot $safeName
    New-Item -ItemType Directory -Force -Path $transitionDir | Out-Null

    & $MixPlanTool --out $transitionDir --plan-id $safeName --json $Outgoing.analyzedTrackPath $Incoming.analyzedTrackPath | Tee-Object -FilePath (Join-Path $transitionDir "planner-stdout.json") | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $transitionDir -Recurse -Force -ErrorAction SilentlyContinue
        return $false
    }

    $summaryPath = Join-Path $transitionDir "planner-summary.json"
    $summary = Read-JsonFile $summaryPath
    $expectedTemplate = if ($Kind -eq "drop-switch") { "second_build_drop_switch_v1" } else { "drop_end_reverb_exit_v1" }
    if ($summary.selectedTemplateId -ne $expectedTemplate) {
        Remove-Item -LiteralPath $transitionDir -Recurse -Force -ErrorAction SilentlyContinue
        return $false
    }

    $rawPlan = Join-Path $transitionDir "mix-plan.json"
    $finalPlan = $rawPlan
    if ($Kind -eq "drop-switch") {
        $nudgedPlan = Join-Path $transitionDir "mix-plan-nudged.json"
        $rawPlanWsl = To-WslPath $rawPlan
        $nudgedPlanWsl = To-WslPath $nudgedPlan
        $assetRootWsl = To-WslPath $AudioFolder
        try {
            Invoke-WslAnalysis "autodj-analysis nudge-mixplan '$rawPlanWsl' --out '$nudgedPlanWsl' --asset-root '$assetRootWsl' --window-ms 80 --max-nudge-ms 80 --json | tee '$(To-WslPath (Join-Path $transitionDir "nudge-summary.json"))'" | Out-Host
        } catch {
            Write-Warning "Skipping $safeName because transient nudge failed: $_"
            Remove-Item -LiteralPath $transitionDir -Recurse -Force -ErrorAction SilentlyContinue
            return $false
        }
        $nudgeSummary = Read-JsonFile (Join-Path $transitionDir "nudge-summary.json")
        if (-not (Test-NudgeQuality $nudgeSummary $MinNudgeConfidence $MaxNudgeAnchorDisagreementMs)) {
            $disagreementMs = [Math]::Round((Get-NudgeAnchorDisagreementMs $nudgeSummary), 3)
            $message = "Transient nudge quality is weak for $safeName. Confidence=$($nudgeSummary.confidence), nudgeMs=$($nudgeSummary.nudgeMilliseconds), anchorDisagreementMs=$disagreementMs"
            if ($RequireStrongNudge) {
                Write-Warning "Skipping $safeName because $message"
                Remove-Item -LiteralPath $transitionDir -Recurse -Force -ErrorAction SilentlyContinue
                return $false
            }
            Write-Warning "Keeping $safeName even though $message"
        }

        $gainPlan = Join-Path $transitionDir "mix-plan-gain-planned.json"
        $gainReport = Join-Path $transitionDir "energy-report.json"
        $gainPlanWsl = To-WslPath $gainPlan
        $gainReportWsl = To-WslPath $gainReport
        try {
            Invoke-WslAnalysis "autodj-analysis gain-plan-drop-switch '$nudgedPlanWsl' --out '$gainPlanWsl' --report '$gainReportWsl' --asset-root '$assetRootWsl' --json | tee '$(To-WslPath (Join-Path $transitionDir "gain-plan-summary.json"))'" | Out-Host
            $finalPlan = $gainPlan
        } catch {
            Write-Warning "Using nudged plan without gain planning for $safeName because gain planning failed: $_"
            $finalPlan = $nudgedPlan
        }
    }

    $finalCopy = Join-Path $transitionDir "mix-plan-final.json"
    Copy-Item -LiteralPath $finalPlan -Destination $finalCopy -Force

    $renderDir = Join-Path $transitionDir "render"
    New-Item -ItemType Directory -Force -Path $renderDir | Out-Null
    try {
        Invoke-WslAnalysis "autodj-analysis render-mixplan '$(To-WslPath $finalCopy)' --out '$(To-WslPath $renderDir)' --asset-root '$(To-WslPath $AudioFolder)' --json | tee '$(To-WslPath (Join-Path $renderDir "render-stdout.json"))'" | Out-Host
    } catch {
        Write-Warning "Skipping $safeName because render failed: $_"
        Remove-Item -LiteralPath $transitionDir -Recurse -Force -ErrorAction SilentlyContinue
        return $false
    }

    $sessionName = "$safeName.transition-authoring-session.json"
    $sessionPath = Join-Path $SessionsRoot $sessionName
    $family = if ($Kind -eq "drop-switch") { "drop_switch" } else { "reverb_exit" }
    New-AuthoringSessionFromMixPlan $finalCopy $sessionPath $artifactsByTrackId $safeName $family "Generated batch audition from $($Outgoing.trackId) to $($Incoming.trackId). MixPlan: $finalCopy"
    Copy-Item -LiteralPath $sessionPath -Destination (Join-Path $transitionDir $sessionName) -Force
    return $true
}

function New-PairCandidates([bool]$RequireSameBpm) {
    $pairs = @()
    for ($offset = 1; $offset -lt $trackRows.Count; $offset += 1) {
        for ($index = 0; $index -lt $trackRows.Count; $index += 1) {
            $outgoing = $trackRows[$index]
            $incoming = $trackRows[($index + $offset) % $trackRows.Count]
            if ($outgoing.trackId -eq $incoming.trackId) {
                continue
            }
            $sameBpm = $outgoing.bpmKey -eq $incoming.bpmKey
            if ($RequireSameBpm -and -not $sameBpm) {
                continue
            }
            if (-not $RequireSameBpm -and $sameBpm) {
                continue
            }
            $pairs += [pscustomobject]@{
                outgoing = $outgoing
                incoming = $incoming
            }
        }
    }
    return $pairs
}

$dropMade = 0
foreach ($pair in @(New-PairCandidates $true)) {
    if ($dropMade -ge $DropSwitchCount) { break }
    if (Try-CreateTransition "drop-switch" ($dropMade + 1) $pair.outgoing $pair.incoming) {
        $dropMade += 1
    }
}

$reverbMade = 0
foreach ($pair in @(New-PairCandidates $false)) {
    if ($reverbMade -ge $ReverbExitCount) { break }
    if (Try-CreateTransition "reverb-exit" ($reverbMade + 1) $pair.outgoing $pair.incoming) {
        $reverbMade += 1
    }
}

$runSummary = [ordered]@{
    ok = ($dropMade -eq $DropSwitchCount -and $reverbMade -eq $ReverbExitCount)
    runName = $RunName
    outputRoot = $OutputRoot
    analysisRoot = $AnalysisRoot
    sessionsRoot = $SessionsRoot
    transitionsRoot = $TransitionsRoot
    audioFolder = $AudioFolder
    usingExistingAnalysis = $UsingExistingAnalysis
    existingAnalysisRoot = if ($UsingExistingAnalysis) { $AnalysisRoot } else { "" }
    dropSwitchRequested = $DropSwitchCount
    dropSwitchCreated = $dropMade
    reverbExitRequested = $ReverbExitCount
    reverbExitCreated = $reverbMade
    minNudgeConfidence = $MinNudgeConfidence
    maxNudgeAnchorDisagreementMs = $MaxNudgeAnchorDisagreementMs
    requireStrongNudge = [bool]$RequireStrongNudge
    autoDjExe = $AutoDjExe
}
Write-JsonFile (Join-Path $OutputRoot "run-summary.json") $runSummary

Write-Host ""
Write-Host "Batch complete."
Write-Host "Output root: $OutputRoot"
Write-Host "Sessions to import: $SessionsRoot"
Write-Host "Transitions/renders: $TransitionsRoot"
Write-Host "Drop switches created: $dropMade / $DropSwitchCount"
Write-Host "Reverb exits created: $reverbMade / $ReverbExitCount"
Write-Host "AutoDJ exe: $AutoDjExe"
