#pragma once

#include "autodj/domain/domain.hpp"
#include "autodj/playback/mix_plan.hpp"

#include <map>
#include <optional>
#include <string>
#include <vector>

namespace autodj::playback {

enum class TransportState {
    Stopped,
    Playing,
    Paused,
};

struct PlaybackState final {
    TransportState transport{TransportState::Stopped};
    domain::TimelineSeconds timelineSeconds{0.0};
    bool hasLoadedPlan{false};
};

struct RuntimeControlState final {
    double value{0.0};
    bool postFader{false};
    std::map<std::string, std::string> effectParameters;
};

struct RuntimeLoopState final {
    bool active{false};
    domain::TrackSeconds startSeconds{0.0};
    double lengthBeats{0.0};
};

struct RuntimeDeckState final {
    int deck{0};
    bool loaded{false};
    bool playing{false};
    domain::TrackId trackId;
    domain::TrackSeconds sourceSeconds{0.0};
    RuntimeLoopState loop;
    std::map<AutomationControl, RuntimeControlState> controls;
};

struct PlaybackExecutionState final {
    domain::TimelineSeconds timelineSeconds{0.0};
    std::map<int, RuntimeDeckState> decks;
    std::map<AutomationControl, RuntimeControlState> globalControls;
};

class PlaybackEngine final {
public:
    [[nodiscard]] PlanValidationResult loadPlan(const std::string& planJson);

    void play() noexcept;
    void pause() noexcept;
    void stop() noexcept;
    [[nodiscard]] bool seek(domain::TimelineSeconds timelineSeconds) noexcept;

    [[nodiscard]] PlaybackState getState() const noexcept;
    [[nodiscard]] PlaybackExecutionState getExecutionState() const;
    [[nodiscard]] PlaybackExecutionState evaluateAt(domain::TimelineSeconds timelineSeconds) const;

private:
    struct ScheduledCommand final {
        std::size_t commandIndex{0};
        int priority{0};
    };

    [[nodiscard]] static int commandPriority(DeckCommandType type) noexcept;
    void compileSchedule();

    PlaybackState state_{};
    std::optional<MixPlan> loadedPlan_;
    std::vector<ScheduledCommand> schedule_;
};

}  // namespace autodj::playback
