#include "autodj/repository/local_audio_repository.hpp"

#include <stdexcept>
#include <utility>

namespace autodj::repository {

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

std::vector<RepositoryTrack> LocalAudioRepository::listTracks() const {
    return {};
}

RepositoryScanResult LocalAudioRepository::scan() {
    return RepositoryScanResult{
        .repositoryId = repositoryId_,
        .tracksAdded = 0,
        .tracksUpdated = 0,
        .tracksRemoved = 0,
        .errors = {},
    };
}

}  // namespace autodj::repository

