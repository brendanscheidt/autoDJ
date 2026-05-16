#include "autodj/repository/repository_manifest_writer.hpp"

#include <fstream>
#include <iomanip>
#include <sstream>
#include <system_error>
#include <utility>

namespace autodj::repository {
namespace {

std::string jsonString(const std::string& value) {
    std::ostringstream output;
    output << '"';
    for (const unsigned char character : value) {
        switch (character) {
            case '"':
                output << "\\\"";
                break;
            case '\\':
                output << "\\\\";
                break;
            case '\b':
                output << "\\b";
                break;
            case '\f':
                output << "\\f";
                break;
            case '\n':
                output << "\\n";
                break;
            case '\r':
                output << "\\r";
                break;
            case '\t':
                output << "\\t";
                break;
            default:
                if (character < 0x20U) {
                    output << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(character)
                           << std::dec << std::setfill(' ');
                } else {
                    output << static_cast<char>(character);
                }
                break;
        }
    }
    output << '"';
    return output.str();
}

std::string jsonNumber(double value) {
    std::ostringstream output;
    output << std::setprecision(15) << value;
    return output.str();
}

void appendRepositoryError(std::ostringstream& output, const RepositoryError& error, const std::string& indent) {
    output << indent << "{\n";
    output << indent << "  \"code\": " << jsonString(error.code) << ",\n";
    output << indent << "  \"message\": " << jsonString(error.message);

    if (error.sourceUri.has_value()) {
        output << ",\n" << indent << "  \"sourceUri\": " << jsonString(error.sourceUri.value());
    }
    if (error.trackId.has_value()) {
        output << ",\n" << indent << "  \"trackId\": " << jsonString(error.trackId.value().value);
    }

    output << "\n" << indent << "}";
}

void appendTrackAsset(std::ostringstream& output, const TrackAsset& track, const std::string& indent) {
    output << indent << "{\n";
    output << indent << "  \"trackId\": " << jsonString(track.trackId.value) << ",\n";
    output << indent << "  \"repositoryId\": " << jsonString(track.repositoryId) << ",\n";
    output << indent << "  \"sourceUri\": " << jsonString(track.sourceUri);

    if (!track.contentHash.empty()) {
        output << ",\n" << indent << "  \"contentHash\": " << jsonString(track.contentHash);
    }
    if (track.title.has_value()) {
        output << ",\n" << indent << "  \"title\": " << jsonString(track.title.value());
    }
    if (track.artist.has_value()) {
        output << ",\n" << indent << "  \"artist\": " << jsonString(track.artist.value());
    }
    if (track.album.has_value()) {
        output << ",\n" << indent << "  \"album\": " << jsonString(track.album.value());
    }
    if (track.durationSeconds.has_value()) {
        output << ",\n" << indent << "  \"durationSeconds\": " << jsonNumber(track.durationSeconds.value());
    }
    if (track.sampleRate.has_value()) {
        output << ",\n" << indent << "  \"sampleRate\": " << track.sampleRate.value();
    }
    if (track.channels.has_value()) {
        output << ",\n" << indent << "  \"channels\": " << track.channels.value();
    }
    output << ",\n" << indent << "  \"formatHint\": " << jsonString(track.formatHint);
    output << "\n" << indent << "}";
}

void appendScanSummary(std::ostringstream& output, const RepositoryScanSummary& scan, const std::string& indent) {
    output << indent << "{\n";
    output << indent << "  \"repositoryId\": " << jsonString(scan.repositoryId) << ",\n";
    output << indent << "  \"tracksAdded\": " << scan.tracksAdded << ",\n";
    output << indent << "  \"tracksUpdated\": " << scan.tracksUpdated << ",\n";
    output << indent << "  \"tracksRemoved\": " << scan.tracksRemoved << ",\n";
    output << indent << "  \"errors\": [";
    if (!scan.errors.empty()) {
        output << "\n";
        for (std::size_t index = 0; index < scan.errors.size(); ++index) {
            appendRepositoryError(output, scan.errors[index], indent + "    ");
            if (index + 1 < scan.errors.size()) {
                output << ",";
            }
            output << "\n";
        }
        output << indent << "  ";
    }
    output << "]\n";
    output << indent << "}";
}

RepositoryError makeWriteError(std::string code, std::string message, const std::filesystem::path& path) {
    return RepositoryError{
        .code = std::move(code),
        .message = std::move(message),
        .sourceUri = path.lexically_normal().generic_string(),
    };
}

}  // namespace

std::string serializeRepositoryManifest(const RepositoryManifest& manifest) {
    std::ostringstream output;

    output << "{\n";
    output << "  \"schemaVersion\": " << jsonString(manifest.schemaVersion) << ",\n";
    output << "  \"repositoryId\": " << jsonString(manifest.repositoryId) << ",\n";
    output << "  \"producer\": " << jsonString(manifest.producer) << ",\n";
    output << "  \"producerVersion\": " << jsonString(manifest.producerVersion) << ",\n";
    output << "  \"createdAtUtc\": " << jsonString(manifest.createdAtUtc) << ",\n";
    output << "  \"source\": {\n";
    output << "    \"repositoryType\": " << jsonString(manifest.source.repositoryType) << ",\n";
    output << "    \"rootUri\": " << jsonString(manifest.source.rootUri) << "\n";
    output << "  },\n";
    output << "  \"tracks\": [";
    if (!manifest.tracks.empty()) {
        output << "\n";
        for (std::size_t index = 0; index < manifest.tracks.size(); ++index) {
            appendTrackAsset(output, manifest.tracks[index], "    ");
            if (index + 1 < manifest.tracks.size()) {
                output << ",";
            }
            output << "\n";
        }
        output << "  ";
    }
    output << "],\n";
    output << "  \"scan\": ";
    appendScanSummary(output, manifest.scan, "");
    output << "\n";
    output << "}\n";

    return output.str();
}

RepositoryManifestWriteResult writeRepositoryManifest(const RepositoryManifest& manifest,
                                                      const std::filesystem::path& manifestPath) {
    const auto normalizedPath = manifestPath.lexically_normal();
    if (normalizedPath.empty()) {
        return RepositoryManifestWriteResult{
            .manifestPath = normalizedPath,
            .error = makeWriteError("manifest_path_empty", "Repository manifest path is empty", normalizedPath),
        };
    }

    std::error_code filesystemError;
    const auto parentPath = normalizedPath.parent_path();
    if (!parentPath.empty()) {
        std::filesystem::create_directories(parentPath, filesystemError);
        if (filesystemError) {
            return RepositoryManifestWriteResult{
                .manifestPath = normalizedPath,
                .error = makeWriteError("manifest_directory_error", filesystemError.message(), normalizedPath),
            };
        }
    }

    std::ofstream file{normalizedPath, std::ios::binary | std::ios::trunc};
    if (!file) {
        return RepositoryManifestWriteResult{
            .manifestPath = normalizedPath,
            .error = makeWriteError("manifest_write_error", "Could not open repository manifest for writing", normalizedPath),
        };
    }

    file << serializeRepositoryManifest(manifest);
    if (!file) {
        return RepositoryManifestWriteResult{
            .manifestPath = normalizedPath,
            .error = makeWriteError("manifest_write_error", "Could not write repository manifest", normalizedPath),
        };
    }

    return RepositoryManifestWriteResult{
        .manifestPath = normalizedPath,
        .error = std::nullopt,
    };
}

RepositoryManifestWriteResult writeRepositoryManifest(const RepositoryManifest& manifest,
                                                      const MetadataCachePaths& cachePaths) {
    return writeRepositoryManifest(manifest, cachePaths.repositoryManifestPath());
}

}  // namespace autodj::repository
