# Design Document

## Overview

This spec moves the Python analysis worker from a single-track stub to a
manifest/cache-aware batch worker. The worker will read
`repository-manifest.json`, probe each local source file with `ffprobe`, write
`analyzed-track.json` under the spec 002 cache layout, and skip artifacts that
are already current for the same source content hash and analyzer parameters.

The hard music analysis fields remain placeholders in this spec. The value of
this slice is cache correctness, batch orchestration, robust subprocess error
handling, and real file metadata.

## Steering Context

Implementation agents must read:

- `.codex/steering/00-product-vision.md`
- `.codex/steering/01-system-architecture.md`
- `.codex/steering/02-core-contracts.md`
- `.codex/steering/03-tech-stack.md`
- `.codex/steering/04-project-structure.md`
- `.codex/steering/07-analysis-pipeline.md`
- `.codex/steering/08-engineering-practices.md`
- `.codex/steering/09-roadmap.md`

## Architecture

Relevant pipeline segment:

```text
LocalAudioRepository
  -> repository-manifest.json
  -> autodj-analysis analyze-batch
  -> .autodj-cache/tracks/<track-id>/analyzed-track.json
  -> future DJStrategy / PlaybackEngine
```

Dependency direction:

```text
analysis/worker-python
  -> core/contracts/schemas by JSON shape
  -> repository manifest artifact on disk
  -> ffprobe subprocess
```

The worker must not import C++ modules, playback code, DJ strategy code, desktop
UI code, or heavy MIR libraries in this spec.

## Public CLI Surface

Current commands remain supported:

```powershell
python -m autodj_analysis classify <audio-path>
python -m autodj_analysis analyze <audio-path> --out <output-dir>
```

Add:

```powershell
python -m autodj_analysis analyze-batch <repository-manifest.json> --out <cache-root>
```

Options:

```text
--ffprobe <path>          executable override, default ffprobe
--force                   ignore cache freshness and rewrite all artifacts
--parameters-hash <hash>  override current parameter hash
--json                    print JSON summary
```

The existing `analyze` command can keep stub behavior or be refactored to share
artifact-writing helpers. It should not become a blocking dependency for
`analyze-batch` correctness.

## Proposed Python Modules

The exact file names can follow implementation judgment, but the module should
stay small and testable.

```text
analysis/worker-python/src/autodj_analysis/
  cli.py
  analyze.py
  batch.py
  cache.py
  manifest.py
  probe.py
```

### `manifest.py`

Responsibilities:

- Load JSON.
- Validate the subset of repository manifest fields needed for analysis.
- Convert manifest tracks into simple Python data objects.
- Preserve source URI strings exactly as stored.
- Resolve local paths for probing.

Suggested data objects:

```python
@dataclass(frozen=True)
class RepositoryTrack:
    track_id: str
    repository_id: str
    source_uri: str
    source_path: Path
    content_hash: str | None
    format_hint: str | None
    title: str | None
    artist: str | None
    album: str | None
```

### `cache.py`

Responsibilities:

- Resolve `<cache-root>/tracks/<track-id>/analyzed-track.json`.
- Load existing analyzed artifacts for freshness checks.
- Perform atomic writes.
- Return freshness decisions with reasons.

Freshness key:

```text
schemaVersion
trackId
analyzer.producer
analyzer.producerVersion
analyzer.sourceContentHash
analyzer.parametersHash
```

### `probe.py`

Responsibilities:

- Execute `ffprobe`.
- Parse JSON.
- Select the primary audio stream.
- Normalize duration/sample-rate/channels and provider metadata.
- Convert expected subprocess and parsing failures into worker errors.

Recommended command:

```text
ffprobe -v error -print_format json -show_format -show_streams <path>
```

Suggested data object:

```python
@dataclass(frozen=True)
class AudioProbe:
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    codec_name: str | None
    codec_long_name: str | None
    bit_rate: int | None
    format_name: str | None
    format_long_name: str | None
    tags: dict[str, str]
    raw: dict[str, object]
```

### `batch.py`

Responsibilities:

- Iterate manifest tracks.
- Skip fresh artifacts unless forced.
- Probe stale/missing artifacts.
- Build analyzed-track artifacts.
- Write artifacts.
- Continue after per-track failures.
- Return a batch result suitable for CLI and future UI display.

Suggested result shape:

```json
{
  "ok": true,
  "manifestPath": "...",
  "cacheRoot": "...",
  "totalTracks": 2,
  "analyzed": 1,
  "skipped": 1,
  "failed": 0,
  "tracks": [
    {
      "trackId": "track-a",
      "status": "analyzed",
      "artifactPath": ".../tracks/track-a/analyzed-track.json"
    }
  ],
  "errors": []
}
```

## Artifact Construction

Analyzer provenance constants should be centralized:

```python
ANALYZER_PRODUCER = "autodj_analysis.ffprobe"
ANALYZER_VERSION = __version__
DEFAULT_PARAMETERS_HASH = "sha256:ffprobe-v1-placeholders-v1"
```

Real fields:

- Use repository track identity fields.
- Use repository `contentHash` as `analyzer.sourceContentHash`.
- Use `ffprobe` metadata for duration, sample rate, channels, codec, bit rate,
  format, and tags.
- Derive title from manifest title, probe tags, or filename stem in that order.

Placeholder fields:

- Tempo: use a low-confidence placeholder, for example `bpm: 140.0`,
  `normalizedBpm: 140.0`, `confidence: 0.0`, plus warning.
- Key: `unknown`, confidence `0.0`.
- Beat grid/downbeats: empty arrays with confidence `0.0` are preferred over
  fake high-confidence timings.
- Sections: either empty array or one `unknown` section spanning duration with
  low confidence.
- Energy: minimal curve with low confidence.
- Vocals: `hasVocals: false`, confidence `0.0`.
- Cue points: empty array.

The artifact should be honest about what is known. Do not generate plausible
but fake build/drop cues in this spec.

## Error Handling

Define a small worker error type or structured dictionaries with:

```text
code
message
trackId
sourceUri
```

Expected error codes:

- `manifest_read_error`
- `manifest_parse_error`
- `manifest_missing_field`
- `source_missing`
- `ffprobe_missing`
- `ffprobe_failed`
- `ffprobe_invalid_json`
- `ffprobe_no_audio_stream`
- `artifact_write_error`

Unexpected programming errors can still raise normally during tests, but CLI
user-facing failures should be concise.

## Testing Strategy

Use generated temporary directories and files. Do not commit music.

Prefer a fake `ffprobe` executable for most tests:

- Python script that prints known JSON and exits 0.
- Python script that prints invalid JSON and exits 0.
- Python script that exits nonzero.

Optional integration:

- If `ffprobe` is on PATH, generate a tiny WAV file using Python's standard
  `wave` module and verify real probing.
- Skip cleanly when `ffprobe` is unavailable.

Test command:

```powershell
.\.venv\Scripts\python -m pytest .\analysis\worker-python
```

## README Update

The current README still describes the project as in foundation setup. Update it
when this spec is implemented to reflect:

- Foundation and local repository/cache specs are complete.
- Analysis worker now supports batch probing from repository manifests.
- `analyze-batch` command exists.
- BPM/key/section analysis is still not implemented.
- Local music and generated cache artifacts must not be committed.

## Implementation Constraints

- Keep dependencies minimal. Use Python standard library for JSON, dataclasses,
  pathlib, subprocess, and tests.
- Do not add FFmpeg Python bindings.
- Do not add Essentia, librosa, Demucs, numpy, scipy, or soundfile in this spec.
- Do not modify C++ repository behavior unless verification exposes a narrow
  compatibility issue.
- Do not write outside the provided `--out` cache root except reading the source
  audio file.
- Keep generated analysis artifacts out of git unless they are explicit tiny
  JSON fixtures under `fixtures/`.
