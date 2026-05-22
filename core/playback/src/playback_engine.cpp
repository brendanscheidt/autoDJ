#include "autodj/playback/playback_engine.hpp"

#include <algorithm>
#include <cmath>

namespace autodj::playback {
namespace {

[[nodiscard]] double clamp01(const double value) noexcept {
    if (value < 0.0) {
        return 0.0;
    }
    if (value > 1.0) {
        return 1.0;
    }
    return value;
}

[[nodiscard]] double smoothstep(const double value) noexcept {
    const auto t = clamp01(value);
    return t * t * (3.0 - 2.0 * t);
}

[[nodiscard]] double interpolate(const Keyframe& from, const Keyframe& to, const domain::TimelineSeconds at) noexcept {
    if (to.at <= from.at) {
        return to.value;
    }

    const auto normalized = clamp01((at - from.at) / (to.at - from.at));
    switch (to.interpolation) {
        case KeyframeInterpolation::Hold:
            return from.value;
        case KeyframeInterpolation::Linear:
            return from.value + ((to.value - from.value) * normalized);
        case KeyframeInterpolation::Smoothstep:
            return from.value + ((to.value - from.value) * smoothstep(normalized));
        case KeyframeInterpolation::Exponential: {
            const auto curved = normalized * normalized;
            return from.value + ((to.value - from.value) * curved);
        }
    }
    return from.value;
}

[[nodiscard]] RuntimeControlState evaluateAutomation(const DeckCommand& command,
                                                     const domain::TimelineSeconds timelineSeconds) {
    RuntimeControlState control;
    control.postFader = command.postFader;
    control.effectParameters = command.effectParameters;

    if (command.keyframes.empty()) {
        return control;
    }
    if (timelineSeconds <= command.keyframes.front().at) {
        control.value = command.keyframes.front().value;
        return control;
    }
    if (timelineSeconds >= command.keyframes.back().at) {
        control.value = command.keyframes.back().value;
        return control;
    }

    for (std::size_t index = 1; index < command.keyframes.size(); ++index) {
        const auto& next = command.keyframes[index];
        if (timelineSeconds <= next.at) {
            control.value = interpolate(command.keyframes[index - 1], next, timelineSeconds);
            return control;
        }
    }

    control.value = command.keyframes.back().value;
    return control;
}

void advancePlayingDecks(std::map<int, RuntimeDeckState>& decks, const domain::TimelineSeconds deltaSeconds) {
    if (deltaSeconds <= 0.0) {
        return;
    }
    for (auto& [_, deck] : decks) {
        if (deck.loaded && deck.playing) {
            deck.sourceSeconds += deltaSeconds;
        }
    }
}

}  // namespace

PlanValidationResult PlaybackEngine::loadPlan(const std::string& planJson) {
    const auto parseResult = parseMixPlan(planJson);

    if (!parseResult.validation.ok || !parseResult.plan.has_value()) {
        state_.hasLoadedPlan = false;
        state_.transport = TransportState::Stopped;
        state_.timelineSeconds = 0.0;
        loadedPlan_.reset();
        schedule_.clear();
        return parseResult.validation;
    }

    loadedPlan_ = parseResult.plan;
    compileSchedule();
    state_.hasLoadedPlan = true;
    state_.transport = TransportState::Stopped;
    state_.timelineSeconds = 0.0;
    return parseResult.validation;
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

PlaybackExecutionState PlaybackEngine::getExecutionState() const {
    return evaluateAt(state_.timelineSeconds);
}

PlaybackExecutionState PlaybackEngine::evaluateAt(domain::TimelineSeconds timelineSeconds) const {
    PlaybackExecutionState execution;
    if (!loadedPlan_.has_value() || !std::isfinite(timelineSeconds) || timelineSeconds < 0.0) {
        return execution;
    }

    execution.timelineSeconds = timelineSeconds;

    domain::TimelineSeconds cursor{0.0};
    for (const auto& scheduled : schedule_) {
        const auto& command = loadedPlan_->commands[scheduled.commandIndex];
        if (command.at > timelineSeconds) {
            break;
        }

        advancePlayingDecks(execution.decks, command.at - cursor);
        cursor = command.at;

        switch (command.type) {
            case DeckCommandType::Stop: {
                if (command.deck.has_value()) {
                    execution.decks.erase(command.deck.value());
                }
                break;
            }
            case DeckCommandType::ClearLoop: {
                if (command.deck.has_value()) {
                    auto& deck = execution.decks[command.deck.value()];
                    deck.deck = command.deck.value();
                    deck.loop = RuntimeLoopState{};
                }
                break;
            }
            case DeckCommandType::Load: {
                if (command.deck.has_value()) {
                    RuntimeDeckState deck;
                    deck.deck = command.deck.value();
                    deck.loaded = true;
                    deck.playing = false;
                    deck.trackId = command.trackId;
                    deck.sourceSeconds = command.cueSeconds.value_or(0.0);
                    execution.decks[deck.deck] = std::move(deck);
                }
                break;
            }
            case DeckCommandType::Seek: {
                if (command.deck.has_value()) {
                    auto& deck = execution.decks[command.deck.value()];
                    deck.deck = command.deck.value();
                    if (deck.loaded) {
                        deck.sourceSeconds = command.toSeconds.value_or(0.0);
                    }
                }
                break;
            }
            case DeckCommandType::SetLoop: {
                if (command.deck.has_value()) {
                    auto& deck = execution.decks[command.deck.value()];
                    deck.deck = command.deck.value();
                    deck.loop = RuntimeLoopState{
                        .active = true,
                        .startSeconds = command.startSeconds.value_or(0.0),
                        .lengthBeats = command.lengthBeats.value_or(0.0),
                    };
                }
                break;
            }
            case DeckCommandType::Automate:
                break;
            case DeckCommandType::Play: {
                if (command.deck.has_value()) {
                    auto& deck = execution.decks[command.deck.value()];
                    deck.deck = command.deck.value();
                    if (deck.loaded) {
                        deck.playing = true;
                    }
                }
                break;
            }
        }
    }

    advancePlayingDecks(execution.decks, timelineSeconds - cursor);

    for (const auto& command : loadedPlan_->commands) {
        if (command.type != DeckCommandType::Automate || !command.control.has_value() || command.keyframes.empty()) {
            continue;
        }
        if (timelineSeconds < command.keyframes.front().at) {
            continue;
        }

        const auto value = evaluateAutomation(command, timelineSeconds);
        if (command.deck.has_value()) {
            auto& deck = execution.decks[command.deck.value()];
            deck.deck = command.deck.value();
            deck.controls[command.control.value()] = value;
        } else {
            execution.globalControls[command.control.value()] = value;
        }
    }

    return execution;
}

int PlaybackEngine::commandPriority(const DeckCommandType type) noexcept {
    switch (type) {
        case DeckCommandType::Stop:
        case DeckCommandType::ClearLoop:
            return 0;
        case DeckCommandType::Load:
            return 1;
        case DeckCommandType::Seek:
            return 2;
        case DeckCommandType::Automate:
        case DeckCommandType::SetLoop:
            return 3;
        case DeckCommandType::Play:
            return 4;
    }
    return 10;
}

void PlaybackEngine::compileSchedule() {
    schedule_.clear();
    if (!loadedPlan_.has_value()) {
        return;
    }

    schedule_.reserve(loadedPlan_->commands.size());
    for (std::size_t index = 0; index < loadedPlan_->commands.size(); ++index) {
        schedule_.push_back(ScheduledCommand{
            .commandIndex = index,
            .priority = commandPriority(loadedPlan_->commands[index].type),
        });
    }

    std::stable_sort(schedule_.begin(), schedule_.end(), [this](const ScheduledCommand& left,
                                                                const ScheduledCommand& right) {
        const auto& leftCommand = loadedPlan_->commands[left.commandIndex];
        const auto& rightCommand = loadedPlan_->commands[right.commandIndex];
        if (leftCommand.at != rightCommand.at) {
            return leftCommand.at < rightCommand.at;
        }
        if (left.priority != right.priority) {
            return left.priority < right.priority;
        }
        return left.commandIndex < right.commandIndex;
    });
}

}  // namespace autodj::playback
