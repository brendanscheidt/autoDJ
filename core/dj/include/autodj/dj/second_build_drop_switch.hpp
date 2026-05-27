#pragma once

#include "autodj/dj/analyzed_track_summary.hpp"
#include "autodj/playback/mix_plan.hpp"

#include <optional>
#include <string>
#include <vector>

namespace autodj::dj {

struct DropSwitchTemplateIssue final {
    std::string code;
    std::string message;
};

struct DropSwitchTemplateOptions final {
    int outgoingDeck{1};
    int incomingDeck{2};
    double outgoingTimelineStartSeconds{0.0};
    double outgoingSourceStartSeconds{0.0};
    double incomingLoadLeadSeconds{4.0};
    double outgoingSilentMeasuresBeforeDrop{1.0};
    double minimumSectionConfidence{0.65};
    double complexTransitionConfidence{0.85};
    std::optional<double> incomingTargetBpm;
    std::string tempoBackend{"soundstretch"};
    std::string tempoBackendVersion{"2.3.2"};
    std::string tempoQuality{"standard"};
    bool requiresRenderedBpmValidation{true};
};

struct DropSwitchTemplatePlanFragment final {
    std::vector<playback::TrackAssetReference> assets;
    std::vector<playback::TrackPlacement> placements;
    playback::TransitionEdge transition;
    std::vector<playback::DeckCommand> commands;
    std::vector<playback::PlanAnnotation> annotations;
};

struct DropSwitchTemplateResult final {
    std::optional<DropSwitchTemplatePlanFragment> fragment;
    std::vector<DropSwitchTemplateIssue> rejectionReasons;
    std::vector<std::string> riskFlags;

    [[nodiscard]] bool ok() const noexcept { return fragment.has_value() && rejectionReasons.empty(); }
};

[[nodiscard]] DropSwitchTemplateResult buildSecondBuildDropSwitchTemplate(
    const TrackAnalysisSummary& outgoing,
    const TrackAnalysisSummary& incoming,
    const DropSwitchTemplateOptions& options = {});

}  // namespace autodj::dj
