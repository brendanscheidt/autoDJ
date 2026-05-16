#pragma once

#include "autodj/domain/domain.hpp"

#include <cstddef>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace autodj::repository {

struct RepositoryError final {
    std::string code;
    std::string message;
    std::optional<std::string> sourceUri;
    std::optional<domain::TrackId> trackId;
};

struct TrackAsset final {
    domain::TrackId trackId;
    std::string repositoryId;
    std::filesystem::path sourcePath;
    std::string sourceUri;
    std::string contentHash;
    std::string formatHint{"unknown"};
    std::optional<std::string> title;
    std::optional<std::string> artist;
    std::optional<std::string> album;
    std::optional<double> durationSeconds;
    std::optional<int> sampleRate;
    std::optional<int> channels;
};

using RepositoryTrack = TrackAsset;

struct RepositoryScanSummary final {
    std::string repositoryId;
    std::size_t tracksAdded{0};
    std::size_t tracksUpdated{0};
    std::size_t tracksRemoved{0};
    std::vector<RepositoryError> errors;

    [[nodiscard]] bool changed() const noexcept {
        return tracksAdded != 0 || tracksUpdated != 0 || tracksRemoved != 0;
    }

    [[nodiscard]] bool ok() const noexcept { return errors.empty(); }
};

struct RepositoryScanResult final {
    std::string repositoryId;
    std::vector<TrackAsset> tracks;
    std::size_t tracksAdded{0};
    std::size_t tracksUpdated{0};
    std::size_t tracksRemoved{0};
    std::vector<RepositoryError> errors;

    [[nodiscard]] bool changed() const noexcept {
        return tracksAdded != 0 || tracksUpdated != 0 || tracksRemoved != 0;
    }

    [[nodiscard]] bool ok() const noexcept { return errors.empty(); }
};

struct RepositorySource final {
    std::string repositoryType;
    std::string rootUri;
};

struct RepositoryManifest final {
    std::string schemaVersion{"1.0.0"};
    std::string repositoryId;
    std::string producer;
    std::string producerVersion;
    std::string createdAtUtc;
    RepositorySource source;
    std::vector<TrackAsset> tracks;
    RepositoryScanSummary scan;
};

struct ResolvedAudioAsset final {
    domain::TrackId trackId;
    std::string readableUri;
    std::string formatHint{"unknown"};
    std::string contentHash;
};

class IAudioRepository {
public:
    virtual ~IAudioRepository() = default;

    [[nodiscard]] virtual std::string repositoryId() const = 0;
    [[nodiscard]] virtual std::vector<TrackAsset> listTracks() const = 0;
    virtual RepositoryScanResult scan() = 0;
};

}  // namespace autodj::repository
