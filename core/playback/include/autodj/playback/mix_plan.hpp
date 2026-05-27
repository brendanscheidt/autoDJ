#pragma once

#include "autodj/domain/domain.hpp"

#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace autodj::playback {

struct PlanValidationIssue final {
    std::string code;
    std::string message;
};

struct PlanValidationResult final {
    bool ok{false};
    std::vector<PlanValidationIssue> errors;
    std::vector<PlanValidationIssue> warnings;
};

enum class TransitionTechnique {
    IntroOutroBlend,
    BuildToDropSwap,
    DropEndReverbExit,
    WashOut,
    DropDouble,
    LoopTighten,
    VocalOverInstrumental,
    EchoOut,
    HardCut,
};

enum class DeckCommandType {
    Load,
    Play,
    Stop,
    Seek,
    SetLoop,
    ClearLoop,
    Automate,
};

enum class AutomationControl {
    Volume,
    EqLow,
    EqMid,
    EqHigh,
    Filter,
    ReverbWet,
    ReverbTailGain,
    ReverbDecaySeconds,
    EchoWet,
    Tempo,
    Crossfader,
};

enum class KeyframeInterpolation {
    Hold,
    Linear,
    Smoothstep,
    Exponential,
};

struct StrategyProvenance final {
    std::string strategyId;
    std::string strategyVersion;
    std::string randomSeed;
};

struct TempoPlan final {
    std::optional<double> sourceBpm;
    std::optional<double> targetBpm;
    std::optional<double> tempoRatio;
    std::optional<bool> preservePitch;
    std::string backend;
    std::string backendVersion;
    std::string quality;
    std::string renderedSourceUri;
    std::string renderedContentHash;
    std::optional<double> targetBpmBias;
    std::optional<double> validatedBpm;
    std::string validationStatus;
    std::optional<bool> requiresRenderedBpmValidation;
    std::vector<std::string> warnings;
};

struct TrackAssetReference final {
    domain::TrackId trackId;
    std::string sourceUri;
    std::string formatHint;
    std::string contentHash;
    std::optional<domain::TrackSeconds> durationSeconds;
    std::optional<double> sourceBpm;
    std::optional<double> normalizedBpm;
};

struct TrackPlacement final {
    std::string placementId;
    domain::TrackId trackId;
    int deck{0};
    domain::TrackSeconds sourceStartSeconds{0.0};
    std::optional<domain::TrackSeconds> sourceEndSeconds;
    domain::TimelineSeconds timelineStartSeconds{0.0};
    std::optional<domain::TimelineSeconds> timelineEndSeconds;
    std::string role;
    std::optional<TempoPlan> tempoPlan;
};

struct TransitionAnchor final {
    domain::TrackId trackId;
    std::string sectionId;
    std::string cueId;
    std::optional<domain::TrackSeconds> sourceSeconds;
    std::optional<int> beatIndex;
    std::optional<int> measureIndex;
};

struct TransitionEdge final {
    std::string transitionId;
    std::string fromPlacementId;
    std::string toPlacementId;
    TransitionTechnique technique{TransitionTechnique::HardCut};
    std::string templateId;
    domain::TimelineSeconds timelineStartSeconds{0.0};
    domain::TimelineSeconds timelineEndSeconds{0.0};
    double score{0.0};
    std::vector<std::string> reasons;
    std::vector<std::string> riskFlags;
    std::optional<double> measureCountToTarget;
    std::optional<domain::TimelineSeconds> alignedDropTimelineSeconds;
    std::optional<domain::TimelineSeconds> handoffTimelineSeconds;
    std::map<std::string, TransitionAnchor> sourceAnchors;
    std::optional<TempoPlan> tempoPlan;
};

struct Keyframe final {
    domain::TimelineSeconds at{0.0};
    double value{0.0};
    KeyframeInterpolation interpolation{KeyframeInterpolation::Linear};
};

struct DeckCommand final {
    DeckCommandType type{DeckCommandType::Play};
    domain::TimelineSeconds at{0.0};
    std::optional<int> deck;
    domain::TrackId trackId;
    std::string stem;
    std::optional<domain::TrackSeconds> cueSeconds;
    std::optional<domain::TrackSeconds> toSeconds;
    std::optional<domain::TrackSeconds> startSeconds;
    std::optional<double> lengthBeats;
    std::optional<AutomationControl> control;
    std::vector<Keyframe> keyframes;
    bool postFader{false};
    std::map<std::string, std::string> effectParameters;
};

struct PlanAnnotation final {
    domain::TimelineSeconds at{0.0};
    std::string placementId;
    std::string transitionId;
    std::string message;
};

struct MixPlan final {
    std::string schemaVersion;
    domain::PlanId planId;
    std::string createdAtUtc;
    StrategyProvenance strategy;
    std::vector<TrackAssetReference> assets;
    std::vector<TrackPlacement> tracks;
    std::vector<TransitionEdge> transitions;
    std::vector<DeckCommand> commands;
    std::vector<PlanAnnotation> annotations;
};

struct MixPlanParseResult final {
    std::optional<MixPlan> plan;
    PlanValidationResult validation;
};

[[nodiscard]] MixPlanParseResult parseMixPlan(std::string_view json);

[[nodiscard]] std::string toString(TransitionTechnique technique);
[[nodiscard]] std::string toString(DeckCommandType type);
[[nodiscard]] std::string toString(AutomationControl control);

}  // namespace autodj::playback
