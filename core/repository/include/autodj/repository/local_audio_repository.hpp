#pragma once

#include "autodj/repository/audio_repository.hpp"

#include <filesystem>
#include <string>
#include <vector>

namespace autodj::repository {

class LocalAudioRepository final : public IAudioRepository {
public:
    explicit LocalAudioRepository(std::filesystem::path rootPath, std::string repositoryId = "local");

    [[nodiscard]] std::string repositoryId() const override;
    [[nodiscard]] const std::filesystem::path& rootPath() const noexcept;
    [[nodiscard]] std::vector<RepositoryTrack> listTracks() const override;
    RepositoryScanResult scan() override;

private:
    std::filesystem::path rootPath_;
    std::string repositoryId_;
};

}  // namespace autodj::repository

