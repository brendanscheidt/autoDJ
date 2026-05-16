#pragma once

#include "autodj/domain/domain.hpp"

#include <string>
#include <vector>

namespace autodj::playback {

enum class TransportState {
    Stopped,
    Playing,
    Paused,
};

struct PlanValidationIssue final {
    std::string code;
    std::string message;
};

struct PlanValidationResult final {
    bool ok{false};
    std::vector<PlanValidationIssue> errors;
    std::vector<PlanValidationIssue> warnings;
};

struct PlaybackState final {
    TransportState transport{TransportState::Stopped};
    domain::TimelineSeconds timelineSeconds{0.0};
    bool hasLoadedPlan{false};
};

class PlaybackEngine final {
public:
    [[nodiscard]] PlanValidationResult loadPlan(const std::string& planJson);

    void play() noexcept;
    void pause() noexcept;
    void stop() noexcept;
    [[nodiscard]] bool seek(domain::TimelineSeconds timelineSeconds) noexcept;

    [[nodiscard]] PlaybackState getState() const noexcept;

private:
    PlaybackState state_{};
};

}  // namespace autodj::playback

