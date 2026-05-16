#include "autodj/playback/playback_engine.hpp"

#include <cmath>
#include <string>

namespace autodj::playback {

namespace {

[[nodiscard]] bool is_blank(const std::string& value) {
    for (const char character : value) {
        if (character != ' ' && character != '\t' && character != '\r' && character != '\n') {
            return false;
        }
    }

    return true;
}

}  // namespace

PlanValidationResult PlaybackEngine::loadPlan(const std::string& planJson) {
    PlanValidationResult result;

    if (is_blank(planJson)) {
        result.errors.push_back(PlanValidationIssue{
            .code = "empty_plan",
            .message = "PlaybackEngine requires a non-empty placeholder plan.",
        });
        state_.hasLoadedPlan = false;
        state_.transport = TransportState::Stopped;
        state_.timelineSeconds = 0.0;
        return result;
    }

    result.ok = true;
    state_.hasLoadedPlan = true;
    state_.transport = TransportState::Stopped;
    state_.timelineSeconds = 0.0;
    return result;
}

void PlaybackEngine::play() noexcept {
    if (state_.hasLoadedPlan) {
        state_.transport = TransportState::Playing;
    }
}

void PlaybackEngine::pause() noexcept {
    if (state_.transport == TransportState::Playing) {
        state_.transport = TransportState::Paused;
    }
}

void PlaybackEngine::stop() noexcept {
    state_.transport = TransportState::Stopped;
    state_.timelineSeconds = 0.0;
}

bool PlaybackEngine::seek(domain::TimelineSeconds timelineSeconds) noexcept {
    if (!std::isfinite(timelineSeconds) || timelineSeconds < 0.0) {
        return false;
    }

    state_.timelineSeconds = timelineSeconds;
    return true;
}

PlaybackState PlaybackEngine::getState() const noexcept {
    return state_;
}

}  // namespace autodj::playback

