#pragma once

#include "autodj/repository/audio_repository.hpp"
#include "autodj/repository/local_audio_repository.hpp"
#include "autodj/repository/metadata_cache_paths.hpp"
#include "autodj/repository/repository_manifest_writer.hpp"

#include <optional>
#include <string>

namespace autodj::repository {

struct RepositoryManifestProvenance final {
    std::string producer{"autodj.repository.local"};
    std::string producerVersion{"0.1.0"};
    std::string createdAtUtc;
};

struct RepositoryScanWorkflowResult final {
    std::optional<RepositoryManifest> previousManifest;
    RepositoryScanResult scan;
    RepositoryManifest manifest;
    RepositoryManifestWriteResult write;

    [[nodiscard]] bool ok() const noexcept { return scan.ok() && write.ok(); }
};

[[nodiscard]] RepositorySource makeLocalRepositorySource(const LocalAudioRepository& repository);

[[nodiscard]] RepositoryManifest makeRepositoryManifest(const RepositoryScanResult& scan,
                                                        RepositorySource source,
                                                        const RepositoryManifestProvenance& provenance);

[[nodiscard]] RepositoryScanWorkflowResult scanCompareAndPersist(IAudioRepository& repository,
                                                                 const MetadataCachePaths& cachePaths,
                                                                 RepositorySource source,
                                                                 const RepositoryManifestProvenance& provenance);

[[nodiscard]] RepositoryScanWorkflowResult scanCompareAndPersist(LocalAudioRepository& repository,
                                                                 const MetadataCachePaths& cachePaths,
                                                                 const RepositoryManifestProvenance& provenance);

}  // namespace autodj::repository
