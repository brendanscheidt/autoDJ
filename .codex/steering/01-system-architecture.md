# System Architecture

## Pipeline

```text
AudioRepository
  -> GenreAnalyzer
  -> TrackAnalyzer / AnalysisWorker
  -> SemanticCueProvider
  -> MetadataCache
  -> DJStrategy
  -> MixPlan
  -> PlaybackEngine
  -> Desktop Workbench UI
```

The architecture should separate three concerns:

- Ingestion: where tracks come from.
- Intelligence: how tracks are analyzed and arranged into a set.
- Execution: how a planned set is played.

The playback engine should not know whether tracks came from local files, a
future cloud sync system, or a future licensed catalog. It receives resolved
audio assets and a command timeline.

## Module Responsibilities

### AudioRepository

Provides access to audio assets. For the MVP this is a local folder/file
repository for WAV and MP3.

Responsibilities:

- Discover or import local tracks.
- Assign stable track IDs.
- Return file paths, content hashes, duration when known, and basic tags.
- Report whether a track has changed and needs reanalysis.
- Avoid DJ, genre, or playback-specific logic.

Future repository implementations may target other sources, but they must expose
the same contract. They may not leak provider-specific assumptions into the
engine.

### GenreAnalyzer

Classifies tracks before dispatching to a genre-specific DJ strategy.

MVP behavior:

- Return `dubstep` for every track.
- Include a confidence field and a reason string so the shape matches a real
  classifier later.

Future behavior:

- Return one or more candidate genres.
- Optionally reject unsupported tracks from the AutoDJ pool.
- Route compatible tracks to the correct DJ strategy.

### TrackAnalyzer / AnalysisWorker

Runs offline audio analysis and writes normalized metadata.

Responsibilities:

- Decode audio for analysis.
- Estimate BPM, beat grid, downbeats, key, loudness, energy, sections, cue
  candidates, vocal regions, and stem paths.
- Compute confidence values for uncertain analysis.
- Cache results keyed by track identity and file content hash.
- Produce versioned JSON artifacts that the C++ app can consume.

The analysis worker may be Python while playback is C++. Treat it as a separate
process boundary unless there is a strong reason to embed it later.

### SemanticCueProvider

Normalizes section and cue labels before DJ planning.

Responsibilities:

- Convert provider-specific evidence into canonical `AnalyzedTrack.sections`
  and `AnalyzedTrack.cuePoints`.
- Support Rekordbox XML hot-cue labels as the current trusted POC oracle.
- Keep automatic semantic backends such as `dubstep-phrase-hybrid`, CUE-DETR,
  EDM-98, All-In-One, or SongFormer behind the same contract.
- Preserve provenance, confidence, and warnings so bad transitions can be traced
  to a specific cue source.

Boundary rule: DJ strategies consume normalized analyzed-track sections/cues.
They should not parse Rekordbox XML or model-specific raw outputs directly.

### MetadataCache

Stores analyzed track artifacts and derived assets.

Responsibilities:

- Persist `AnalyzedTrack` records.
- Store waveform previews and stem file locations.
- Invalidate analysis when source files change.
- Keep schema version and analyzer version for migrations.

SQLite is the long-term local cache candidate. JSON files are acceptable during
early development if they follow the same schemas.

### DJStrategy

Generates a set-level plan from analyzed tracks.

Responsibilities:

- Select track order.
- Select transition templates between tracks.
- Compile musically meaningful actions into a `MixPlan`.
- Explain decisions with scores and reasons for debugging.
- Own genre-specific rules.

The DJ strategy should not render audio. It emits plans.

### MixPlan

The `MixPlan` is the durable contract between intelligence and playback.

It contains:

- Set metadata.
- Track placements.
- Transition edges.
- Deck commands.
- Automation lanes and keyframes.
- References to audio assets and stems.
- Debug annotations explaining DJ choices.

Transitions belong primarily to the edge between two tracks, not only to either
individual track. This avoids embedding relationship-specific behavior inside a
track record.

### PlaybackEngine

Executes a `MixPlan`.

Responsibilities:

- Load audio onto decks.
- Play, pause, stop, seek, loop, and clear loops.
- Apply volume, EQ, filter, tempo, reverb, echo, and crossfader automation.
- Interpolate keyframes deterministically.
- Preserve real-time audio safety.
- Report playback state to the UI.

The playback engine should be dumb by design. It does not choose tracks,
classify genres, or decide transition techniques.

### Desktop Workbench UI

The first UI is a developer/listener workbench.

Responsibilities:

- Import local tracks.
- Show repository status.
- Run analysis.
- Show analysis metadata and confidence.
- Generate a mix plan.
- Visualize waveform, sections, cue points, and transitions.
- Play the generated set.
- Provide debugging affordances for bad analysis or bad transitions.

## Runtime Modes

### Offline Analysis

Runs outside the real-time audio path. It can use CPU/GPU, spawn worker
processes, and write derived files.

### Plan Generation

Runs after tracks are analyzed. It should be deterministic for a given random
seed, input set, and algorithm version.

### Real-time Playback

Runs with strict constraints:

- No blocking file I/O on the audio callback.
- No network calls.
- No unbounded allocation.
- No heavy analysis.
- No locks that can wait on UI or worker threads.

### Offline Render

Not required for the MVP, but the architecture should allow rendering a
`MixPlan` to a WAV file later using the same execution semantics as playback.

## Boundary Rules

- Repository code does not analyze audio.
- Genre analyzer does not decide transitions.
- Track analyzer does not choose set order.
- DJ strategies do not render audio.
- Playback engine does not contain genre-specific logic.
- UI may inspect everything, but should not be the owner of core decisions.

## Data Flow

1. User imports local files into the repository.
2. Repository emits `RepositoryTrack` records.
3. Stub genre analyzer marks them as `dubstep`.
4. Analysis worker generates `AnalyzedTrack` artifacts.
5. Optional semantic cue providers override or augment sections/cues.
6. Metadata cache stores artifacts.
7. Dubstep DJ strategy creates a `MixPlan`.
8. Playback engine validates and executes the plan.
9. UI visualizes playback state and debug annotations.
