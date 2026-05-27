#pragma once

#include "autodj/dj/analyzed_track_summary.hpp"
#include "autodj/playback/mix_plan.hpp"

#include <optional>
#include <string>
#include <vector>

namespace autodj::dj {

struct DropEndReverbExitIssue final {
    std::string code;
    std::string message;
};

struct DropEndReverbExitOptions final {
    int outgoingDeck{1};
    int incomingDeck{2};
    double outgoingTimelineStartSeconds{0.0};
    double outgoingSourceStartSeconds{0.0};
    double incomingLoadLeadSeconds{4.0};
    double reverbRampMeasures{1.0};
    double finalDryFadeMeasures{1.0};
    double incomingLowRestoreMeasures{4.0};
    double midReverbWet{0.6};
    double reverbDecaySeconds{24.0};
    double reverbTailSeconds{24.0};
    bool includeWashSweep{true};
    int washSweepDeck{3};
    std::string washSweepTrackId{"washout-sweep-fx"};
    std::string washSweepSourceUri{"fixtures/audio/fx/washout-sweep.wav"};
    std::string washSweepFormatHint{"wav"};
    double washSweepDurationSeconds{7.68};
    double washSweepPeakOffsetSeconds{3.8400907029478457};
    double washSweepGain{2.50};
    double minimumSectionConfidence{0.65};
    bool allowSecondBuildDropPair{false};
};

struct DropEndReverbExitPlanFragment final {
    std::vector<playback::TrackAssetReference> assets;
    std::vector<playback::TrackPlacement> placements;
    playback::TransitionEdge transition;
    std::vector<playback::DeckCommand> commands;
    std::vector<playback::PlanAnnotation> annotations;
};

struct DropEndReverbExitResult final {
    std::optional<DropEndReverbExitPlanFragment> fragment;
    std::vector<DropEndReverbExitIssue> rejectionReasons;
    std::vector<std::string> riskFlags;

    [[nodiscard]] bool ok() const noexcept { return fragment.has_value() && rejectionReasons.empty(); }
};

[[nodiscard]] DropEndReverbExitResult buildDropEndReverbExitTemplate(
    const TrackAnalysisSummary& outgoing,
    const TrackAnalysisSummary& incoming,
    const DropEndReverbExitOptions& options = {});

}  // namespace autodj::dj
