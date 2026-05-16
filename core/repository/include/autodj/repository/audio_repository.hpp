#pragma once

#include "autodj/domain/domain.hpp"

#include <cstddef>
#include <string>
#include <vector>

namespace autodj::repository {

struct RepositoryError final {
    std::string message;
};

struct RepositoryScanResult final {
    std::string repositoryId;
    std::size_t tracksAdded{0};
    std::size_t tracksUpdated{0};
    std::size_t tracksRemoved{0};
    std::vector<RepositoryError> errors;

    [[nodiscard]] bool changed() const noexcept {
        return tracksAdded != 0 || tracksUpdated != 0 || tracksRemoved != 0;
    }

    [[nodiscard]] bool ok() const noexcept { return errors.empty(); }
};

struct RepositoryTrack final {
    domain::TrackId trackId;
    std::string sourceUri;
};

class IAudioRepository {
public:
    virtual ~IAudioRepository() = default;

    [[nodiscard]] virtual std::string repositoryId() const = 0;
    [[nodiscard]] virtual std::vector<RepositoryTrack> listTracks() const = 0;
    virtual RepositoryScanResult scan() = 0;
};

}  // namespace autodj::repository

