#pragma once

#include "autodj/repository/audio_repository.hpp"
#include "autodj/repository/metadata_cache_paths.hpp"

#include <filesystem>
#include <optional>
#include <string>
#include <string_view>

namespace autodj::repository {

struct RepositoryManifestReadResult final {
    std::filesystem::path manifestPath;
    std::optional<RepositoryManifest> manifest;
    std::optional<RepositoryError> error;

    [[nodiscard]] bool ok() const noexcept { return manifest.has_value() && !error.has_value(); }
};

[[nodiscard]] RepositoryManifestReadResult parseRepositoryManifest(std::string_view json,
                                                                   std::string sourceUri = {});

[[nodiscard]] RepositoryManifestReadResult readRepositoryManifest(const std::filesystem::path& manifestPath);

[[nodiscard]] RepositoryManifestReadResult readRepositoryManifest(const MetadataCachePaths& cachePaths);

}  // namespace autodj::repository
