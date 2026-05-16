# Requirements Document

## Introduction

This spec starts the Analysis MVP by turning the Python worker from a
single-file stub into a manifest/cache-aware batch worker. It consumes the
repository manifest produced by spec 002, probes local WAV/MP3 files with
`ffprobe`, writes `analyzed-track.json` artifacts into the metadata cache
layout, and skips artifacts that are already current.

The implementation must remain intentionally narrow. It may inspect audio file
container and stream metadata through `ffprobe`; it must not estimate BPM, key,
sections, beat grids, waveform data, vocals, stems, or transition cues in this
spec.

## Requirement 1: Batch Manifest Analysis CLI

**User Story:** As a developer, I want to analyze every track in a repository
manifest, so the cache can be populated from the imported local library.

### Acceptance Criteria

1. WHEN `autodj-analysis analyze-batch <repository-manifest.json> --out
   <cache-root>` is run THEN the worker SHALL read the repository manifest.
2. WHEN the manifest contains multiple tracks THEN the worker SHALL attempt
   every track and produce a batch summary.
3. WHEN the command completes THEN the summary SHALL include analyzed, skipped,
   failed, and total counts.
4. WHEN `--json` is provided THEN the summary SHALL be emitted as parseable JSON.
5. WHEN the manifest cannot be read or parsed THEN the command SHALL fail with a
   nonzero exit code and an actionable error.

## Requirement 2: Repository Manifest Consumption

**User Story:** As an analysis worker, I want to consume repository manifests,
so analysis uses the same track identity and content hashes as ingestion.

### Acceptance Criteria

1. WHEN a valid manifest is read THEN the worker SHALL recover repository ID,
   source metadata, track IDs, source URIs, content hashes, titles where
   available, albums/artists where available, and format hints where available.
2. WHEN required manifest fields are absent or the JSON is malformed THEN the
   worker SHALL return a structured or explicit error.
3. WHEN a track has a relative or platform-specific source URI THEN the worker
   SHALL resolve it consistently for local probing without changing the stored
   source URI.
4. WHEN a manifest track has a content hash THEN the worker SHALL copy it into
   analyzer provenance as `sourceContentHash`.

## Requirement 3: Metadata Cache Layout

**User Story:** As an analysis developer, I want analyzed artifacts written to
the cache layout from spec 002, so later DJ and playback modules can find them.

### Acceptance Criteria

1. WHEN a track is analyzed THEN the worker SHALL write
   `<cache-root>/tracks/<track-id>/analyzed-track.json`.
2. WHEN parent directories are missing THEN the worker SHALL create only the
   directories required for the analyzed artifact.
3. WHEN writing an artifact THEN the worker SHALL write atomically to avoid
   leaving partial JSON at the final path.
4. WHEN resolving paths THEN the worker SHALL not create waveform or stem
   artifacts in this spec.

## Requirement 4: FFprobe Metadata Probe

**User Story:** As a listener/developer, I want the worker to read real file
metadata, so duration and stream fields are no longer hardcoded.

### Acceptance Criteria

1. WHEN a local audio file is probed successfully THEN the worker SHALL populate
   duration seconds from `ffprobe` stream or format metadata.
2. WHEN a local audio file is probed successfully THEN the worker SHALL populate
   sample rate and channel count from the selected audio stream.
3. WHEN codec, format, bit rate, or tags are available THEN the worker SHALL
   preserve useful fields under provider metadata.
4. WHEN `ffprobe` is missing, returns a nonzero exit code, emits invalid JSON,
   or finds no audio stream THEN the worker SHALL return a per-track failure.
5. WHEN one track fails probing THEN other tracks in the same batch SHALL still
   be analyzed or skipped.

## Requirement 5: AnalyzedTrack Artifact Shape

**User Story:** As a downstream module, I want analyzed-track artifacts to match
the contract, so later strategy and playback work can consume them.

### Acceptance Criteria

1. WHEN an artifact is written THEN it SHALL match
   `core/contracts/schemas/analyzed-track.schema.json` at the required top-level
   shape.
2. WHEN a repository track is analyzed THEN the artifact SHALL preserve the
   repository `TrackAsset` identity fields.
3. WHEN real probed metadata exists THEN the artifact SHALL include real
   duration, sample rate, channel count, and provider metadata.
4. WHEN musical analysis has not been implemented THEN tempo, key, beat grid,
   sections, energy, vocals, and cue point fields SHALL be marked as
   placeholders or low-confidence.
5. WHEN an artifact is inspected THEN `quality.warnings` SHALL clearly state
   that only FFprobe metadata was analyzed.

## Requirement 6: Cache Invalidation And Skipping

**User Story:** As a user, I want repeated analysis to skip unchanged tracks, so
the app does not redo unnecessary work.

### Acceptance Criteria

1. WHEN an existing artifact has matching `schemaVersion`, `trackId`,
   `analyzer.producer`, `analyzer.producerVersion`,
   `analyzer.sourceContentHash`, and `analyzer.parametersHash` THEN the batch
   worker SHALL skip it.
2. WHEN the source content hash changes THEN the batch worker SHALL rewrite the
   artifact.
3. WHEN the analyzer version or parameters hash changes THEN the batch worker
   SHALL rewrite the artifact.
4. WHEN existing artifact JSON is malformed or missing required fields THEN the
   batch worker SHALL rewrite it.
5. WHEN `--force` is passed THEN the batch worker SHALL rewrite artifacts even
   if they are current.

## Requirement 7: Error Handling And Observability

**User Story:** As a maintainer, I want clear analysis errors and summaries, so
bad files do not make the pipeline opaque.

### Acceptance Criteria

1. WHEN a per-track failure occurs THEN the summary SHALL include the track ID,
   source URI, error code, and message.
2. WHEN the batch has any per-track failures THEN the command SHALL return a
   nonzero exit code after processing all possible tracks.
3. WHEN verbose or JSON output is requested THEN the output SHALL be suitable
   for later UI integration.
4. WHEN expected failures occur THEN the worker SHALL avoid stack traces unless
   an unexpected programming error is raised.

## Requirement 8: Documentation And Status

**User Story:** As a future implementation agent, I want accurate docs, so the
project status and commands are not misleading.

### Acceptance Criteria

1. WHEN this spec is implemented THEN `README.md` SHALL describe spec 002 as
   complete and mention the current analysis batch workflow.
2. WHEN this spec is implemented THEN README commands SHALL include
   `analyze-batch`.
3. WHEN this spec is implemented THEN docs SHALL still warn not to commit local
   media or generated cache artifacts.

## Requirement 9: Verification

**User Story:** As a future task executor, I want repeatable verification, so
analysis changes do not regress ingestion or foundation behavior.

### Acceptance Criteria

1. WHEN implementation completes THEN Python worker tests SHALL pass.
2. WHEN implementation completes THEN `python -m autodj_analysis --help` SHALL
   pass.
3. WHEN implementation completes THEN `python -m autodj_analysis analyze-batch
   --help` SHALL pass.
4. WHEN implementation completes THEN `cmake --preset debug` SHALL configure.
5. WHEN implementation completes THEN `cmake --build --preset debug` SHALL
   build all C++ targets.
6. WHEN implementation completes THEN `ctest --preset debug` SHALL pass all C++
   tests.
7. WHEN a task is completed THEN `tasks.md` SHALL be updated to mark only the
   completed verified work.
