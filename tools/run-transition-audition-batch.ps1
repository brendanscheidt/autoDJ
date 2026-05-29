param(
    [string]$ProjectRoot = "C:\Users\Brendan\Dev\AudioProj",
    [string]$AudioFolder = "C:\Users\Brendan\Desktop\AutoDJTestDubstep",
    [string]$ExistingAnalysisRoot = "",
    [string]$DropSwitchPairListPath = "",
    [string]$RunName = "transition-audition-$(Get-Date -Format yyyyMMdd-HHmmss)",
    [int]$DropSwitchCount = 10,
    [Alias("WashOutCount")]
    [int]$ReverbExitCount = 10,
    [int]$AnalysisWorkers = 2,
    [ValidateSet("current-autodj-signal", "dubstep-phrase-hybrid")]
    [string]$AnalysisSectionBackend = "current-autodj-signal",
    [ValidateSet("keyfinder", "selected-madmom-keyfinder", "madmom-cnn-key")]
    [string]$AnalysisKeyBackend = "keyfinder",
    [double]$MinNudgeConfidence = 0.58,
    [double]$MaxNudgeAnchorDisagreementMs = 30.0,
    [bool]$ForceAnalysis = $true,
    [switch]$RequireStrongNudge,
    [switch]$RequireRekordboxSemanticTruth,
    [ValidateSet("compatible", "score", "off")]
    [string]$DropSwitchKeyPolicy = "compatible",
    [ValidateSet("exact-then-stretch", "exact", "stretch")]
    [string]$DropSwitchTempoPolicy = "exact-then-stretch",
    [double]$MaxTempoAdjustmentBpmPerDeck = 10.0,
    [string]$TempoStretchBackend = "soundstretch",
    [string]$TempoStretchQuality = "standard",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

function To-WslPath([string]$Path) {
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    return (wsl.exe -d Ubuntu-24.04 -- wslpath -a ($fullPath -replace "\\", "/")).Trim()
}

function Invoke-WslAnalysis([string]$Command) {
    wsl.exe -d Ubuntu-24.04 -- bash -lc "set -o pipefail; cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && $Command"
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

function Get-ShortHash([string]$Text) {
    $sha1 = [System.Security.Cryptography.SHA1]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        $hash = $sha1.ComputeHash($bytes)
        return ([System.BitConverter]::ToString($hash).Replace("-", "").Substring(0, 8)).ToLowerInvariant()
    } finally {
        $sha1.Dispose()
    }
}

function Shorten-IdPart([string]$Text, [int]$MaxLength = 30) {
    $safe = [regex]::Replace($Text.ToLowerInvariant(), "[^a-z0-9]+", "-").Trim("-")
    if ([string]::IsNullOrWhiteSpace($safe)) {
        return "track"
    }
    if ($safe.Length -le $MaxLength) {
        return $safe
    }
    return $safe.Substring(0, $MaxLength).Trim("-")
}

function New-TransitionSafeName([string]$Kind, [int]$Index, [string]$OutgoingTrackId, [string]$IncomingTrackId) {
    $outShort = Shorten-IdPart $OutgoingTrackId
    $inShort = Shorten-IdPart $IncomingTrackId
    $hash = Get-ShortHash "$Kind|$Index|$OutgoingTrackId|$IncomingTrackId"
    return "{0}-{1:000}-{2}-to-{3}-{4}" -f $Kind, $Index, $outShort, $inShort, $hash
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

function Format-InvariantNumber([double]$Value) {
    return $Value.ToString("R", [System.Globalization.CultureInfo]::InvariantCulture)
}

function Parse-CamelotKey([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }
    $trimmed = $Value.Trim().ToUpperInvariant()
    $match = [regex]::Match($trimmed, "^(?<number>1[0-2]|[1-9])(?<letter>[AB])$")
    if (-not $match.Success) {
        return $null
    }
    return [pscustomobject]@{
        number = [int]$match.Groups["number"].Value
        letter = [string]$match.Groups["letter"].Value
        value = $trimmed
    }
}

function Test-AdjacentCamelotNumber([int]$First, [int]$Second) {
    return (($First % 12) + 1 -eq $Second) -or (($Second % 12) + 1 -eq $First)
}

function Get-KeyCompatibility($Outgoing, $Incoming) {
    $minimumConfidence = 0.65
    if ([string]::IsNullOrWhiteSpace([string]$Outgoing.camelotKey) -or [string]::IsNullOrWhiteSpace([string]$Incoming.camelotKey)) {
        return [pscustomobject]@{
            classification = "unknown"
            score = 0.4
            compatible = $false
            reason = "missing_key"
        }
    }
    if ((NumberOrZero $Outgoing.keyConfidence) -lt $minimumConfidence -or (NumberOrZero $Incoming.keyConfidence) -lt $minimumConfidence) {
        return [pscustomobject]@{
            classification = "unknown"
            score = 0.45
            compatible = $false
            reason = "low_key_confidence"
        }
    }

    $first = Parse-CamelotKey ([string]$Outgoing.camelotKey)
    $second = Parse-CamelotKey ([string]$Incoming.camelotKey)
    if ($null -eq $first -or $null -eq $second) {
        return [pscustomobject]@{
            classification = "unknown"
            score = 0.4
            compatible = $false
            reason = "invalid_camelot_key"
        }
    }
    if ($first.value -eq $second.value) {
        return [pscustomobject]@{
            classification = "perfect"
            score = 1.0
            compatible = $true
            reason = "same_camelot_key"
        }
    }
    if ($first.number -eq $second.number -and $first.letter -ne $second.letter) {
        return [pscustomobject]@{
            classification = "relative"
            score = 0.9
            compatible = $true
            reason = "same_number_opposite_mode"
        }
    }
    if ($first.letter -eq $second.letter -and (Test-AdjacentCamelotNumber $first.number $second.number)) {
        return [pscustomobject]@{
            classification = "adjacent"
            score = 0.8
            compatible = $true
            reason = "neighboring_camelot_number_same_mode"
        }
    }
    return [pscustomobject]@{
        classification = "clash"
        score = 0.0
        compatible = $false
        reason = "distant_camelot_key"
    }
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

function Get-FieldValue($Value, [string[]]$Names) {
    if ($null -eq $Value) {
        return ""
    }
    foreach ($name in $Names) {
        $property = $Value.PSObject.Properties[$name]
        if ($null -ne $property -and -not [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            return [string]$property.Value
        }
    }
    return ""
}

function Read-DropSwitchPairList([string]$Path, [hashtable]$RowsByTrackId) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return @()
    }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $fullPath)) {
        throw "Drop switch pair list does not exist: $fullPath"
    }
    $extension = [System.IO.Path]::GetExtension($fullPath).ToLowerInvariant()
    if ($extension -eq ".json") {
        $payload = Read-JsonFile $fullPath
        $rows = @($payload)
        if ($rows.Count -eq 1 -and $rows[0] -is [System.Array]) {
            $expandedRows = @()
            foreach ($item in $rows[0]) {
                $expandedRows += $item
            }
            $rows = $expandedRows
        }
    } elseif ($extension -eq ".csv") {
        $rows = @(Import-Csv -LiteralPath $fullPath)
    } else {
        throw "Unsupported drop switch pair list format: $fullPath. Use JSON or CSV."
    }
    $pairs = @()
    foreach ($row in $rows) {
        $outgoingId = Get-FieldValue $row @("outgoing", "outgoingTrackId", "songA", "song_a", "from")
        $incomingId = Get-FieldValue $row @("incoming", "incomingTrackId", "songB", "song_b", "to")
        if ([string]::IsNullOrWhiteSpace($outgoingId) -or [string]::IsNullOrWhiteSpace($incomingId)) {
            throw "Pair list row is missing outgoing/incoming ids: $($row | ConvertTo-Json -Compress)"
        }
        if (-not $RowsByTrackId.ContainsKey($outgoingId)) {
            throw "Pair list outgoing track id was not found in analysis: $outgoingId"
        }
        if (-not $RowsByTrackId.ContainsKey($incomingId)) {
            throw "Pair list incoming track id was not found in analysis: $incomingId"
        }
        $outgoing = $RowsByTrackId[$outgoingId]
        $incoming = $RowsByTrackId[$incomingId]
        $tempoDelta = [Math]::Abs((NumberOrZero $outgoing.normalizedBpm) - (NumberOrZero $incoming.normalizedBpm))
        if ($outgoing.bpmKey -ne $incoming.bpmKey -and $DropSwitchTempoPolicy -eq "exact") {
            Write-Warning "Forced drop-switch pair is not same-BPM by analyzed normalized BPM: $outgoingId($($outgoing.bpmKey)) -> $incomingId($($incoming.bpmKey))"
        } elseif ($tempoDelta -gt $MaxTempoAdjustmentBpmPerDeck) {
            Write-Warning "Forced drop-switch pair exceeds the tempo-stretch gate: $outgoingId($($outgoing.bpmKey)) -> $incomingId($($incoming.bpmKey)); delta=$tempoDelta BPM, gate=$MaxTempoAdjustmentBpmPerDeck BPM"
        }
        $compatibility = Get-KeyCompatibility $outgoing $incoming
        if ($DropSwitchKeyPolicy -ne "off" -and -not $compatibility.compatible) {
            Write-Warning "Forced drop-switch pair is not Camelot-compatible by analyzed keys: $outgoingId($($outgoing.camelotKey), confidence=$($outgoing.keyConfidence)) -> $incomingId($($incoming.camelotKey), confidence=$($incoming.keyConfidence)); classification=$($compatibility.classification), reason=$($compatibility.reason)"
        }
        $pairs += [pscustomobject]@{
            outgoing = $outgoing
            incoming = $incoming
            keyCompatibility = $compatibility
        }
    }
    return $pairs
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
            normalizedBpm = NumberOrZero $artifact.tempo.normalizedBpm
            bpmKey = "{0:0.###}" -f $(NumberOrZero $artifact.tempo.normalizedBpm)
            camelotKey = if ($artifact.key -and $artifact.key.camelot) { [string]$artifact.key.camelot } else { "" }
            keyConfidence = if ($artifact.key -and $null -ne $artifact.key.confidence) { NumberOrZero $artifact.key.confidence } else { 0.0 }
            contentHash = if ($artifact.analysis -and $artifact.analysis.sourceContentHash) { [string]$artifact.analysis.sourceContentHash } else { "" }
            hasRekordboxSemanticTruth = $null -ne $artifact.source.providerMetadata.rekordboxSemanticXml
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
    if ($RequireRekordboxSemanticTruth) {
        $missingTruthRows = @($trackRows | Where-Object { -not $_.hasRekordboxSemanticTruth })
        if ($missingTruthRows.Count -gt 0) {
            $examples = ($missingTruthRows | Select-Object -First 5 | ForEach-Object { $_.trackId }) -join ", "
            throw "Existing analysis root is missing Rekordbox semantic-truth metadata on $($missingTruthRows.Count) tracks. Examples: $examples. Use autodj-analysis apply-rekordbox-semantics before running truth-based transition auditions."
        }
    }
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
            normalizedBpm = 0.0
            bpmKey = ""
            camelotKey = ""
            keyConfidence = 0.0
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
    Write-Host "Analyzing $($trackRows.Count) tracks with section backend '$AnalysisSectionBackend', key backend '$AnalysisKeyBackend', and $AnalysisWorkers worker(s)..."
    Invoke-WslAnalysis "autodj-analysis analyze-batch '$manifestWsl' --out '$analysisWsl'$forceArg --section-backend '$AnalysisSectionBackend' --key-backend '$AnalysisKeyBackend' --workers $AnalysisWorkers --debug-waveform-points 32768 --json | tee '$analysisWsl/analyze-summary.json'"

    foreach ($row in $trackRows) {
        $trackDir = Split-Path -Parent $row.analyzedTrackPath
        New-Item -ItemType Directory -Force -Path $trackDir | Out-Null
        $sourceCopy = Join-Path $trackDir ("source-audio" + [System.IO.Path]::GetExtension($row.audioPath).ToLowerInvariant())
        Copy-Item -LiteralPath $row.audioPath -Destination $sourceCopy -Force
        $row.sourceAudioPath = $sourceCopy
        $artifact = Read-JsonFile $row.analyzedTrackPath
        $row.normalizedBpm = NumberOrZero $artifact.tempo.normalizedBpm
        $row.bpmKey = "{0:0.###}" -f $(NumberOrZero $artifact.tempo.normalizedBpm)
        $row.camelotKey = if ($artifact.key -and $artifact.key.camelot) { [string]$artifact.key.camelot } else { "" }
        $row.keyConfidence = if ($artifact.key -and $null -ne $artifact.key.confidence) { NumberOrZero $artifact.key.confidence } else { 0.0 }
    }
}

$artifactsByTrackId = @{}
foreach ($row in $trackRows) {
    $artifactsByTrackId[$row.trackId] = $row
}
$rowsByTrackId = @{}
foreach ($row in $trackRows) {
    $rowsByTrackId[$row.trackId] = $row
}

function Try-CreateTransition([string]$Kind, [int]$Index, $Outgoing, $Incoming) {
    $safeName = New-TransitionSafeName $Kind $Index $Outgoing.trackId $Incoming.trackId
    $transitionDir = Join-Path $TransitionsRoot $safeName
    New-Item -ItemType Directory -Force -Path $transitionDir | Out-Null

    $plannerArgs = @(
        "--out", $transitionDir,
        "--plan-id", $safeName,
        "--max-tempo-adjustment-bpm", (Format-InvariantNumber $MaxTempoAdjustmentBpmPerDeck),
        "--tempo-backend", $TempoStretchBackend,
        "--tempo-quality", $TempoStretchQuality
    )
    if ($Kind -eq "drop-switch" -and $DropSwitchTempoPolicy -ne "exact") {
        $plannerArgs += "--allow-tempo-stretch"
    } else {
        $plannerArgs += "--disable-tempo-stretch"
    }
    $plannerArgs += @("--json", $Outgoing.analyzedTrackPath, $Incoming.analyzedTrackPath)

    & $MixPlanTool @plannerArgs | Tee-Object -FilePath (Join-Path $transitionDir "planner-stdout.json") | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $transitionDir -Recurse -Force -ErrorAction SilentlyContinue
        return $false
    }

    $summaryPath = Join-Path $transitionDir "planner-summary.json"
    $summary = Read-JsonFile $summaryPath
    $expectedTemplate = if ($Kind -eq "drop-switch") { "second_build_drop_switch_v1" } else { "drop_end_wash_out_v1" }
    if ($summary.selectedTemplateId -ne $expectedTemplate) {
        Remove-Item -LiteralPath $transitionDir -Recurse -Force -ErrorAction SilentlyContinue
        return $false
    }

    $rawPlan = Join-Path $transitionDir "mix-plan.json"
    $finalPlan = $rawPlan
    if ($Kind -eq "drop-switch" -or $Kind -eq "wash-out") {
        $nudgedPlan = Join-Path $transitionDir "mix-plan-nudged.json"
        $rawPlanWsl = To-WslPath $rawPlan
        $nudgedPlanWsl = To-WslPath $nudgedPlan
        $assetRootWsl = To-WslPath $AudioFolder
        $nudgeSummaryPath = Join-Path $transitionDir "nudge-summary.json"
        try {
            Invoke-WslAnalysis "autodj-analysis nudge-mixplan '$rawPlanWsl' --out '$nudgedPlanWsl' --asset-root '$assetRootWsl' --window-ms 80 --max-nudge-ms 80 --json > '$(To-WslPath $nudgeSummaryPath)'"
        } catch {
            Write-Warning "Skipping $safeName because transient nudge failed: $_"
            Remove-Item -LiteralPath $transitionDir -Recurse -Force -ErrorAction SilentlyContinue
            return $false
        }
        $nudgeSummary = Read-JsonFile $nudgeSummaryPath
        Write-Host ("Transient nudge for {0}: {1:N1}ms mode={2} confidence={3:N3} risk={4}" -f $safeName, (NumberOrZero $nudgeSummary.nudgeMilliseconds), ([string]$nudgeSummary.selectedAnchorMode), (NumberOrZero $nudgeSummary.confidence), (($nudgeSummary.riskFlags -join ",") -replace "^$", "none"))
        if (-not (Test-NudgeQuality $nudgeSummary $MinNudgeConfidence $MaxNudgeAnchorDisagreementMs)) {
            $disagreementMs = [Math]::Round((Get-NudgeAnchorDisagreementMs $nudgeSummary), 3)
            $message = "Transient nudge quality is weak for $safeName. Confidence=$($nudgeSummary.confidence), nudgeMs=$($nudgeSummary.nudgeMilliseconds), anchorDisagreementMs=$disagreementMs"
            if ($RequireStrongNudge -and $Kind -eq "drop-switch") {
                Write-Warning "Skipping $safeName because $message"
                Remove-Item -LiteralPath $transitionDir -Recurse -Force -ErrorAction SilentlyContinue
                return $false
            }
            Write-Warning "Keeping $safeName even though $message"
        }

        $finalPlan = $nudgedPlan
        if ($Kind -eq "drop-switch") {
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
    $family = if ($Kind -eq "drop-switch") { "drop_switch" } else { "wash_out" }
    New-AuthoringSessionFromMixPlan $finalCopy $sessionPath $artifactsByTrackId $safeName $family "Generated batch audition from $($Outgoing.trackId) to $($Incoming.trackId). MixPlan: $finalCopy"
    Copy-Item -LiteralPath $sessionPath -Destination (Join-Path $transitionDir $sessionName) -Force
    return $true
}

function New-DropSwitchPairCandidates {
    $pairs = @()
    $keyRejected = 0
    $tempoRejected = 0
    for ($offset = 1; $offset -lt $trackRows.Count; $offset += 1) {
        for ($index = 0; $index -lt $trackRows.Count; $index += 1) {
            $outgoing = $trackRows[$index]
            $incoming = $trackRows[($index + $offset) % $trackRows.Count]
            if ($outgoing.trackId -eq $incoming.trackId) {
                continue
            }
            $tempoDelta = [Math]::Abs((NumberOrZero $outgoing.normalizedBpm) - (NumberOrZero $incoming.normalizedBpm))
            $sameBpm = $tempoDelta -le 0.0001
            $stretchEligible = (-not $sameBpm) -and $tempoDelta -le $MaxTempoAdjustmentBpmPerDeck
            if ($DropSwitchTempoPolicy -eq "exact" -and -not $sameBpm) {
                continue
            }
            if ($DropSwitchTempoPolicy -eq "stretch" -and -not $stretchEligible) {
                continue
            }
            if ($DropSwitchTempoPolicy -eq "exact-then-stretch" -and -not $sameBpm -and -not $stretchEligible) {
                $tempoRejected += 1
                continue
            }
            $compatibility = Get-KeyCompatibility $outgoing $incoming
            if ($DropSwitchKeyPolicy -eq "compatible" -and -not $compatibility.compatible) {
                $keyRejected += 1
                continue
            }
            $tempoPriority = if ($sameBpm) { 0 } else { 1 }
            $pairs += [pscustomobject]@{
                outgoing = $outgoing
                incoming = $incoming
                sameBpm = $sameBpm
                tempoDelta = $tempoDelta
                tempoPriority = $tempoPriority
                keyCompatibility = $compatibility
                keyScore = [double]$compatibility.score
                keyClassification = [string]$compatibility.classification
            }
        }
    }
    if ($DropSwitchKeyPolicy -eq "compatible") {
        Write-Host "Drop-switch key filter rejected $keyRejected candidate pairs that were not Camelot-compatible."
    }
    if ($DropSwitchTempoPolicy -eq "exact-then-stretch") {
        Write-Host "Drop-switch tempo filter rejected $tempoRejected candidate pairs outside the $MaxTempoAdjustmentBpmPerDeck BPM stretch gate."
    }
    return @(
        $pairs | Sort-Object `
            @{ Expression = "tempoPriority"; Descending = $false },
            @{ Expression = "keyScore"; Descending = $true },
            @{ Expression = "tempoDelta"; Descending = $false },
            @{ Expression = { $_.outgoing.trackId } },
            @{ Expression = { $_.incoming.trackId } }
    )
}

function New-ReverbPairCandidates {
    $pairs = @()
    for ($offset = 1; $offset -lt $trackRows.Count; $offset += 1) {
        for ($index = 0; $index -lt $trackRows.Count; $index += 1) {
            $outgoing = $trackRows[$index]
            $incoming = $trackRows[($index + $offset) % $trackRows.Count]
            if ($outgoing.trackId -eq $incoming.trackId) {
                continue
            }
            $compatibility = Get-KeyCompatibility $outgoing $incoming
            $pairs += [pscustomobject]@{
                outgoing = $outgoing
                incoming = $incoming
                keyCompatibility = $compatibility
                keyScore = [double]$compatibility.score
                keyClassification = [string]$compatibility.classification
            }
        }
    }
    return @($pairs | Sort-Object @{ Expression = "keyScore"; Descending = $true }, @{ Expression = { $_.outgoing.trackId } }, @{ Expression = { $_.incoming.trackId } })
}

$dropMade = 0
$forcedDropPairs = @(Read-DropSwitchPairList $DropSwitchPairListPath $rowsByTrackId)
$dropPairs = if ($forcedDropPairs.Count -gt 0) { $forcedDropPairs } else { @(New-DropSwitchPairCandidates) }
if ($forcedDropPairs.Count -eq 0 -and $DropSwitchCount -gt 0 -and $dropPairs.Count -eq 0 -and $DropSwitchKeyPolicy -eq "compatible") {
    throw "No Camelot-compatible drop-switch candidate pairs were found for policy '$DropSwitchTempoPolicy'. Confirm analyzed-track artifacts include in-house key.camelot metadata, increase -MaxTempoAdjustmentBpmPerDeck, or rerun with -DropSwitchKeyPolicy score/off for diagnostic auditions."
}
foreach ($pair in $dropPairs) {
    if ($dropMade -ge $DropSwitchCount) { break }
    if (Try-CreateTransition "drop-switch" ($dropMade + 1) $pair.outgoing $pair.incoming) {
        $dropMade += 1
    }
}

$washOutMade = 0
foreach ($pair in @(New-ReverbPairCandidates)) {
    if ($washOutMade -ge $ReverbExitCount) { break }
    if (Try-CreateTransition "wash-out" ($washOutMade + 1) $pair.outgoing $pair.incoming) {
        $washOutMade += 1
    }
}

$runSummary = [ordered]@{
    ok = ($dropMade -eq $DropSwitchCount -and $washOutMade -eq $ReverbExitCount)
    runName = $RunName
    outputRoot = $OutputRoot
    analysisRoot = $AnalysisRoot
    dropSwitchPairListPath = if ([string]::IsNullOrWhiteSpace($DropSwitchPairListPath)) { "" } else { [System.IO.Path]::GetFullPath($DropSwitchPairListPath) }
    sessionsRoot = $SessionsRoot
    transitionsRoot = $TransitionsRoot
    audioFolder = $AudioFolder
    usingExistingAnalysis = $UsingExistingAnalysis
    existingAnalysisRoot = if ($UsingExistingAnalysis) { $AnalysisRoot } else { "" }
    dropSwitchRequested = $DropSwitchCount
    dropSwitchCreated = $dropMade
    washOutRequested = $ReverbExitCount
    washOutCreated = $washOutMade
    minNudgeConfidence = $MinNudgeConfidence
    maxNudgeAnchorDisagreementMs = $MaxNudgeAnchorDisagreementMs
    requireStrongNudge = [bool]$RequireStrongNudge
    requireRekordboxSemanticTruth = [bool]$RequireRekordboxSemanticTruth
    dropSwitchKeyPolicy = $DropSwitchKeyPolicy
    dropSwitchTempoPolicy = $DropSwitchTempoPolicy
    maxTempoAdjustmentBpmPerDeck = $MaxTempoAdjustmentBpmPerDeck
    tempoStretchBackend = $TempoStretchBackend
    tempoStretchQuality = $TempoStretchQuality
    autoDjExe = $AutoDjExe
}
Write-JsonFile (Join-Path $OutputRoot "run-summary.json") $runSummary

Write-Host ""
Write-Host "Batch complete."
Write-Host "Output root: $OutputRoot"
Write-Host "Sessions to import: $SessionsRoot"
Write-Host "Transitions/renders: $TransitionsRoot"
Write-Host "Drop switches created: $dropMade / $DropSwitchCount"
Write-Host "Wash-outs created: $washOutMade / $ReverbExitCount"
Write-Host "AutoDJ exe: $AutoDjExe"
