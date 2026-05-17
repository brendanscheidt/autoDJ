# Manual Known-Song Checkpoint

Use this checkpoint after generated fixture tests pass. The goal is not to bless
the baseline as production-grade. The goal is to capture whether one real local
song produces musically plausible BPM, energy, rough sections, and cue
candidates.

Do not commit local music, generated manifests, generated summaries, or
`.autodj-cache/` outputs. Put manual inputs under `local-audio/`, which is
ignored by git.

## WSL Setup

Run from Windows PowerShell:

```powershell
wsl --status
wsl --list --verbose
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && python3.11 --version"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && python3.11 -m venv .venv-analysis"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pip install -U pip setuptools wheel"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pip install -e './analysis/worker-python[dev,analysis-wsl]'"
```

Verify the analysis environment:

```powershell
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python -m analysis -q"
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pip check"
```

Install FFmpeg tools inside WSL so `ffprobe` is available to `analyze-batch`:

```powershell
wsl -d Ubuntu-24.04 -- bash -lc "sudo apt update && sudo apt install -y ffmpeg"
wsl -d Ubuntu-24.04 -- bash -lc "ffprobe -version | head -n 1"
```

## Generated-Fixture Check

This command covers the real batch path with a generated energy-ramp song:

```powershell
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python/tests/test_batch.py::test_analyze_repository_manifest_runs_real_signal_analysis_for_generated_audio -q"
```

For broader fixture coverage, run:

```powershell
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/Brendan/Dev/AudioProj && source .venv-analysis/bin/activate && python -m pytest analysis/worker-python -m analysis -q"
```

## One-Song Batch Run

Start an Ubuntu shell:

```powershell
wsl -d Ubuntu-24.04
```

Inside WSL, replace `SOURCE_SONG` with a local WAV or MP3 you are allowed to
analyze:

```bash
cd /mnt/c/Users/Brendan/Dev/AudioProj || exit 1
source .venv-analysis/bin/activate || exit 1

SOURCE_SONG="/mnt/c/Users/Brendan/Music/AutoDJTest/BackspinBass.mp3"

export SONG_ROOT="$PWD/local-audio/manual-known-song"
mkdir -p "$SONG_ROOT"

SONG_EXT="${SOURCE_SONG##*.}"
export SONG_FILE="known-song.${SONG_EXT}"
export TRACK_ID="manual-known-song"

cp "$SOURCE_SONG" "$SONG_ROOT/$SONG_FILE" || exit 1
export CONTENT_HASH="sha256:$(sha256sum "$SONG_ROOT/$SONG_FILE" | awk '{print $1}')"

python - <<'PY'
from datetime import UTC, datetime
import json
import os
from pathlib import Path

song_root = Path(os.environ["SONG_ROOT"]).resolve()
song_file = os.environ["SONG_FILE"]
track_id = os.environ["TRACK_ID"]
content_hash = os.environ["CONTENT_HASH"]

manifest = {
    "schemaVersion": "1.0.0",
    "repositoryId": "manual-known-song",
    "producer": "manual-known-song-checkpoint",
    "producerVersion": "1.0.0",
    "createdAtUtc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "source": {"repositoryType": "local", "rootUri": str(song_root)},
    "tracks": [{
        "trackId": track_id,
        "repositoryId": "manual-known-song",
        "sourceUri": song_file,
        "contentHash": content_hash,
        "title": Path(song_file).stem,
        "formatHint": Path(song_file).suffix.lstrip(".").lower(),
    }],
}

(song_root / "repository-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(song_root / "repository-manifest.json")
PY

python -m autodj_analysis analyze-batch \
  local-audio/manual-known-song/repository-manifest.json \
  --out .autodj-cache/manual-known-song \
  --json | tee local-audio/manual-known-song/analyze-summary.json

python -m autodj_analysis debug-waveform "$SONG_ROOT/$SONG_FILE" \
  --out local-audio/manual-known-song/debug-waveform.json \
  --points 32768 \
  --json
```

Print the fields to inspect:

```bash
python - <<'PY'
import json
from pathlib import Path

track_id = "manual-known-song"
cache_dir = Path(".autodj-cache/manual-known-song/tracks") / track_id
artifact = json.loads((cache_dir / "analyzed-track.json").read_text(encoding="utf-8"))
waveform = json.loads((cache_dir / "waveform.json").read_text(encoding="utf-8"))

print("tempo", artifact["tempo"])
print("beatGrid confidence", artifact["beatGrid"]["confidence"])
print("beat count", len(artifact["beatGrid"]["beats"]))
print("energy first/last", artifact["energy"]["curve"][:3], artifact["energy"]["curve"][-3:])
print("sections", artifact["sections"])
print("cuePoints", artifact["cuePoints"])
print("quality", artifact["quality"])
print("waveform summary", waveform["summary"])
print("waveform points", len(waveform["points"]))
PY
```

## Visual Debug Viewer

Open `tools/analysis-debug-viewer.html` in a browser. It does not need a dev
server. Load these files:

- `.autodj-cache/manual-known-song/tracks/manual-known-song/analyzed-track.json`
- `local-audio/manual-known-song/debug-waveform.json`
- `local-audio/manual-known-song/known-song.mp3`

If you have not generated the RGB debug waveform yet, load
`.autodj-cache/manual-known-song/tracks/manual-known-song/waveform.json`
instead. The debug file is higher resolution and includes low/mid/high band
energy and transient strength, which makes beat alignment easier to inspect.

The viewer overlays the waveform, RGB band color, transient highlights, RMS,
energy curve, beat grid, cue points, and rough sections. Use the optional
reference BPM field to compare the generated grid against a known tempo such as
`140`. Use the zoom window selector, mouse wheel, or drag on the main waveform
to inspect beat alignment closely. Click the main waveform to seek playback to
that time, and use Play/Pause to audition whether the grid lines up. The small
overview waveform stays on the full song and shows the active zoom window.

## Inspection Checklist

Record these observations in the task note or a follow-up issue:

- BPM: Is `tempo.bpm` near the song's perceived tempo?
- Normalized BPM: Is `tempo.normalizedBpm` plausible for dubstep-style 70/140
  halftime or straight-time reasoning?
- Beat grid: Do early `beatGrid.beats[*].timeSeconds` values line up with
  audible beats? Is `beatGrid.confidence` honest?
- Energy: Does `energy.curve` broadly follow the song's intro/build/drop shape?
  Does `bassEnergyCurve` rise during bass-heavy sections?
- Sections: Are rough `intro`, `build`, `drop`, or `outro` labels plausible?
  Are questionable labels low confidence or absent?
- Cue candidates: Are `drop`, `build_start`, `mix_in`, or `mix_out` points near
  useful musical boundaries? Are beat-snapped cues close to real beats?
- Warnings: Are `quality.warnings` clear about heuristic sections, missing
  downbeats, and weak evidence?
- False positives: Note any cue, section, or tempo output that would make a DJ
  transition risky.

## Current Backend Combination

The current artifact writer uses:

- FFprobe for container metadata under `source.providerMetadata.ffprobe`.
- SoundFile for local audio decoding.
- librosa for resampling, onset strength, and tempo/beat experiments.
- NumPy for deterministic signal array handling.
- SciPy signal processing for the low-pass bass-energy estimate.
- Custom Python code for waveform peak/RMS points.
- Custom conservative heuristics for rough sections and cue candidates.

Essentia is installed and smoke-tested in the WSL analysis environment as a POC
reference backend, but it is not yet selected by `analyze-batch` for artifact
fields. Candidate libraries such as audioFlux, pyAudioAnalysis, and mir_eval are
tracked in `mir-library-survey.md` for comparison work. Key, vocal regions,
downbeats, and stems remain placeholders until a future spec adds a tested
backend.

## Native And Mobile Portability Notes

| Feature family | Current baseline | Portability estimate | Future path |
| --- | --- | --- | --- |
| Waveform peak/RMS | Custom sample-window stats | Easy | Reimplement directly in C++ over decoded PCM. |
| RMS energy curve | Custom frame RMS with NumPy arrays | Easy | Reimplement directly in C++ with the same frame/hop parameters. |
| Bass energy curve | SciPy low-pass filter plus frame RMS | Moderate | Port with a native IIR/FIR filter or compare against a permissive DSP library. |
| Onset density | librosa onset strength | Moderate | Port a spectral-flux style onset envelope or choose a native MIR library. |
| BPM and beat grid | librosa plus transient/interval fallback | Moderate to hard | Validate on real songs, compare Essentia/audioFlux/aubio, then port or license the strongest backend. |
| Rough sections and cues | Custom energy/onset/beat heuristics | Moderate | Keep heuristic logic portable, but calibrate thresholds from real-song feedback. |
| Downbeats | Not emitted | Hard | Requires a defensible backend or model; avoid fabricating downbeats. |
| Key | Placeholder | Moderate to hard | Compare chroma/key backends before emitting product-critical key values. |
| Vocals and stems | Placeholder | Hard/licensing-dependent | Future Demucs or native/mobile ML work must include model, license, and runtime decisions. |

Do not copy incompatible open-source implementation code into a closed-source
native analyzer. Use documented algorithms, permissive libraries, or commercial
licenses where needed.
