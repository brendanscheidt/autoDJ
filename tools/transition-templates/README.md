# Transition Sheet Workflow

This folder contains fillable text templates for authoring transitions in Rekordbox and converting them into AutoDJ JSON.

This is now a developer fallback path. The preferred authoring path is the
native Spec 007 transition workbench, which can load analyzed songs, edit
automation visually, and export session/MixPlan/recipe JSON. Keep these sheets
for quick scripted fixtures, regression cases, and cases where Rekordbox notes
need to be converted without opening the workbench.

The current workflow is:

1. Export AutoDJ analysis into Rekordbox XML:

   ```powershell
   wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && autodj-analysis export-rekordbox-xml <analyzed-track.json> --out <track-rekordbox.xml> --source-uri '<audio-file>'"
   ```

   By default this uses `--cue-policy transition-8`, which caps Rekordbox `POSITION_MARK` entries to the 8 most transition-relevant hot cues. Use `--cue-policy all` only when you want every semantic section boundary for debugging outside the hot-cue limit.

2. Import that XML into Rekordbox to inspect AutoDJ BPM, beatgrid, and semantic section cue marks.
3. Design a transition in Rekordbox by ear.
4. Copy one of the `.txt` templates in this folder and fill in the bar/beat stamps you used.
5. Parse the filled sheet:

   ```powershell
   wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && autodj-analysis parse-transition-template tools/transition-templates/my-filled-transition.txt --out .autodj-cache/manual-transition/mix-plan.json --json"
   ```

## Time Format

The parser uses bar/beat stamps, not raw timeline seconds.

The first beat in the analyzed beatgrid is `1.1`, then `1.2`, `1.3`, `1.4`, `2.1`, and so on.

For exact two-song transition sheets:

- `song_a.*` fields are source positions in song A.
- `song_b.*` fields are source positions in song B.
- `action: b.volume at 25.1 = 1 smooth` means automate deck B volume when song B reaches bar `25.1`.
- `action: a.reverbTailGain at b:9.1 = 0 smooth` means automate deck A, but schedule it at the moment deck B reaches bar `9.1`.

Interpolation words:

- `instant`: jump at that point.
- `straight`: linear fade/ramp.
- `smooth`: eased fade/ramp.
- `curve`: more aggressive curved fade/ramp.

## Template Types

- `specific-drop-switch.transition.txt`: exact two-song drop switch. The parser aligns `song_b.drop_start` to `song_a.drop_start`.
- `specific-double-drop.transition.txt`: exact two-song double drop. The parser aligns `song_b.drop_start` to `song_a.drop_start` and preserves your deck automation through both drops.
- `specific-reverb-exit.transition.txt`: exact two-song reverb exit. The parser aligns `song_b.first_beat` to `song_a.drop_end`.
- `generic-drop-switch.recipe.txt`: reusable drop-switch recipe with semantic anchors and expressions.
- `generic-reverb-exit.recipe.txt`: reusable reverb-exit recipe with semantic anchors and expressions.
