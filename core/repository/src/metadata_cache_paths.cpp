#include "autodj/repository/metadata_cache_paths.hpp"

#include <utility>

namespace autodj::repository {

MetadataCachePaths::MetadataCachePaths(std::filesystem::path cacheRoot)
    : cacheRoot_(std::move(cacheRoot).lexically_normal()) {}

MetadataCachePaths MetadataCachePaths::forRepositoryRoot(const std::filesystem::path& repositoryRoot) {
    return MetadataCachePaths{repositoryRoot / ".autodj-cache"};
}

MetadataCachePaths MetadataCachePaths::forRepositoryRoot(const std::filesystem::path& repositoryRoot,
                                                         std::filesystem::path cacheRoot) {
    if (cacheRoot.empty()) {
        return forRepositoryRoot(repositoryRoot);
    }
    return MetadataCachePaths{std::move(cacheRoot)};
}

const std::filesystem::path& MetadataCachePaths::root() const noexcept {
    return cacheRoot_;
}

std::filesystem::path MetadataCachePaths::repositoryManifestPath() const {
    return cacheRoot_ / "repository-manifest.json";
}

std::filesystem::path MetadataCachePaths::tracksRoot() const {
    return cacheRoot_ / "tracks";
}

std::filesystem::path MetadataCachePaths::trackRoot(const domain::TrackId& trackId) const {
    return tracksRoot() / trackId.value;
}

std::filesystem::path MetadataCachePaths::analyzedTrackPath(const domain::TrackId& trackId) const {
    return trackRoot(trackId) / "analyzed-track.json";
}

std::filesystem::path MetadataCachePaths::waveformPath(const domain::TrackId& trackId) const {
    return trackRoot(trackId) / "waveform.json";
}

std::filesystem::path MetadataCachePaths::stemsDirectory(const domain::TrackId& trackId) const {
    return trackRoot(trackId) / "stems";
}

std::error_code MetadataCachePaths::ensureRootDirectories() const {
    std::error_code error;
    std::filesystem::create_directories(tracksRoot(), error);
    return error;
}

std::error_code MetadataCachePaths::ensureTrackDirectories(const domain::TrackId& trackId) const {
    if (trackId.empty()) {
        return std::make_error_code(std::errc::invalid_argument);
    }

    auto error = ensureRootDirectories();
    if (error) {
        return error;
    }

    std::filesystem::create_directories(stemsDirectory(trackId), error);
    return error;
}

}  // namespace autodj::repository
