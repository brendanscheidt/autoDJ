#include "autodj/repository/repository_scan_workflow.hpp"

#include "autodj/repository/repository_manifest_reader.hpp"
#include "autodj/repository/repository_scan_comparison.hpp"

#include <filesystem>
#include <system_error>
#include <utility>

namespace autodj::repository {
namespace {

std::optional<RepositoryError> manifestExistsError(const std::filesystem::path& manifestPath,
                                                   const std::error_code& error) {
    if (!error) {
        return std::nullopt;
    }

    return RepositoryError{
        .code = "manifest_read_error",
        .message = error.message(),
        .sourceUri = manifestPath.lexically_normal().generic_string(),
    };
}

}  // namespace

RepositorySource makeLocalRepositorySource(const LocalAudioRepository& repository) {
    return RepositorySource{
        .repositoryType = "local",
        .rootUri = repository.rootPath().lexically_normal().generic_string(),
    };
}

RepositoryManifest makeRepositoryManifest(const RepositoryScanResult& scan,
                                          RepositorySource source,
                                          const RepositoryManifestProvenance& provenance) {
    return RepositoryManifest{
        .schemaVersion = "1.0.0",
        .repositoryId = scan.repositoryId,
        .producer = provenance.producer,
        .producerVersion = provenance.producerVersion,
        .createdAtUtc = provenance.createdAtUtc,
        .source = std::move(source),
        .tracks = scan.tracks,
        .scan = RepositoryScanSummary{
            .repositoryId = scan.repositoryId,
            .tracksAdded = scan.tracksAdded,
            .tracksUpdated = scan.tracksUpdated,
            .tracksRemoved = scan.tracksRemoved,
            .errors = scan.errors,
        },
    };
}

RepositoryScanWorkflowResult scanCompareAndPersist(IAudioRepository& repository,
                                                   const MetadataCachePaths& cachePaths,
                                                   RepositorySource source,
                                                   const RepositoryManifestProvenance& provenance) {
    std::optional<RepositoryManifest> previousManifest;
    std::optional<RepositoryError> priorManifestError;

    const auto manifestPath = cachePaths.repositoryManifestPath();
    std::error_code filesystemError;
    const auto manifestExists = std::filesystem::exists(manifestPath, filesystemError);
    priorManifestError = manifestExistsError(manifestPath, filesystemError);

    if (manifestExists && !priorManifestError.has_value()) {
        auto read = readRepositoryManifest(manifestPath);
        if (read.ok()) {
            previousManifest = std::move(read.manifest).value();
        } else if (read.error.has_value()) {
            priorManifestError = std::move(read.error).value();
        }
    }

    auto scan = repository.scan();
    if (previousManifest.has_value()) {
        scan = compareScanResultToManifest(std::move(scan), previousManifest.value());
    }
    if (priorManifestError.has_value()) {
        scan.errors.push_back(std::move(priorManifestError).value());
    }

    auto manifest = makeRepositoryManifest(scan, std::move(source), provenance);
    auto write = writeRepositoryManifest(manifest, cachePaths);

    return RepositoryScanWorkflowResult{
        .previousManifest = std::move(previousManifest),
        .scan = std::move(scan),
        .manifest = std::move(manifest),
        .write = std::move(write),
    };
}

RepositoryScanWorkflowResult scanCompareAndPersist(LocalAudioRepository& repository,
                                                   const MetadataCachePaths& cachePaths,
                                                   const RepositoryManifestProvenance& provenance) {
    return scanCompareAndPersist(repository, cachePaths, makeLocalRepositorySource(repository), provenance);
}

}  // namespace autodj::repository
