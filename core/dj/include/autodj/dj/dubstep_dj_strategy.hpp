#pragma once

#include "autodj/dj/analyzed_track_summary.hpp"
#include "autodj/dj/dj_strategy.hpp"
#include "autodj/playback/mix_plan.hpp"

#include <optional>
#include <string>
#include <vector>

namespace autodj::dj {

struct DubstepPocPlanIssue final {
    std::string code;
    std::string message;
    domain::TrackId trackId;
};

struct DubstepPocPlanOptions final {
    domain::PlanId planId{"plan-dubstep-poc"};
    std::string createdAtUtc{"2026-01-01T00:00:00Z"};
    std::string randomSeed{"deterministic-poc"};
    bool allowTempoStretch{true};
    double maxTempoAdjustmentBpmPerDeck{10.0};
    std::string tempoBackend{"soundstretch"};
    std::string tempoBackendVersion{"2.3.2"};
    std::string tempoQuality{"standard"};
    bool requiresRenderedBpmValidation{true};
};

struct DubstepPocPlanResult final {
    std::optional<playback::MixPlan> plan;
    std::vector<DubstepPocPlanIssue> errors;
    std::vector<DubstepPocPlanIssue> candidateRejections;
    std::vector<std::string> debugNotes;
    std::optional<domain::TrackId> selectedIncomingTrackId;
    std::optional<domain::TrackId> nextOutgoingTrackId;
    std::string selectedTemplateId;
    int nextOutgoingDeck{0};

    [[nodiscard]] bool ok() const noexcept { return plan.has_value() && errors.empty(); }
};

class DubstepDJStrategy final : public IDJStrategy {
public:
    [[nodiscard]] std::string strategyId() const override;
    [[nodiscard]] std::vector<std::string> supportedGenres() const override;
    [[nodiscard]] std::string generatePlanPlaceholder() const override;

    [[nodiscard]] DubstepPocPlanResult generatePocPlan(
        const TrackAnalysisSummary& outgoing,
        const std::vector<TrackAnalysisSummary>& incomingCandidates,
        const DubstepPocPlanOptions& options = {}) const;
};

[[nodiscard]] std::string serializeMixPlanJson(const playback::MixPlan& plan);

}  // namespace autodj::dj
