#include "autodj/repository/repository.hpp"

#include <cassert>
#include <chrono>
#include <fstream>
#include <filesystem>
#include <sstream>
#include <string>
#include <stdexcept>
#include <system_error>
#include <type_traits>
#include <utility>
#include <vector>

namespace {

class TempDirectory final {
public:
    TempDirectory()
        : path_(std::filesystem::temp_directory_path()
                / ("autodj-repository-tests-"
                   + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()))) {
        std::filesystem::create_directories(path_);
    }

    ~TempDirectory() {
        std::error_code ignored;
        std::filesystem::remove_all(path_, ignored);
    }

    [[nodiscard]] const std::filesystem::path& path() const noexcept { return path_; }

private:
    std::filesystem::path path_;
};

void write_file(const std::filesystem::path& path, const std::string& contents) {
    std::filesystem::create_directories(path.parent_path());
    std::ofstream file{path, std::ios::binary};
    file << contents;
}

std::string read_file_text(const std::filesystem::path& path) {
    std::ifstream file{path, std::ios::binary};
    std::ostringstream contents;
    contents << file.rdbuf();
    return contents.str();
}

autodj::repository::RepositoryManifest example_manifest(const std::filesystem::path& rootPath) {
    const autodj::repository::TrackAsset track{
        .trackId = autodj::domain::TrackId{"track-drop-001"},
        .repositoryId = "local-manifest-writer",
        .sourcePath = rootPath / "drop.wav",
        .sourceUri = (rootPath / "drop.wav").lexically_normal().generic_string(),
        .contentHash = "sha256:abc123",
        .formatHint = "wav",
        .title = "Drop \"One\"\nMix",
        .artist = "AutoDJ Fixture",
        .album = "Writer Tests",
        .durationSeconds = 180.25,
        .sampleRate = 48000,
        .channels = 2,
    };

    return autodj::repository::RepositoryManifest{
        .schemaVersion = "1.0.0",
        .repositoryId = "local-manifest-writer",
        .producer = "autodj.repository.local",
        .producerVersion = "0.1.0",
        .createdAtUtc = "2026-01-01T00:00:00Z",
        .source = autodj::repository::RepositorySource{
            .repositoryType = "local",
            .rootUri = rootPath.lexically_normal().generic_string(),
        },
        .tracks = {track},
        .scan = autodj::repository::RepositoryScanSummary{
            .repositoryId = "local-manifest-writer",
            .tracksAdded = 1,
            .tracksUpdated = 0,
            .tracksRemoved = 0,
            .errors = {autodj::repository::RepositoryError{
                .code = "file_hash_unreadable",
                .message = "Could not read test file",
                .sourceUri = (rootPath / "bad.wav").lexically_normal().generic_string(),
                .trackId = autodj::domain::TrackId{"track-bad"},
            }},
        },
    };
}

autodj::repository::RepositoryManifest manifest_from_scan(const std::filesystem::path& rootPath,
                                                          const autodj::repository::RepositoryScanResult& scan) {
    return autodj::repository::RepositoryManifest{
        .schemaVersion = "1.0.0",
        .repositoryId = scan.repositoryId,
        .producer = "autodj.repository.local",
        .producerVersion = "0.1.0",
        .createdAtUtc = "2026-01-01T00:00:00Z",
        .source = autodj::repository::RepositorySource{
            .repositoryType = "local",
            .rootUri = rootPath.lexically_normal().generic_string(),
        },
        .tracks = scan.tracks,
        .scan = autodj::repository::RepositoryScanSummary{
            .repositoryId = scan.repositoryId,
            .tracksAdded = scan.tracksAdded,
            .tracksUpdated = scan.tracksUpdated,
            .tracksRemoved = scan.tracksRemoved,
            .errors = scan.errors,
        },
    };
}

autodj::repository::RepositoryManifestProvenance test_provenance() {
    return autodj::repository::RepositoryManifestProvenance{
        .producer = "autodj.repository.local",
        .producerVersion = "0.1.0",
        .createdAtUtc = "2026-01-01T00:00:00Z",
    };
}

void local_repository_is_constructible_with_root_and_id() {
    const std::filesystem::path root{"C:/example/music"};
    const autodj::repository::LocalAudioRepository repository{root, "local-test"};

    assert(repository.repositoryId() == "local-test");
    assert(repository.rootPath() == root);
}

void local_repository_implements_audio_repository_contract() {
    static_assert(std::is_base_of_v<autodj::repository::IAudioRepository,
                                    autodj::repository::LocalAudioRepository>);

    autodj::repository::LocalAudioRepository local{"C:/example/music", "local-contract"};
    autodj::repository::IAudioRepository& repository = local;

    assert(repository.repositoryId() == "local-contract");
}

void scan_of_empty_existing_root_reports_no_tracks_or_errors() {
    const TempDirectory root;
    autodj::repository::LocalAudioRepository repository{root.path(), "local-scan"};

    const auto result = repository.scan();

    assert(result.repositoryId == "local-scan");
    assert(result.tracks.empty());
    assert(result.tracksAdded == 0);
    assert(result.tracksUpdated == 0);
    assert(result.tracksRemoved == 0);
    assert(result.ok());
    assert(!result.changed());
}

void placeholder_track_listing_is_empty() {
    const TempDirectory root;
    const autodj::repository::LocalAudioRepository repository{root.path(), "local-empty"};

    const auto tracks = repository.listTracks();

    assert(tracks.empty());
}

void scan_discovers_wav_and_mp3_files_recursively_case_insensitively() {
    const TempDirectory root;
    write_file(root.path() / "drop.WAV", "fake wav bytes");
    write_file(root.path() / "nested" / "build.mp3", "fake mp3 bytes");
    write_file(root.path() / "nested" / "upper.MP3", "fake upper mp3 bytes");
    write_file(root.path() / "notes.txt", "not audio");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-discovery"};
    const auto result = repository.scan();

    assert(result.ok());
    assert(result.tracks.size() == 3);
    assert(result.tracksAdded == 3);
    assert(repository.listTracks().size() == 3);
    assert(result.tracks[0].repositoryId == "local-discovery");
    assert(result.tracks[0].sourcePath.filename() == "drop.WAV");
    assert(result.tracks[0].formatHint == "wav");
    assert(result.tracks[1].sourcePath.filename() == "build.mp3");
    assert(result.tracks[1].formatHint == "mp3");
    assert(result.tracks[2].sourcePath.filename() == "upper.MP3");
    assert(result.tracks[2].formatHint == "mp3");
}

void scan_ignores_unsupported_files_and_cache_directory() {
    const TempDirectory root;
    write_file(root.path() / "include.wav", "include");
    write_file(root.path() / "ignore.flac", "unsupported");
    write_file(root.path() / ".autodj-cache" / "cached.mp3", "cache should be ignored");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-filter"};
    const auto result = repository.scan();

    assert(result.ok());
    assert(result.tracks.size() == 1);
    assert(result.tracks.front().sourcePath.filename() == "include.wav");
}

void scan_returns_tracks_in_deterministic_relative_path_order() {
    const TempDirectory root;
    write_file(root.path() / "z-last.wav", "z");
    write_file(root.path() / "a-first.mp3", "a");
    write_file(root.path() / "nested" / "m-middle.wav", "m");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-order"};
    const auto result = repository.scan();

    assert(result.ok());
    assert(result.tracks.size() == 3);
    assert(result.tracks[0].sourcePath.filename() == "a-first.mp3");
    assert(result.tracks[1].sourcePath.filename() == "m-middle.wav");
    assert(result.tracks[2].sourcePath.filename() == "z-last.wav");
}

void track_ids_are_stable_across_repeated_scans() {
    const TempDirectory root;
    write_file(root.path() / "nested" / "Drop.WAV", "fake wav bytes");

    autodj::repository::LocalAudioRepository firstRepository{root.path(), "local-stable"};
    const auto firstResult = firstRepository.scan();

    autodj::repository::LocalAudioRepository secondRepository{root.path(), "local-stable"};
    const auto secondResult = secondRepository.scan();

    assert(firstResult.ok());
    assert(secondResult.ok());
    assert(firstResult.tracks.size() == 1);
    assert(secondResult.tracks.size() == 1);
    assert(firstResult.tracks.front().trackId.value == secondResult.tracks.front().trackId.value);
    assert(firstResult.tracks.front().trackId.value.find("track-nested-drop-wav-") == 0);
    assert(firstResult.tracks.front().trackId.value.size() > std::string{"track-nested-drop-wav-"}.size());
}

void track_ids_are_scoped_by_repository_id() {
    const TempDirectory root;
    write_file(root.path() / "drop.wav", "fake wav bytes");

    autodj::repository::LocalAudioRepository firstRepository{root.path(), "local-one"};
    autodj::repository::LocalAudioRepository secondRepository{root.path(), "local-two"};

    const auto firstResult = firstRepository.scan();
    const auto secondResult = secondRepository.scan();

    assert(firstResult.ok());
    assert(secondResult.ok());
    assert(firstResult.tracks.size() == 1);
    assert(secondResult.tracks.size() == 1);
    assert(firstResult.tracks.front().trackId.value != secondResult.tracks.front().trackId.value);
}

void discovered_tracks_include_normalized_source_metadata() {
    const TempDirectory root;
    write_file(root.path() / "nested" / "drop.wav", "fake wav bytes");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-source"};
    const auto result = repository.scan();

    assert(result.ok());
    assert(result.tracks.size() == 1);

    const auto& track = result.tracks.front();
    assert(track.repositoryId == "local-source");
    assert(track.formatHint == "wav");
    assert(track.contentHash.find("sha256:") == 0);
    assert(track.sourceUri.find('\\') == std::string::npos);
    assert(track.sourceUri.find("nested/drop.wav") != std::string::npos);
}

void content_hashes_are_sha256_prefixed_and_stable_for_unchanged_files() {
    const TempDirectory root;
    write_file(root.path() / "drop.wav", "abc");

    autodj::repository::LocalAudioRepository firstRepository{root.path(), "local-hash"};
    const auto firstResult = firstRepository.scan();

    autodj::repository::LocalAudioRepository secondRepository{root.path(), "local-hash"};
    const auto secondResult = secondRepository.scan();

    const std::string expectedHash =
        "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

    assert(firstResult.ok());
    assert(secondResult.ok());
    assert(firstResult.tracks.size() == 1);
    assert(secondResult.tracks.size() == 1);
    assert(firstResult.tracks.front().contentHash == expectedHash);
    assert(secondResult.tracks.front().contentHash == expectedHash);
    assert(firstResult.tracks.front().contentHash == secondResult.tracks.front().contentHash);
}

void content_hash_changes_when_file_bytes_change() {
    const TempDirectory root;
    const auto path = root.path() / "drop.wav";
    write_file(path, "first bytes");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-hash-change"};
    const auto firstResult = repository.scan();

    write_file(path, "second bytes");
    const auto secondResult = repository.scan();

    assert(firstResult.ok());
    assert(secondResult.ok());
    assert(firstResult.tracks.size() == 1);
    assert(secondResult.tracks.size() == 1);
    assert(firstResult.tracks.front().trackId.value == secondResult.tracks.front().trackId.value);
    assert(firstResult.tracks.front().contentHash != secondResult.tracks.front().contentHash);
}

void metadata_cache_paths_default_under_repository_root() {
    const TempDirectory repositoryRoot;

    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(repositoryRoot.path());
    const auto expectedRoot = (repositoryRoot.path() / ".autodj-cache").lexically_normal();

    assert(paths.root() == expectedRoot);
    assert(paths.repositoryManifestPath() == expectedRoot / "repository-manifest.json");
    assert(paths.tracksRoot() == expectedRoot / "tracks");
    assert(!std::filesystem::exists(expectedRoot));
}

void metadata_cache_paths_use_configured_cache_root() {
    const TempDirectory repositoryRoot;
    const auto customRoot = (repositoryRoot.path() / "custom-cache").lexically_normal();

    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(repositoryRoot.path(), customRoot);
    const autodj::repository::MetadataCachePaths directPaths{customRoot};

    assert(paths.root() == customRoot);
    assert(directPaths.root() == customRoot);
    assert(paths.repositoryManifestPath() == customRoot / "repository-manifest.json");
}

void metadata_cache_paths_resolve_track_artifact_locations() {
    const TempDirectory repositoryRoot;
    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(repositoryRoot.path());
    const autodj::domain::TrackId trackId{"track-drop-123"};
    const auto trackRoot = paths.root() / "tracks" / "track-drop-123";

    assert(paths.trackRoot(trackId) == trackRoot);
    assert(paths.analyzedTrackPath(trackId) == trackRoot / "analyzed-track.json");
    assert(paths.waveformPath(trackId) == trackRoot / "waveform.json");
    assert(paths.stemsDirectory(trackId) == trackRoot / "stems");
}

void metadata_cache_path_resolution_does_not_create_artifacts() {
    const TempDirectory repositoryRoot;
    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(repositoryRoot.path());
    const autodj::domain::TrackId trackId{"track-read-only"};

    (void)paths.repositoryManifestPath();
    (void)paths.trackRoot(trackId);
    (void)paths.analyzedTrackPath(trackId);
    (void)paths.waveformPath(trackId);
    (void)paths.stemsDirectory(trackId);

    assert(!std::filesystem::exists(paths.root()));
}

void metadata_cache_helpers_create_directories_only_when_explicitly_requested() {
    const TempDirectory repositoryRoot;
    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(repositoryRoot.path());
    const autodj::domain::TrackId trackId{"track-create-dirs"};

    const auto error = paths.ensureTrackDirectories(trackId);

    assert(!error);
    assert(std::filesystem::is_directory(paths.root()));
    assert(std::filesystem::is_directory(paths.tracksRoot()));
    assert(std::filesystem::is_directory(paths.trackRoot(trackId)));
    assert(std::filesystem::is_directory(paths.stemsDirectory(trackId)));
    assert(!std::filesystem::exists(paths.repositoryManifestPath()));
    assert(!std::filesystem::exists(paths.analyzedTrackPath(trackId)));
    assert(!std::filesystem::exists(paths.waveformPath(trackId)));
}

void metadata_cache_helpers_reject_empty_track_ids_for_directory_creation() {
    const TempDirectory repositoryRoot;
    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(repositoryRoot.path());

    const auto error = paths.ensureTrackDirectories(autodj::domain::TrackId{});

    assert(error == std::errc::invalid_argument);
    assert(!std::filesystem::exists(paths.root()));
}

void repository_manifest_writer_writes_to_default_cache_manifest_path() {
    const TempDirectory repositoryRoot;
    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(repositoryRoot.path());
    const auto manifest = example_manifest(repositoryRoot.path());

    const auto result = autodj::repository::writeRepositoryManifest(manifest, paths);

    assert(result.ok());
    assert(result.manifestPath == paths.repositoryManifestPath());
    assert(std::filesystem::exists(paths.repositoryManifestPath()));

    const auto json = read_file_text(paths.repositoryManifestPath());
    assert(json.find("\"schemaVersion\": \"1.0.0\"") != std::string::npos);
    assert(json.find("\"repositoryId\": \"local-manifest-writer\"") != std::string::npos);
    assert(json.find("\"producer\": \"autodj.repository.local\"") != std::string::npos);
    assert(json.find("\"producerVersion\": \"0.1.0\"") != std::string::npos);
    assert(json.find("\"createdAtUtc\": \"2026-01-01T00:00:00Z\"") != std::string::npos);
    assert(json.find("\"source\": {") != std::string::npos);
    assert(json.find("\"repositoryType\": \"local\"") != std::string::npos);
    assert(json.find("\"tracks\": [") != std::string::npos);
    assert(json.find("\"scan\": {") != std::string::npos);
}

void repository_manifest_writer_writes_to_caller_provided_path() {
    const TempDirectory repositoryRoot;
    const auto manifestPath = repositoryRoot.path() / "custom" / "repository-manifest.json";
    const auto manifest = example_manifest(repositoryRoot.path());

    const auto result = autodj::repository::writeRepositoryManifest(manifest, manifestPath);

    assert(result.ok());
    assert(result.manifestPath == manifestPath.lexically_normal());
    assert(std::filesystem::exists(manifestPath));
}

void repository_manifest_writer_includes_track_fields_and_omits_local_source_path() {
    const TempDirectory repositoryRoot;
    const auto manifest = example_manifest(repositoryRoot.path());
    const auto json = autodj::repository::serializeRepositoryManifest(manifest);

    assert(json.find("\"trackId\": \"track-drop-001\"") != std::string::npos);
    assert(json.find("\"repositoryId\": \"local-manifest-writer\"") != std::string::npos);
    assert(json.find("\"sourceUri\":") != std::string::npos);
    assert(json.find("\"contentHash\": \"sha256:abc123\"") != std::string::npos);
    assert(json.find("\"formatHint\": \"wav\"") != std::string::npos);
    assert(json.find("\"title\": \"Drop \\\"One\\\"\\nMix\"") != std::string::npos);
    assert(json.find("\"artist\": \"AutoDJ Fixture\"") != std::string::npos);
    assert(json.find("\"album\": \"Writer Tests\"") != std::string::npos);
    assert(json.find("\"durationSeconds\": 180.25") != std::string::npos);
    assert(json.find("\"sampleRate\": 48000") != std::string::npos);
    assert(json.find("\"channels\": 2") != std::string::npos);
    assert(json.find("sourcePath") == std::string::npos);
}

void repository_manifest_writer_includes_scan_summary_and_errors() {
    const TempDirectory repositoryRoot;
    const auto manifest = example_manifest(repositoryRoot.path());
    const auto json = autodj::repository::serializeRepositoryManifest(manifest);

    assert(json.find("\"tracksAdded\": 1") != std::string::npos);
    assert(json.find("\"tracksUpdated\": 0") != std::string::npos);
    assert(json.find("\"tracksRemoved\": 0") != std::string::npos);
    assert(json.find("\"errors\": [") != std::string::npos);
    assert(json.find("\"code\": \"file_hash_unreadable\"") != std::string::npos);
    assert(json.find("\"message\": \"Could not read test file\"") != std::string::npos);
    assert(json.find("\"trackId\": \"track-bad\"") != std::string::npos);
}

void repository_manifest_serialization_is_deterministic() {
    const TempDirectory repositoryRoot;
    const auto manifest = example_manifest(repositoryRoot.path());

    assert(autodj::repository::serializeRepositoryManifest(manifest)
           == autodj::repository::serializeRepositoryManifest(manifest));
}

void repository_manifest_writer_reports_empty_path_errors() {
    const TempDirectory repositoryRoot;
    const auto manifest = example_manifest(repositoryRoot.path());

    const auto result = autodj::repository::writeRepositoryManifest(manifest, std::filesystem::path{});

    assert(!result.ok());
    assert(result.error.has_value());
    assert(result.error->code == "manifest_path_empty");
}

void repository_manifest_reader_roundtrips_written_manifest() {
    const TempDirectory repositoryRoot;
    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(repositoryRoot.path());
    const auto manifest = example_manifest(repositoryRoot.path());

    const auto writeResult = autodj::repository::writeRepositoryManifest(manifest, paths);
    const auto readResult = autodj::repository::readRepositoryManifest(paths);

    assert(writeResult.ok());
    assert(readResult.ok());
    assert(readResult.manifestPath == paths.repositoryManifestPath());
    assert(readResult.manifest.has_value());

    const auto& readManifest = readResult.manifest.value();
    assert(readManifest.schemaVersion == "1.0.0");
    assert(readManifest.repositoryId == manifest.repositoryId);
    assert(readManifest.producer == manifest.producer);
    assert(readManifest.producerVersion == manifest.producerVersion);
    assert(readManifest.createdAtUtc == manifest.createdAtUtc);
    assert(readManifest.source.repositoryType == "local");
    assert(readManifest.source.rootUri == manifest.source.rootUri);
    assert(readManifest.tracks.size() == 1);
    assert(readManifest.tracks.front().trackId.value == "track-drop-001");
    assert(readManifest.tracks.front().repositoryId == "local-manifest-writer");
    assert(readManifest.tracks.front().sourcePath.empty());
    assert(readManifest.tracks.front().sourceUri == manifest.tracks.front().sourceUri);
    assert(readManifest.tracks.front().contentHash == "sha256:abc123");
    assert(readManifest.tracks.front().formatHint == "wav");
    assert(readManifest.tracks.front().title.value() == "Drop \"One\"\nMix");
    assert(readManifest.tracks.front().artist.value() == "AutoDJ Fixture");
    assert(readManifest.tracks.front().album.value() == "Writer Tests");
    assert(readManifest.tracks.front().durationSeconds.value() == 180.25);
    assert(readManifest.tracks.front().sampleRate.value() == 48000);
    assert(readManifest.tracks.front().channels.value() == 2);
    assert(readManifest.scan.repositoryId == "local-manifest-writer");
    assert(readManifest.scan.tracksAdded == 1);
    assert(readManifest.scan.tracksUpdated == 0);
    assert(readManifest.scan.tracksRemoved == 0);
    assert(readManifest.scan.errors.size() == 1);
    assert(readManifest.scan.errors.front().code == "file_hash_unreadable");
    assert(readManifest.scan.errors.front().message == "Could not read test file");
    assert(readManifest.scan.errors.front().trackId.value().value == "track-bad");
}

void repository_manifest_reader_parses_serialized_manifest_text() {
    const TempDirectory repositoryRoot;
    const auto manifest = example_manifest(repositoryRoot.path());

    const auto readResult = autodj::repository::parseRepositoryManifest(autodj::repository::serializeRepositoryManifest(manifest));

    assert(readResult.ok());
    assert(readResult.manifest.has_value());
    assert(readResult.manifest->repositoryId == "local-manifest-writer");
    assert(readResult.manifest->tracks.front().title.value() == "Drop \"One\"\nMix");
}

void repository_manifest_reader_reports_malformed_json() {
    const auto result = autodj::repository::parseRepositoryManifest("{\"schemaVersion\": ");

    assert(!result.ok());
    assert(result.error.has_value());
    assert(result.error->code == "manifest_parse_error");
}

void repository_manifest_reader_reports_unsupported_schema_versions() {
    const TempDirectory repositoryRoot;
    auto manifest = example_manifest(repositoryRoot.path());
    manifest.schemaVersion = "9.9.9";

    const auto result = autodj::repository::parseRepositoryManifest(autodj::repository::serializeRepositoryManifest(manifest));

    assert(!result.ok());
    assert(result.error.has_value());
    assert(result.error->code == "manifest_schema_unsupported");
}

void repository_manifest_reader_reports_missing_required_fields() {
    const auto result = autodj::repository::parseRepositoryManifest(R"({
  "schemaVersion": "1.0.0",
  "producer": "autodj.repository.local",
  "producerVersion": "0.1.0",
  "createdAtUtc": "2026-01-01T00:00:00Z",
  "source": { "repositoryType": "local", "rootUri": "C:/Music" },
  "tracks": [],
  "scan": { "repositoryId": "missing-repo", "tracksAdded": 0, "tracksUpdated": 0, "tracksRemoved": 0, "errors": [] }
})");

    assert(!result.ok());
    assert(result.error.has_value());
    assert(result.error->code == "manifest_missing_field");
}

void repository_manifest_reader_reports_file_read_errors() {
    const TempDirectory repositoryRoot;
    const auto missingPath = repositoryRoot.path() / ".autodj-cache" / "repository-manifest.json";

    const auto result = autodj::repository::readRepositoryManifest(missingPath);

    assert(!result.ok());
    assert(result.error.has_value());
    assert(result.error->code == "manifest_read_error");
    assert(result.error->sourceUri.value() == missingPath.lexically_normal().generic_string());
}

void scan_without_prior_manifest_reports_all_discovered_tracks_added() {
    const TempDirectory root;
    write_file(root.path() / "first.wav", "first");
    write_file(root.path() / "second.mp3", "second");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-initial-scan"};
    const auto result = repository.scan();

    assert(result.ok());
    assert(result.tracks.size() == 2);
    assert(result.tracksAdded == 2);
    assert(result.tracksUpdated == 0);
    assert(result.tracksRemoved == 0);
}

void scan_with_prior_manifest_reports_unchanged_files_as_unchanged() {
    const TempDirectory root;
    write_file(root.path() / "drop.wav", "same bytes");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-unchanged"};
    const auto initialScan = repository.scan();
    const auto priorManifest = manifest_from_scan(root.path(), initialScan);

    const auto nextScan = repository.scan(priorManifest);

    assert(nextScan.ok());
    assert(nextScan.tracks.size() == 1);
    assert(nextScan.tracksAdded == 0);
    assert(nextScan.tracksUpdated == 0);
    assert(nextScan.tracksRemoved == 0);
    assert(!nextScan.changed());
}

void scan_with_prior_manifest_reports_content_updates() {
    const TempDirectory root;
    const auto path = root.path() / "drop.wav";
    write_file(path, "old bytes");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-updated"};
    const auto initialScan = repository.scan();
    const auto priorManifest = manifest_from_scan(root.path(), initialScan);

    write_file(path, "new bytes");
    const auto nextScan = repository.scan(priorManifest);

    assert(nextScan.ok());
    assert(nextScan.tracks.size() == 1);
    assert(nextScan.tracksAdded == 0);
    assert(nextScan.tracksUpdated == 1);
    assert(nextScan.tracksRemoved == 0);
    assert(nextScan.changed());
    assert(nextScan.tracks.front().trackId.value == initialScan.tracks.front().trackId.value);
    assert(nextScan.tracks.front().contentHash != initialScan.tracks.front().contentHash);
}

void scan_with_prior_manifest_reports_removed_files() {
    const TempDirectory root;
    const auto path = root.path() / "drop.wav";
    write_file(path, "drop");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-removed"};
    const auto initialScan = repository.scan();
    const auto priorManifest = manifest_from_scan(root.path(), initialScan);

    std::filesystem::remove(path);
    const auto nextScan = repository.scan(priorManifest);

    assert(nextScan.ok());
    assert(nextScan.tracks.empty());
    assert(nextScan.tracksAdded == 0);
    assert(nextScan.tracksUpdated == 0);
    assert(nextScan.tracksRemoved == 1);
}

void scan_with_prior_manifest_treats_renames_as_removed_plus_added() {
    const TempDirectory root;
    const auto originalPath = root.path() / "old-name.wav";
    const auto renamedPath = root.path() / "new-name.wav";
    write_file(originalPath, "same bytes");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-renamed"};
    const auto initialScan = repository.scan();
    const auto priorManifest = manifest_from_scan(root.path(), initialScan);

    std::filesystem::rename(originalPath, renamedPath);
    const auto nextScan = repository.scan(priorManifest);

    assert(nextScan.ok());
    assert(nextScan.tracks.size() == 1);
    assert(nextScan.tracksAdded == 1);
    assert(nextScan.tracksUpdated == 0);
    assert(nextScan.tracksRemoved == 1);
    assert(nextScan.tracks.front().trackId.value != initialScan.tracks.front().trackId.value);
    assert(nextScan.tracks.front().contentHash == initialScan.tracks.front().contentHash);
}

void standalone_scan_comparison_preserves_scan_errors() {
    const TempDirectory root;
    auto currentScan = autodj::repository::RepositoryScanResult{
        .repositoryId = "local-compare-errors",
        .tracks = {},
        .tracksAdded = 1,
        .tracksUpdated = 0,
        .tracksRemoved = 0,
        .errors = {autodj::repository::RepositoryError{
            .code = "file_hash_unreadable",
            .message = "Could not read test file",
        }},
    };
    const auto priorManifest = manifest_from_scan(root.path(), currentScan);

    const auto compared = autodj::repository::compareScanResultToManifest(std::move(currentScan), priorManifest);

    assert(!compared.ok());
    assert(compared.errors.size() == 1);
    assert(compared.errors.front().code == "file_hash_unreadable");
}

void scan_workflow_missing_manifest_behaves_like_first_scan_and_persists_manifest() {
    const TempDirectory root;
    write_file(root.path() / "first.wav", "first");
    write_file(root.path() / "second.mp3", "second");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-workflow-first"};
    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(root.path());

    const auto result = autodj::repository::scanCompareAndPersist(repository, paths, test_provenance());

    assert(result.ok());
    assert(!result.previousManifest.has_value());
    assert(result.scan.tracks.size() == 2);
    assert(result.scan.tracksAdded == 2);
    assert(result.scan.tracksUpdated == 0);
    assert(result.scan.tracksRemoved == 0);
    assert(result.write.ok());
    assert(result.write.manifestPath == paths.repositoryManifestPath());

    const auto read = autodj::repository::readRepositoryManifest(paths);
    assert(read.ok());
    assert(read.manifest.has_value());
    assert(read.manifest->repositoryId == "local-workflow-first");
    assert(read.manifest->source.repositoryType == "local");
    assert(read.manifest->source.rootUri == root.path().lexically_normal().generic_string());
    assert(read.manifest->tracks.size() == 2);
    assert(read.manifest->scan.tracksAdded == 2);
}

void scan_workflow_uses_prior_manifest_for_unchanged_rescan() {
    const TempDirectory root;
    write_file(root.path() / "drop.wav", "same bytes");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-workflow-unchanged"};
    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(root.path());

    const auto initial = autodj::repository::scanCompareAndPersist(repository, paths, test_provenance());
    const auto next = autodj::repository::scanCompareAndPersist(repository, paths, test_provenance());

    assert(initial.ok());
    assert(initial.scan.tracksAdded == 1);
    assert(next.ok());
    assert(next.previousManifest.has_value());
    assert(next.scan.tracks.size() == 1);
    assert(next.scan.tracksAdded == 0);
    assert(next.scan.tracksUpdated == 0);
    assert(next.scan.tracksRemoved == 0);
    assert(!next.scan.changed());

    const auto read = autodj::repository::readRepositoryManifest(paths);
    assert(read.ok());
    assert(read.manifest->scan.tracksAdded == 0);
    assert(read.manifest->scan.tracksUpdated == 0);
    assert(read.manifest->scan.tracksRemoved == 0);
}

void scan_workflow_persists_updates_after_content_changes() {
    const TempDirectory root;
    const auto trackPath = root.path() / "drop.wav";
    write_file(trackPath, "old bytes");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-workflow-updated"};
    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(root.path());

    const auto initial = autodj::repository::scanCompareAndPersist(repository, paths, test_provenance());
    write_file(trackPath, "new bytes");
    const auto next = autodj::repository::scanCompareAndPersist(repository, paths, test_provenance());

    assert(initial.ok());
    assert(next.ok());
    assert(next.previousManifest.has_value());
    assert(next.scan.tracks.size() == 1);
    assert(next.scan.tracksAdded == 0);
    assert(next.scan.tracksUpdated == 1);
    assert(next.scan.tracksRemoved == 0);
    assert(next.scan.tracks.front().contentHash != initial.scan.tracks.front().contentHash);

    const auto read = autodj::repository::readRepositoryManifest(paths);
    assert(read.ok());
    assert(read.manifest->tracks.size() == 1);
    assert(read.manifest->tracks.front().contentHash == next.scan.tracks.front().contentHash);
    assert(read.manifest->scan.tracksUpdated == 1);
}

void scan_workflow_preserves_tracks_when_prior_manifest_is_malformed() {
    const TempDirectory root;
    write_file(root.path() / "drop.wav", "drop");
    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(root.path());
    write_file(paths.repositoryManifestPath(), "{\"schemaVersion\": ");

    autodj::repository::LocalAudioRepository repository{root.path(), "local-workflow-malformed-prior"};
    const auto result = autodj::repository::scanCompareAndPersist(repository, paths, test_provenance());

    assert(!result.ok());
    assert(!result.previousManifest.has_value());
    assert(result.scan.tracks.size() == 1);
    assert(result.scan.tracksAdded == 1);
    assert(result.scan.errors.size() == 1);
    assert(result.scan.errors.front().code == "manifest_parse_error");
    assert(result.write.ok());

    const auto read = autodj::repository::readRepositoryManifest(paths);
    assert(read.ok());
    assert(read.manifest->tracks.size() == 1);
    assert(read.manifest->scan.errors.size() == 1);
    assert(read.manifest->scan.errors.front().code == "manifest_parse_error");
}

void scan_workflow_preserves_successful_tracks_when_file_errors_are_reported() {
    const TempDirectory root;
    write_file(root.path() / "good.wav", "good");

    class RepositoryWithFileError final : public autodj::repository::IAudioRepository {
    public:
        explicit RepositoryWithFileError(std::filesystem::path sourcePath) : sourcePath_(std::move(sourcePath)) {}

        [[nodiscard]] std::string repositoryId() const override { return "local-workflow-file-error"; }

        [[nodiscard]] std::vector<autodj::repository::TrackAsset> listTracks() const override { return {track()}; }

        autodj::repository::RepositoryScanResult scan() override {
            return autodj::repository::RepositoryScanResult{
                .repositoryId = repositoryId(),
                .tracks = {track()},
                .tracksAdded = 1,
                .tracksUpdated = 0,
                .tracksRemoved = 0,
                .errors = {autodj::repository::RepositoryError{
                    .code = "file_hash_unreadable",
                    .message = "Could not read test file",
                    .sourceUri = (sourcePath_.parent_path() / "bad.mp3").lexically_normal().generic_string(),
                    .trackId = autodj::domain::TrackId{"track-bad"},
                }},
            };
        }

    private:
        [[nodiscard]] autodj::repository::TrackAsset track() const {
            return autodj::repository::TrackAsset{
                .trackId = autodj::domain::TrackId{"track-good"},
                .repositoryId = repositoryId(),
                .sourcePath = sourcePath_,
                .sourceUri = sourcePath_.lexically_normal().generic_string(),
                .contentHash = "sha256:good",
                .formatHint = "wav",
            };
        }

        std::filesystem::path sourcePath_;
    };

    RepositoryWithFileError repository{root.path() / "good.wav"};
    const auto paths = autodj::repository::MetadataCachePaths::forRepositoryRoot(root.path());
    const auto result = autodj::repository::scanCompareAndPersist(
        repository,
        paths,
        autodj::repository::RepositorySource{
            .repositoryType = "local",
            .rootUri = root.path().lexically_normal().generic_string(),
        },
        test_provenance());

    assert(!result.ok());
    assert(result.scan.tracks.size() == 1);
    assert(result.scan.tracks.front().sourcePath.filename() == "good.wav");
    assert(result.scan.errors.front().code == "file_hash_unreadable");
    assert(result.write.ok());

    const auto read = autodj::repository::readRepositoryManifest(paths);
    assert(read.ok());
    assert(read.manifest->tracks.size() == 1);
    assert(read.manifest->scan.errors.size() == 1);
    assert(read.manifest->scan.errors.front().code == "file_hash_unreadable");
}

void scan_missing_root_returns_structured_error() {
    const TempDirectory root;
    const auto missing = root.path() / "missing";
    autodj::repository::LocalAudioRepository repository{missing, "local-missing"};

    const auto result = repository.scan();

    assert(result.tracks.empty());
    assert(!result.ok());
    assert(result.errors.size() == 1);
    assert(result.errors.front().code == "root_missing");
    assert(result.errors.front().sourceUri.value() == missing.generic_string());
    assert(repository.listTracks().empty());
}

void track_assets_expose_contract_fields() {
    const autodj::repository::TrackAsset track{
        .trackId = autodj::domain::TrackId{"track-local-001"},
        .repositoryId = "local-test",
        .sourcePath = std::filesystem::path{"C:/example/music/track.wav"},
        .sourceUri = "file:///example/music/track.wav",
        .contentHash = "sha256:abc123",
        .formatHint = "wav",
        .title = "Example Track",
        .artist = "Example Artist",
        .album = "Example Album",
        .durationSeconds = 123.5,
        .sampleRate = 44100,
        .channels = 2,
    };

    assert(track.trackId.value == "track-local-001");
    assert(track.repositoryId == "local-test");
    assert(track.sourcePath.filename() == "track.wav");
    assert(track.sourceUri == "file:///example/music/track.wav");
    assert(track.contentHash == "sha256:abc123");
    assert(track.formatHint == "wav");
    assert(track.title.value() == "Example Track");
    assert(track.artist.value() == "Example Artist");
    assert(track.album.value() == "Example Album");
    assert(track.durationSeconds.value() == 123.5);
    assert(track.sampleRate.value() == 44100);
    assert(track.channels.value() == 2);
}

void repository_errors_carry_structured_context() {
    const autodj::repository::RepositoryError error{
        .code = "file_unreadable",
        .message = "Could not open supported audio file",
        .sourceUri = "file:///example/music/bad.wav",
        .trackId = autodj::domain::TrackId{"track-bad"},
    };

    assert(error.code == "file_unreadable");
    assert(error.message == "Could not open supported audio file");
    assert(error.sourceUri.value() == "file:///example/music/bad.wav");
    assert(error.trackId.value().value == "track-bad");
}

void scan_summary_reports_change_and_error_state() {
    const autodj::repository::RepositoryScanSummary summary{
        .repositoryId = "local-summary",
        .tracksAdded = 1,
        .tracksUpdated = 0,
        .tracksRemoved = 1,
        .errors = {autodj::repository::RepositoryError{
            .code = "manifest_invalid",
            .message = "Manifest could not be parsed",
        }},
    };

    assert(summary.repositoryId == "local-summary");
    assert(summary.changed());
    assert(!summary.ok());
    assert(summary.errors.front().code == "manifest_invalid");
}

void scan_results_carry_tracks_and_counts() {
    const autodj::repository::TrackAsset track{
        .trackId = autodj::domain::TrackId{"track-local-002"},
        .repositoryId = "local-result",
        .sourcePath = std::filesystem::path{"C:/example/music/track.mp3"},
        .sourceUri = "file:///example/music/track.mp3",
        .contentHash = "sha256:def456",
        .formatHint = "mp3",
    };

    const autodj::repository::RepositoryScanResult result{
        .repositoryId = "local-result",
        .tracks = {track},
        .tracksAdded = 1,
        .tracksUpdated = 0,
        .tracksRemoved = 0,
        .errors = {},
    };

    assert(result.repositoryId == "local-result");
    assert(result.tracks.size() == 1);
    assert(result.tracks.front().trackId.value == "track-local-002");
    assert(result.tracksAdded == 1);
    assert(result.changed());
    assert(result.ok());
}

void repository_manifest_carries_version_source_tracks_and_scan_summary() {
    const autodj::repository::TrackAsset track{
        .trackId = autodj::domain::TrackId{"track-local-003"},
        .repositoryId = "local-manifest",
        .sourcePath = std::filesystem::path{"C:/example/music/track.wav"},
        .sourceUri = "file:///example/music/track.wav",
        .contentHash = "sha256:manifest",
        .formatHint = "wav",
    };

    const autodj::repository::RepositoryManifest manifest{
        .schemaVersion = "1.0.0",
        .repositoryId = "local-manifest",
        .producer = "autodj.repository.local",
        .producerVersion = "0.1.0",
        .createdAtUtc = "2026-01-01T00:00:00Z",
        .source = autodj::repository::RepositorySource{
            .repositoryType = "local",
            .rootUri = "file:///example/music",
        },
        .tracks = {track},
        .scan = autodj::repository::RepositoryScanSummary{
            .repositoryId = "local-manifest",
            .tracksAdded = 1,
            .tracksUpdated = 0,
            .tracksRemoved = 0,
            .errors = {},
        },
    };

    assert(manifest.schemaVersion == "1.0.0");
    assert(manifest.repositoryId == "local-manifest");
    assert(manifest.producer == "autodj.repository.local");
    assert(manifest.source.repositoryType == "local");
    assert(manifest.source.rootUri == "file:///example/music");
    assert(manifest.tracks.front().contentHash == "sha256:manifest");
    assert(manifest.scan.tracksAdded == 1);
}

void resolved_audio_assets_expose_playable_uri_fields() {
    const autodj::repository::ResolvedAudioAsset asset{
        .trackId = autodj::domain::TrackId{"track-resolved"},
        .readableUri = "file:///example/music/resolved.wav",
        .formatHint = "wav",
        .contentHash = "sha256:resolved",
    };

    assert(asset.trackId.value == "track-resolved");
    assert(asset.readableUri == "file:///example/music/resolved.wav");
    assert(asset.formatHint == "wav");
    assert(asset.contentHash == "sha256:resolved");
}

void local_repository_rejects_empty_repository_id() {
    bool threw = false;

    try {
        const autodj::repository::LocalAudioRepository repository{"C:/example/music", ""};
        (void)repository;
    } catch (const std::invalid_argument&) {
        threw = true;
    }

    assert(threw);
}

}  // namespace

int main() {
    local_repository_is_constructible_with_root_and_id();
    local_repository_implements_audio_repository_contract();
    scan_of_empty_existing_root_reports_no_tracks_or_errors();
    placeholder_track_listing_is_empty();
    scan_discovers_wav_and_mp3_files_recursively_case_insensitively();
    scan_ignores_unsupported_files_and_cache_directory();
    scan_returns_tracks_in_deterministic_relative_path_order();
    track_ids_are_stable_across_repeated_scans();
    track_ids_are_scoped_by_repository_id();
    discovered_tracks_include_normalized_source_metadata();
    content_hashes_are_sha256_prefixed_and_stable_for_unchanged_files();
    content_hash_changes_when_file_bytes_change();
    metadata_cache_paths_default_under_repository_root();
    metadata_cache_paths_use_configured_cache_root();
    metadata_cache_paths_resolve_track_artifact_locations();
    metadata_cache_path_resolution_does_not_create_artifacts();
    metadata_cache_helpers_create_directories_only_when_explicitly_requested();
    metadata_cache_helpers_reject_empty_track_ids_for_directory_creation();
    repository_manifest_writer_writes_to_default_cache_manifest_path();
    repository_manifest_writer_writes_to_caller_provided_path();
    repository_manifest_writer_includes_track_fields_and_omits_local_source_path();
    repository_manifest_writer_includes_scan_summary_and_errors();
    repository_manifest_serialization_is_deterministic();
    repository_manifest_writer_reports_empty_path_errors();
    repository_manifest_reader_roundtrips_written_manifest();
    repository_manifest_reader_parses_serialized_manifest_text();
    repository_manifest_reader_reports_malformed_json();
    repository_manifest_reader_reports_unsupported_schema_versions();
    repository_manifest_reader_reports_missing_required_fields();
    repository_manifest_reader_reports_file_read_errors();
    scan_without_prior_manifest_reports_all_discovered_tracks_added();
    scan_with_prior_manifest_reports_unchanged_files_as_unchanged();
    scan_with_prior_manifest_reports_content_updates();
    scan_with_prior_manifest_reports_removed_files();
    scan_with_prior_manifest_treats_renames_as_removed_plus_added();
    standalone_scan_comparison_preserves_scan_errors();
    scan_workflow_missing_manifest_behaves_like_first_scan_and_persists_manifest();
    scan_workflow_uses_prior_manifest_for_unchanged_rescan();
    scan_workflow_persists_updates_after_content_changes();
    scan_workflow_preserves_tracks_when_prior_manifest_is_malformed();
    scan_workflow_preserves_successful_tracks_when_file_errors_are_reported();
    scan_missing_root_returns_structured_error();
    track_assets_expose_contract_fields();
    repository_errors_carry_structured_context();
    scan_summary_reports_change_and_error_state();
    scan_results_carry_tracks_and_counts();
    repository_manifest_carries_version_source_tracks_and_scan_summary();
    resolved_audio_assets_expose_playable_uri_fields();
    local_repository_rejects_empty_repository_id();

    return 0;
}
