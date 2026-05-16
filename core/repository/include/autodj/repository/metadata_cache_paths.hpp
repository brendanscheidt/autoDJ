#pragma once

#include "autodj/domain/domain.hpp"

#include <filesystem>
#include <system_error>

namespace autodj::repository {

class MetadataCachePaths final {
public:
    explicit MetadataCachePaths(std::filesystem::path cacheRoot);

    [[nodiscard]] static MetadataCachePaths forRepositoryRoot(const std::filesystem::path& repositoryRoot);
    [[nodiscard]] static MetadataCachePaths forRepositoryRoot(const std::filesystem::path& repositoryRoot,
                                                              std::filesystem::path cacheRoot);

    [[nodiscard]] const std::filesystem::path& root() const noexcept;
    [[nodiscard]] std::filesystem::path repositoryManifestPath() const;
    [[nodiscard]] std::filesystem::path tracksRoot() const;
    [[nodiscard]] std::filesystem::path trackRoot(const domain::TrackId& trackId) const;
    [[nodiscard]] std::filesystem::path analyzedTrackPath(const domain::TrackId& trackId) const;
    [[nodiscard]] std::filesystem::path waveformPath(const domain::TrackId& trackId) const;
    [[nodiscard]] std::filesystem::path stemsDirectory(const domain::TrackId& trackId) const;

    [[nodiscard]] std::error_code ensureRootDirectories() const;
    [[nodiscard]] std::error_code ensureTrackDirectories(const domain::TrackId& trackId) const;

private:
    std::filesystem::path cacheRoot_;
};

}  // namespace autodj::repository
