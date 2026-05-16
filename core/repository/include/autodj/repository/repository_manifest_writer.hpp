#pragma once

#include "autodj/repository/audio_repository.hpp"
#include "autodj/repository/metadata_cache_paths.hpp"

#include <filesystem>
#include <optional>
#include <string>

namespace autodj::repository {

struct RepositoryManifestWriteResult final {
    std::filesystem::path manifestPath;
    std::optional<RepositoryError> error;

    [[nodiscard]] bool ok() const noexcept { return !error.has_value(); }
};

[[nodiscard]] std::string serializeRepositoryManifest(const RepositoryManifest& manifest);

[[nodiscard]] RepositoryManifestWriteResult writeRepositoryManifest(const RepositoryManifest& manifest,
                                                                    const std::filesystem::path& manifestPath);

[[nodiscard]] RepositoryManifestWriteResult writeRepositoryManifest(const RepositoryManifest& manifest,
                                                                    const MetadataCachePaths& cachePaths);

}  // namespace autodj::repository
