# Core Contracts

## Contract Principles

Contracts must be stable enough that modules can be developed independently.
Prefer plain data structures and versioned JSON at process boundaries.

Rules:

- Every persisted artifact must include `schemaVersion`.
- Every generated artifact must include `producer`, `producerVersion`, and
  source input hashes when available.
- All absolute audio timing values are seconds as floating point numbers unless
  explicitly marked as samples or beats.
- Musical authoring should use beats, bars, phrases, and section anchors.
- Playback execution should use compiled timeline seconds and sample-accurate
  positions where possible.
- Confidence values use `0.0` to `1.0`.
- IDs are stable strings, not array indexes.
- Provider-specific data lives under `providerMetadata`.

## Shared Time Types

```ts
type TrackSeconds = number;
type TimelineSeconds = number;
type BeatIndex = number;
type BarIndex = number;

interface MusicalPosition {
  beatIndex: BeatIndex;
  barIndex?: BarIndex;
  beatInBar?: number;
  phraseIndex?: number;
}
```

The DJ strategy should reason mostly in musical time. The plan compiler resolves
musical anchors to timeline seconds using the analyzed beat grid.

## Track Identity

```ts
interface TrackAsset {
  trackId: string;
  repositoryId: string;
  sourceUri: string;
  contentHash?: string;
  title?: string;
  artist?: string;
  album?: string;
  durationSeconds?: number;
  sampleRate?: number;
  channels?: number;
  providerMetadata?: Record<string, unknown>;
}
```

For local files, `sourceUri` should be a file URI or normalized absolute path.
Use content hashes to decide whether cached analysis is stale.

## AudioRepository

```ts
interface AudioRepository {
  readonly repositoryId: string;

  scan(): Promise<RepositoryScanResult>;
  listTracks(): Promise<TrackAsset[]>;
  getTrack(trackId: string): Promise<TrackAsset>;
  resolveAudio(trackId: string): Promise<ResolvedAudioAsset>;
}

interface RepositoryScanResult {
  repositoryId: string;
  tracksAdded: number;
  tracksUpdated: number;
  tracksRemoved: number;
  errors: RepositoryError[];
}

interface ResolvedAudioAsset {
  trackId: string;
  readableUri: string;
  formatHint?: "wav" | "mp3" | "flac" | "aiff" | "unknown";
  contentHash?: string;
}
```

MVP implementation: `LocalAudioRepository`.

Future repository implementations must not require playback or analysis code to
understand their provider details.

## GenreAnalyzer

```ts
interface GenreAnalyzer {
  classify(track: TrackAsset): Promise<GenreVerdict>;
  classifyBatch(tracks: TrackAsset[]): Promise<GenreVerdict[]>;
}

interface GenreVerdict {
  trackId: string;
  primaryGenre: string;
  confidence: number;
  allowedForAutoDj: boolean;
  candidateGenres: Array<{ genre: string; confidence: number }>;
  reason?: string;
}
```

MVP implementation: `StubDubstepGenreAnalyzer`, which returns:

```json
{
  "primaryGenre": "dubstep",
  "confidence": 1.0,
  "allowedForAutoDj": true,
  "candidateGenres": [{ "genre": "dubstep", "confidence": 1.0 }],
  "reason": "MVP stub assumes local imports are dubstep"
}
```

## AnalyzedTrack

```ts
interface AnalyzedTrack {
  schemaVersion: string;
  trackId: string;
  source: TrackAsset;
  analyzer: AnalyzerProvenance;
  durationSeconds: number;
  tempo: TempoAnalysis;
  key: KeyAnalysis;
  beatGrid: BeatGrid;
  sections: TrackSection[];
  energy: EnergyAnalysis;
  vocals: VocalAnalysis;
  stems?: StemSet;
  cuePoints: CuePoint[];
  quality: AnalysisQuality;
}
```

### AnalyzerProvenance

```ts
interface AnalyzerProvenance {
  producer: string;
  producerVersion: string;
  createdAtUtc: string;
  sourceContentHash?: string;
  parametersHash?: string;
}
```

### TempoAnalysis

```ts
interface TempoAnalysis {
  bpm: number;
  normalizedBpm: number;
  confidence: number;
  tempoClass?: "halftime" | "straight" | "doubletime";
  candidates?: Array<{ bpm: number; confidence: number }>;
}
```

For dubstep, normalize 70/75 BPM and 140/150 BPM relationships explicitly so
the DJ strategy can reason about halftime and doubletime compatibility.

### KeyAnalysis

```ts
interface KeyAnalysis {
  tonic: string;
  mode: "major" | "minor" | "unknown";
  camelot?: string;
  confidence: number;
  candidates?: Array<{ tonic: string; mode: string; confidence: number }>;
}
```

### BeatGrid

```ts
interface BeatGrid {
  beats: BeatMarker[];
  downbeats: BeatMarker[];
  confidence: number;
}

interface BeatMarker {
  index: number;
  timeSeconds: number;
  beatInBar?: number;
  confidence?: number;
}
```

### TrackSection

```ts
type SectionType =
  | "intro"
  | "verse"
  | "build"
  | "drop"
  | "breakdown"
  | "bridge"
  | "outro"
  | "unknown";

interface TrackSection {
  id: string;
  type: SectionType;
  startSeconds: number;
  endSeconds: number;
  startBeatIndex?: number;
  endBeatIndex?: number;
  energyMean?: number;
  energyPeak?: number;
  vocalPresence?: number;
  confidence: number;
}
```

### EnergyAnalysis

```ts
interface EnergyAnalysis {
  globalEnergy: number;
  curve: Array<{ timeSeconds: number; value: number }>;
  bassEnergyCurve?: Array<{ timeSeconds: number; value: number }>;
  onsetDensityCurve?: Array<{ timeSeconds: number; value: number }>;
}
```

### VocalAnalysis

```ts
interface VocalAnalysis {
  hasVocals: boolean;
  confidence: number;
  regions: Array<{
    startSeconds: number;
    endSeconds: number;
    presence: number;
    confidence: number;
  }>;
}
```

### StemSet

```ts
interface StemSet {
  producer: string;
  producerVersion: string;
  stems: {
    vocals?: string;
    drums?: string;
    bass?: string;
    other?: string;
    instrumental?: string;
  };
  quality?: {
    vocalBleedEstimate?: number;
    artifactEstimate?: number;
  };
}
```

### CuePoint

```ts
type CuePointType =
  | "mix_in"
  | "mix_out"
  | "drop"
  | "build_start"
  | "breakdown_start"
  | "vocal_start"
  | "vocal_end"
  | "loop_candidate";

interface CuePoint {
  id: string;
  type: CuePointType;
  timeSeconds: number;
  beatIndex?: number;
  sectionId?: string;
  confidence: number;
  tags?: string[];
}
```

## DJStrategy

```ts
interface DJStrategy {
  readonly strategyId: string;
  readonly supportedGenres: string[];

  prepare(tracks: AnalyzedTrack[]): Promise<void>;
  generatePlan(options: SetOptions): Promise<MixPlan>;
  nextSegment?(context: DJContext): Promise<MixSegment>;
}

interface SetOptions {
  targetDurationSeconds?: number;
  randomSeed?: string;
  preferredEnergyArc?: "ramp" | "wave" | "peak_early" | "peak_late";
  maxTracks?: number;
  allowVocals?: boolean;
  allowStemTransitions?: boolean;
}
```

The MVP should implement `generatePlan()` first. `nextSegment()` is reserved for
future infinite/adaptive playback.

## MixPlan

```ts
interface MixPlan {
  schemaVersion: string;
  planId: string;
  createdAtUtc: string;
  strategy: {
    strategyId: string;
    strategyVersion: string;
    randomSeed?: string;
  };
  tracks: TrackPlacement[];
  transitions: TransitionEdge[];
  commands: DeckCommand[];
  annotations?: PlanAnnotation[];
}
```

### TrackPlacement

```ts
interface TrackPlacement {
  placementId: string;
  trackId: string;
  deck: number;
  sourceStartSeconds: number;
  sourceEndSeconds?: number;
  timelineStartSeconds: number;
  timelineEndSeconds?: number;
  role?: "primary" | "incoming" | "acapella" | "loop" | "stem";
}
```

### TransitionEdge

```ts
type TransitionTechnique =
  | "intro_outro_blend"
  | "build_to_drop_swap"
  | "loop_tighten"
  | "vocal_over_instrumental"
  | "echo_out"
  | "hard_cut";

interface TransitionEdge {
  transitionId: string;
  fromPlacementId: string;
  toPlacementId: string;
  technique: TransitionTechnique;
  timelineStartSeconds: number;
  timelineEndSeconds: number;
  score: number;
  reasons: string[];
  riskFlags?: string[];
}
```

Transitions live as edges because they describe the relationship between two or
more placements.

## DeckCommand

```ts
type DeckCommand =
  | LoadCommand
  | PlayCommand
  | StopCommand
  | SeekCommand
  | LoopCommand
  | ClearLoopCommand
  | AutomationCommand;

interface LoadCommand {
  type: "load";
  at: TimelineSeconds;
  deck: number;
  trackId: string;
  stem?: "full" | "vocals" | "drums" | "bass" | "other" | "instrumental";
  cueSeconds: TrackSeconds;
}

interface PlayCommand {
  type: "play";
  at: TimelineSeconds;
  deck: number;
}

interface StopCommand {
  type: "stop";
  at: TimelineSeconds;
  deck: number;
}

interface SeekCommand {
  type: "seek";
  at: TimelineSeconds;
  deck: number;
  toSeconds: TrackSeconds;
}

interface LoopCommand {
  type: "setLoop";
  at: TimelineSeconds;
  deck: number;
  startSeconds: TrackSeconds;
  lengthBeats: number;
}

interface ClearLoopCommand {
  type: "clearLoop";
  at: TimelineSeconds;
  deck: number;
}

interface AutomationCommand {
  type: "automate";
  deck?: number;
  control: ControlName;
  keyframes: Keyframe[];
}
```

## Controls

```ts
type ControlName =
  | "volume"
  | "eqLow"
  | "eqMid"
  | "eqHigh"
  | "filter"
  | "reverbWet"
  | "echoWet"
  | "tempo"
  | "crossfader";

interface Keyframe {
  at: TimelineSeconds;
  value: number;
  interpolation?: "hold" | "linear" | "smoothstep" | "exponential";
}
```

Suggested control ranges:

- `volume`: `0.0` to `1.0`
- `eqLow`, `eqMid`, `eqHigh`: `0.0` to `1.0` for MVP, later dB ranges.
- `filter`: `-1.0` low-pass to `1.0` high-pass, `0.0` neutral.
- `reverbWet`, `echoWet`: `0.0` to `1.0`
- `tempo`: playback ratio where `1.0` is unchanged.
- `crossfader`: `-1.0` left to `1.0` right, `0.0` center.

## PlaybackEngine

```ts
interface PlaybackEngine {
  loadPlan(plan: MixPlan): Promise<PlanValidationResult>;
  play(): void;
  pause(): void;
  stop(): void;
  seek(timelineSeconds: number): void;
  getState(): PlaybackState;
}

interface PlanValidationResult {
  ok: boolean;
  errors: PlanValidationIssue[];
  warnings: PlanValidationIssue[];
}
```

The engine should reject invalid plans before playback whenever possible.

## Example Transition Snippet

```json
{
  "transitionId": "tx-004",
  "fromPlacementId": "place-track-a",
  "toPlacementId": "place-track-b",
  "technique": "build_to_drop_swap",
  "timelineStartSeconds": 184.0,
  "timelineEndSeconds": 216.0,
  "score": 0.86,
  "reasons": [
    "BPM normalized match within 0.5",
    "Phrase-aligned 32-bar build",
    "Compatible Camelot keys",
    "Incoming drop energy higher than outgoing drop"
  ]
}
```
