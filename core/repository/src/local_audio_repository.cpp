#include "autodj/repository/local_audio_repository.hpp"

#include "autodj/repository/repository_scan_comparison.hpp"
#include "sha256.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <system_error>
#include <utility>

namespace autodj::repository {
namespace {

std::string lowercased(std::string value) {
    std::ranges::transform(value, value.begin(), [](unsigned char character) {
        return static_cast<char>(std::tolower(character));
    });
    return value;
}

bool isSupportedAudioExtension(const std::filesystem::path& path) {
    const auto extension = lowercased(path.extension().string());
    return extension == ".wav" || extension == ".mp3";
}

std::string formatHintFor(const std::filesystem::path& path) {
    const auto extension = lowercased(path.extension().string());
    if (extension == ".wav") {
        return "wav";
    }
    if (extension == ".mp3") {
        return "mp3";
    }
    return "unknown";
}

std::string normalizedSourceUri(const std::filesystem::path& path) {
    return path.lexically_normal().generic_string();
}

std::filesystem::path relativePath(const std::filesystem::path& path, const std::filesystem::path& rootPath) {
    std::error_code error;
    const auto relative = std::filesystem::relative(path, rootPath, error);
    if (error) {
        return path.filename();
    }
    return relative;
}

std::string normalizedRelativePath(const std::filesystem::path& path, const std::filesystem::path& rootPath) {
    return relativePath(path, rootPath).lexically_normal().generic_string();
}

std::string slugFromRelativePath(const std::filesystem::path& relativePath) {
    std::string slug = relativePath.generic_string();
    std::ranges::transform(slug, slug.begin(), [](unsigned char character) {
        if (std::isalnum(character)) {
            return static_cast<char>(std::tolower(character));
        }
        return '-';
    });

    slug.erase(slug.begin(), std::ranges::find_if(slug, [](char character) {
                   return character != '-';
               }));
    slug.erase(std::ranges::find_if(slug.rbegin(), slug.rend(), [](char character) {
                   return character != '-';
               }).base(),
               slug.end());

    if (slug.empty()) {
        return "track";
    }
    return slug;
}

std::uint64_t fnv1a64(std::string_view value) {
    constexpr std::uint64_t offsetBasis = 14695981039346656037ULL;
    constexpr std::uint64_t prime = 1099511628211ULL;

    std::uint64_t hash = offsetBasis;
    for (const unsigned char character : value) {
        hash ^= character;
        hash *= prime;
    }
    return hash;
}

std::string first12HexOfHash(std::string_view value) {
    std::ostringstream stream;
    stream << std::hex << std::setfill('0') << std::setw(16) << fnv1a64(value);
    return stream.str().substr(0, 12);
}

domain::TrackId makeTrackId(const std::string& repositoryId, const std::filesystem::path& normalizedRelativePath) {
    const auto relativePathText = normalizedRelativePath.generic_string();
    const auto identityInput = repositoryId + "\n" + relativePathText;
    return domain::TrackId{
        "track-" + slugFromRelativePath(normalizedRelativePath) + "-" + first12HexOfHash(identityInput),
    };
}

domain::TrackId makeTrackIdForPath(const std::filesystem::path& path,
                                   const std::filesystem::path& rootPath,
                                   const std::string& repositoryId) {
    return makeTrackId(repositoryId, relativePath(path, rootPath).lexically_normal());
}

struct FileHashResult final {
    std::optional<std::string> contentHash;
    std::string errorMessage;
};

FileHashResult hashFileContent(const std::filesystem::path& path) {
    std::ifstream file{path, std::ios::binary};
    if (!file) {
        return FileHashResult{
            .contentHash = std::nullopt,
            .errorMessage = "Could not open supported audio file for hashing",
        };
    }

    detail::Sha256 hasher;
    std::array<char, 32 * 1024> buffer{};
    while (file) {
        file.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const auto bytesRead = file.gcount();
        if (bytesRead > 0) {
            hasher.update(buffer.data(), static_cast<std::size_t>(bytesRead));
        }
    }

    if (file.bad()) {
        return FileHashResult{
            .contentHash = std::nullopt,
            .errorMessage = "Could not read supported audio file for hashing",
        };
    }

    return FileHashResult{
        .contentHash = "sha256:" + detail::hexEncoded(hasher.finalize()),
        .errorMessage = {},
    };
}

TrackAsset makeDiscoveredTrack(const std::filesystem::path& path,
                               const std::filesystem::path& rootPath,
                               const std::string& repositoryId,
                               std::string contentHash) {
    return TrackAsset{
        .trackId = makeTrackIdForPath(path, rootPath, repositoryId),
        .repositoryId = repositoryId,
        .sourcePath = path,
        .sourceUri = normalizedSourceUri(path),
        .contentHash = std::move(contentHash),
        .formatHint = formatHintFor(path),
    };
}

bool isCacheDirectory(const std::filesystem::directory_entry& entry) {
    return entry.path().filename() == ".autodj-cache";
}

}  // namespace

LocalAudioRepository::LocalAudioRepository(std::filesystem::path rootPath, std::string repositoryId)
    : rootPath_(std::move(rootPath)), repositoryId_(std::move(repositoryId)) {
    if (repositoryId_.empty()) {
        throw std::invalid_argument("LocalAudioRepository requires a non-empty repository id");
    }
}

std::string LocalAudioRepository::repositoryId() const {
    return repositoryId_;
}

const std::filesystem::path& LocalAudioRepository::rootPath() const noexcept {
    return rootPath_;
}

std::vector<TrackAsset> LocalAudioRepository::listTracks() const {
    return tracks_;
}

RepositoryScanResult LocalAudioRepository::scan() {
    std::vector<RepositoryError> errors;
    std::vector<TrackAsset> discoveredTracks;

    std::error_code error;
    if (!std::filesystem::exists(rootPath_, error)) {
        tracks_.clear();
        return RepositoryScanResult{
            .repositoryId = repositoryId_,
            .tracks = {},
            .tracksAdded = 0,
            .tracksUpdated = 0,
            .tracksRemoved = 0,
            .errors = {RepositoryError{
                .code = "root_missing",
                .message = "Repository root does not exist",
                .sourceUri = rootPath_.generic_string(),
            }},
        };
    }

    if (error || !std::filesystem::is_directory(rootPath_, error)) {
        tracks_.clear();
        return RepositoryScanResult{
            .repositoryId = repositoryId_,
            .tracks = {},
            .tracksAdded = 0,
            .tracksUpdated = 0,
            .tracksRemoved = 0,
            .errors = {RepositoryError{
                .code = "root_not_directory",
                .message = "Repository root is not a directory",
                .sourceUri = rootPath_.generic_string(),
            }},
        };
    }

    constexpr auto options = std::filesystem::directory_options::skip_permission_denied;
    for (std::filesystem::recursive_directory_iterator iterator{rootPath_, options, error}, end;
         iterator != end;
         iterator.increment(error)) {
        if (error) {
            errors.push_back(RepositoryError{
                .code = "scan_iteration_error",
                .message = error.message(),
            });
            error.clear();
            continue;
        }

        const auto& entry = *iterator;
        if (entry.is_directory(error)) {
            if (!error && isCacheDirectory(entry)) {
                iterator.disable_recursion_pending();
            }
            error.clear();
            continue;
        }

        if (error) {
            errors.push_back(RepositoryError{
                .code = "file_type_error",
                .message = error.message(),
                .sourceUri = entry.path().generic_string(),
            });
            error.clear();
            continue;
        }

        if (!entry.is_regular_file(error)) {
            error.clear();
            continue;
        }

        if (error) {
            errors.push_back(RepositoryError{
                .code = "file_type_error",
                .message = error.message(),
                .sourceUri = entry.path().generic_string(),
            });
            error.clear();
            continue;
        }

        if (!isSupportedAudioExtension(entry.path())) {
            continue;
        }

        const auto trackId = makeTrackIdForPath(entry.path(), rootPath_, repositoryId_);
        auto hashResult = hashFileContent(entry.path());
        if (!hashResult.contentHash.has_value()) {
            errors.push_back(RepositoryError{
                .code = "file_hash_unreadable",
                .message = std::move(hashResult.errorMessage),
                .sourceUri = normalizedSourceUri(entry.path()),
                .trackId = trackId,
            });
            continue;
        }

        auto contentHash = std::move(hashResult.contentHash).value();
        discoveredTracks.push_back(makeDiscoveredTrack(entry.path(), rootPath_, repositoryId_, std::move(contentHash)));
    }

    if (error) {
        errors.push_back(RepositoryError{
            .code = "scan_iteration_error",
            .message = error.message(),
        });
        error.clear();
    }

    std::ranges::sort(discoveredTracks, [this](const TrackAsset& left, const TrackAsset& right) {
        return normalizedRelativePath(left.sourcePath, rootPath_) < normalizedRelativePath(right.sourcePath, rootPath_);
    });

    tracks_ = discoveredTracks;

    return RepositoryScanResult{
        .repositoryId = repositoryId_,
        .tracks = tracks_,
        .tracksAdded = tracks_.size(),
        .tracksUpdated = 0,
        .tracksRemoved = 0,
        .errors = std::move(errors),
    };
}

RepositoryScanResult LocalAudioRepository::scan(const RepositoryManifest& previousManifest) {
    return compareScanResultToManifest(scan(), previousManifest);
}

}  // namespace autodj::repository
