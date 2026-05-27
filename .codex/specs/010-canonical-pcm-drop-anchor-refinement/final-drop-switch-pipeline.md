# Final Drop-Switch Audition Pipeline

Status: accepted for current POC auditions as of 2026-05-24.

This runbook records the path that should be used for generated drop-switch
auditions after the Spec 010 experiments. It intentionally avoids the
experimental refined-anchor/drop-wall/beatgrid-phase branches unless a future
spec reopens them.

## Accepted Pipeline

For current drop-switch auditions, use this order:

1. Analyze tracks with AutoDJ BPM, beatgrid, waveform, and key analysis.
2. Apply Rekordbox XML semantic labels only with `apply-rekordbox-semantics`.
   Do not replace AutoDJ BPM, beatgrid, or key with Rekordbox values.
3. Generate drop-switch candidates from tracks with compatible Camelot key and
   either exact matching normalized BPM or a SoundStretch-eligible BPM delta.
   Native exact-BPM pairs are still preferred and auditioned first.
4. Filter generated drop-switch candidates by compatible Camelot key when both
   tracks have confident in-house key estimates.
5. Build the MixPlan. If the incoming track must match the outgoing BPM, emit a
   constant incoming `tempoPlan` using SoundStretch.
6. Run raw transient `nudge-mixplan` with the tested 80 ms search window. The
   nudge pass must account for any constant tempo ratio on the incoming deck.
7. Run drop-switch gain planning.
8. Render WAV and export an importable AutoDJ authoring session.

The final path does not use:

- `refine-beatgrid-phase`
- drop-wall selected anchors
- canonical PCM as the active timing source
- Rekordbox BPM or beatgrid truth
- independent per-beat snapping
- Rubber Band as the selected POC time-stretch backend

Those branches are preserved only as research artifacts and should not be
mixed into the accepted audition path without a new manual gate.

## Fresh Analysis Requirement

Generated automatic drop-switch batches should use a fresh analysis root from
the current analyzer. Old roots made before in-house key analysis was added do
not contain `key.camelot`, so the key compatibility gate cannot select pairs.

Use `-ExistingAnalysisRoot` only when every `analyzed-track.json` already has:

- `source.providerMetadata.rekordboxSemanticXml`
- `key.camelot`
- `key.confidence`
- `tempo.normalizedBpm`

## Recommended Audition Command

Run from PowerShell at the repo root:

```powershell
cd C:\Users\Brendan\Dev\AudioProj

$AnalysisRoot = "C:\Users\Brendan\Dev\AudioProj\.autodj-cache\transition-auditions\keyed-rekordbox-semantic-truth-20260524-095821\analysis"

powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\run-transition-audition-batch.ps1 `
  -AudioFolder "C:\Users\Brendan\Desktop\AutoDJTestDubstep" `
  -ExistingAnalysisRoot $AnalysisRoot `
  -RunName "truth-keyed-auditions-$(Get-Date -Format yyyyMMdd-HHmmss)" `
  -DropSwitchCount 10 `
  -ReverbExitCount 10 `
  -RequireRekordboxSemanticTruth `
  -DropSwitchKeyPolicy compatible `
  -DropSwitchTempoPolicy exact-then-stretch `
  -MaxTempoAdjustmentBpmPerDeck 10.0 `
  -TempoStretchBackend soundstretch
```

`$AnalysisRoot` should point at an analysis folder that already has Rekordbox
semantic labels applied. The batch script does not currently import a Rekordbox
XML directly; it consumes `analyzed-track.json` artifacts.

The default `-DropSwitchKeyPolicy compatible` means automatic drop-switch pair
selection requires compatible in-house Camelot keys. The default
`-DropSwitchTempoPolicy exact-then-stretch` means exact normalized BPM matches
are selected first; if more candidates are needed, incoming tracks within the
configured BPM gate can be rendered with SoundStretch to match the outgoing
track's BPM for the overlap. Reverb-exit auditions can still be generated when
BPM/key constraints block a drop switch.

## Diagnostic Modes

Use these only to diagnose pair availability, not for final audition verdicts:

```powershell
# Rank key-compatible pairs higher, but do not reject key clashes.
-DropSwitchKeyPolicy score

# Ignore key compatibility completely.
-DropSwitchKeyPolicy off

# Force only native exact-BPM drop switches.
-DropSwitchTempoPolicy exact

# Force only BPM-stretched drop switches for testing SoundStretch candidates.
-DropSwitchTempoPolicy stretch
```

Use a fixed pair list only for regression listening. Fixed pairs are treated as
explicit human requests, so the script warns about key/BPM issues instead of
silently replacing the pair.

## Manual Verdict Standard

For a drop-switch candidate to remain trusted, the rendered WAV/session should
pass these checks by ear:

- the two drops arrive together;
- the incoming transient is not audibly flammed;
- the build overlap does not clip or overpower the incoming drop;
- the transition uses the intended hand-labeled build/drop sections;
- the pair is harmonically compatible enough for a long build overlap.

If a pair fails the transient check, reject that pair or route it to a different
transition family. Do not re-enable the rejected refined-anchor path as an
automatic fix.
