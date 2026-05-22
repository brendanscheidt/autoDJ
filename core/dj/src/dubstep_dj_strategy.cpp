#include "autodj/dj/dubstep_dj_strategy.hpp"

#include "autodj/dj/drop_end_reverb_exit.hpp"
#include "autodj/dj/second_build_drop_switch.hpp"

#include <algorithm>
#include <cctype>
#include <iomanip>
#include <map>
#include <optional>
#include <sstream>
#include <string>
#include <utility>

namespace autodj::dj {
namespace {

constexpr auto kStrategyVersion = "0.3.0";

void addError(DubstepPocPlanResult& result,
              std::string code,
              std::string message,
              domain::TrackId trackId = {}) {
    result.errors.push_back(DubstepPocPlanIssue{
        .code = std::move(code),
        .message = std::move(message),
        .trackId = std::move(trackId),
    });
}

void addCandidateRejection(DubstepPocPlanResult& result,
                           std::string code,
                           std::string message,
                           domain::TrackId trackId) {
    result.candidateRejections.push_back(DubstepPocPlanIssue{
        .code = std::move(code),
        .message = std::move(message),
        .trackId = std::move(trackId),
    });
}

[[nodiscard]] std::string lowerCopy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](const unsigned char character) {
        return static_cast<char>(std::tolower(character));
    });
    return value;
}

[[nodiscard]] std::string inferFormatHint(const std::string& sourceUri) {
    const auto dot = sourceUri.find_last_of('.');
    if (dot == std::string::npos || dot + 1 >= sourceUri.size()) {
        return "unknown";
    }

    const auto extension = lowerCopy(sourceUri.substr(dot + 1));
    if (extension == "wav" || extension == "mp3" || extension == "flac" || extension == "aiff") {
        return extension;
    }
    return "unknown";
}

[[nodiscard]] playback::TrackAssetReference makeAsset(const TrackAnalysisSummary& summary) {
    return playback::TrackAssetReference{
        .trackId = summary.trackId,
        .sourceUri = summary.sourceUri.empty() ? "fixture://" + summary.trackId.value : summary.sourceUri,
        .formatHint = inferFormatHint(summary.sourceUri),
        .contentHash = {},
        .durationSeconds = summary.durationSeconds,
    };
}

template <typename Fragment>
[[nodiscard]] playback::MixPlan makePlanFromFragment(const Fragment& fragment,
                                                     const TrackAnalysisSummary& outgoing,
                                                     const TrackAnalysisSummary& incoming,
                                                     const DubstepPocPlanOptions& options) {
    playback::MixPlan plan;
    plan.schemaVersion = "1.0.0";
    plan.planId = options.planId;
    plan.createdAtUtc = options.createdAtUtc;
    plan.strategy = playback::StrategyProvenance{
        .strategyId = "dubstep-dj",
        .strategyVersion = kStrategyVersion,
        .randomSeed = options.randomSeed,
    };
    plan.assets = {
        makeAsset(outgoing),
        makeAsset(incoming),
    };
    plan.tracks = fragment.placements;
    plan.transitions = {fragment.transition};
    plan.commands = fragment.commands;
    plan.annotations = fragment.annotations;
    plan.annotations.push_back(playback::PlanAnnotation{
        .at = fragment.transition.timelineStartSeconds,
        .placementId = fragment.transition.fromPlacementId,
        .transitionId = fragment.transition.transitionId,
        .message = "DubstepDJStrategy selected " + fragment.transition.templateId,
    });
    return plan;
}

void chooseDropSwitch(DubstepPocPlanResult& result,
                      const TrackAnalysisSummary& outgoing,
                      const TrackAnalysisSummary& incoming,
                      const DubstepPocPlanOptions& options,
                      const DropSwitchTemplatePlanFragment& fragment) {
    result.plan = makePlanFromFragment(fragment, outgoing, incoming, options);
    result.selectedIncomingTrackId = incoming.trackId;
    result.nextOutgoingTrackId = incoming.trackId;
    result.selectedTemplateId = fragment.transition.templateId;
    result.nextOutgoingDeck = 2;
    result.debugNotes.push_back("Selected second-build drop switch for exact-normalized-BPM incoming candidate "
                                + incoming.trackId.value);
}

void chooseReverbExit(DubstepPocPlanResult& result,
                      const TrackAnalysisSummary& outgoing,
                      const TrackAnalysisSummary& incoming,
                      const DubstepPocPlanOptions& options,
                      const DropEndReverbExitPlanFragment& fragment) {
    result.plan = makePlanFromFragment(fragment, outgoing, incoming, options);
    result.selectedIncomingTrackId = incoming.trackId;
    result.nextOutgoingTrackId = incoming.trackId;
    result.selectedTemplateId = fragment.transition.templateId;
    result.nextOutgoingDeck = 2;
    result.debugNotes.push_back("Selected drop-end reverb exit fallback for incoming candidate "
                                + incoming.trackId.value);
}

[[nodiscard]] bool sameTrack(const TrackAnalysisSummary& lhs, const TrackAnalysisSummary& rhs) {
    return !lhs.trackId.empty() && lhs.trackId == rhs.trackId;
}

[[nodiscard]] std::string jsonString(const std::string& value) {
    std::ostringstream output;
    output << '"';
    for (const auto character : value) {
        switch (character) {
            case '"':
                output << "\\\"";
                break;
            case '\\':
                output << "\\\\";
                break;
            case '\b':
                output << "\\b";
                break;
            case '\f':
                output << "\\f";
                break;
            case '\n':
                output << "\\n";
                break;
            case '\r':
                output << "\\r";
                break;
            case '\t':
                output << "\\t";
                break;
            default:
                if (static_cast<unsigned char>(character) < 0x20) {
                    output << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                           << static_cast<int>(static_cast<unsigned char>(character)) << std::dec;
                } else {
                    output << character;
                }
                break;
        }
    }
    output << '"';
    return output.str();
}

[[nodiscard]] std::string jsonNumber(const double value) {
    std::ostringstream output;
    output << std::setprecision(15) << value;
    return output.str();
}

[[nodiscard]] std::string interpolationToString(const playback::KeyframeInterpolation interpolation) {
    switch (interpolation) {
        case playback::KeyframeInterpolation::Hold:
            return "hold";
        case playback::KeyframeInterpolation::Linear:
            return "linear";
        case playback::KeyframeInterpolation::Smoothstep:
            return "smoothstep";
        case playback::KeyframeInterpolation::Exponential:
            return "exponential";
    }
    return "linear";
}

void writeStringArray(std::ostringstream& output, const std::vector<std::string>& values, const int indent) {
    output << "[";
    if (!values.empty()) {
        output << "\n";
        for (std::size_t index = 0; index < values.size(); ++index) {
            output << std::string(indent, ' ') << jsonString(values[index]);
            if (index + 1 < values.size()) {
                output << ",";
            }
            output << "\n";
        }
        output << std::string(indent - 2, ' ');
    }
    output << "]";
}

void writeAssets(std::ostringstream& output, const std::vector<playback::TrackAssetReference>& assets) {
    output << "  \"assets\": [\n";
    for (std::size_t index = 0; index < assets.size(); ++index) {
        const auto& asset = assets[index];
        output << "    {\n";
        output << "      \"trackId\": " << jsonString(asset.trackId.value) << ",\n";
        output << "      \"sourceUri\": " << jsonString(asset.sourceUri) << ",\n";
        output << "      \"formatHint\": " << jsonString(asset.formatHint) << ",\n";
        output << "      \"contentHash\": " << jsonString(asset.contentHash);
        if (asset.durationSeconds.has_value()) {
            output << ",\n      \"durationSeconds\": " << jsonNumber(asset.durationSeconds.value()) << "\n";
        } else {
            output << "\n";
        }
        output << "    }";
        if (index + 1 < assets.size()) {
            output << ",";
        }
        output << "\n";
    }
    output << "  ],\n";
}

void writePlacements(std::ostringstream& output, const std::vector<playback::TrackPlacement>& placements) {
    output << "  \"tracks\": [\n";
    for (std::size_t index = 0; index < placements.size(); ++index) {
        const auto& placement = placements[index];
        output << "    {\n";
        output << "      \"placementId\": " << jsonString(placement.placementId) << ",\n";
        output << "      \"trackId\": " << jsonString(placement.trackId.value) << ",\n";
        output << "      \"deck\": " << placement.deck << ",\n";
        output << "      \"sourceStartSeconds\": " << jsonNumber(placement.sourceStartSeconds);
        if (placement.sourceEndSeconds.has_value()) {
            output << ",\n      \"sourceEndSeconds\": " << jsonNumber(placement.sourceEndSeconds.value());
        }
        output << ",\n      \"timelineStartSeconds\": " << jsonNumber(placement.timelineStartSeconds);
        if (placement.timelineEndSeconds.has_value()) {
            output << ",\n      \"timelineEndSeconds\": " << jsonNumber(placement.timelineEndSeconds.value());
        }
        output << ",\n      \"role\": " << jsonString(placement.role) << "\n";
        output << "    }";
        if (index + 1 < placements.size()) {
            output << ",";
        }
        output << "\n";
    }
    output << "  ],\n";
}

void writeAnchor(std::ostringstream& output, const playback::TransitionAnchor& anchor, const int indent) {
    const auto spaces = std::string(indent, ' ');
    output << "{\n";
    output << spaces << "  \"trackId\": " << jsonString(anchor.trackId.value);
    if (!anchor.sectionId.empty()) {
        output << ",\n" << spaces << "  \"sectionId\": " << jsonString(anchor.sectionId);
    }
    if (!anchor.cueId.empty()) {
        output << ",\n" << spaces << "  \"cueId\": " << jsonString(anchor.cueId);
    }
    if (anchor.sourceSeconds.has_value()) {
        output << ",\n" << spaces << "  \"sourceSeconds\": " << jsonNumber(anchor.sourceSeconds.value());
    }
    if (anchor.beatIndex.has_value()) {
        output << ",\n" << spaces << "  \"beatIndex\": " << anchor.beatIndex.value();
    }
    if (anchor.measureIndex.has_value()) {
        output << ",\n" << spaces << "  \"measureIndex\": " << anchor.measureIndex.value();
    }
    output << "\n" << spaces << "}";
}

void writeTransitions(std::ostringstream& output, const std::vector<playback::TransitionEdge>& transitions) {
    output << "  \"transitions\": [\n";
    for (std::size_t index = 0; index < transitions.size(); ++index) {
        const auto& transition = transitions[index];
        output << "    {\n";
        output << "      \"transitionId\": " << jsonString(transition.transitionId) << ",\n";
        output << "      \"fromPlacementId\": " << jsonString(transition.fromPlacementId) << ",\n";
        output << "      \"toPlacementId\": " << jsonString(transition.toPlacementId) << ",\n";
        output << "      \"technique\": " << jsonString(playback::toString(transition.technique)) << ",\n";
        output << "      \"templateId\": " << jsonString(transition.templateId) << ",\n";
        output << "      \"timelineStartSeconds\": " << jsonNumber(transition.timelineStartSeconds) << ",\n";
        output << "      \"timelineEndSeconds\": " << jsonNumber(transition.timelineEndSeconds) << ",\n";
        if (transition.alignedDropTimelineSeconds.has_value()) {
            output << "      \"alignedDropTimelineSeconds\": "
                   << jsonNumber(transition.alignedDropTimelineSeconds.value()) << ",\n";
        }
        if (transition.handoffTimelineSeconds.has_value()) {
            output << "      \"handoffTimelineSeconds\": " << jsonNumber(transition.handoffTimelineSeconds.value())
                   << ",\n";
        }
        if (transition.measureCountToTarget.has_value()) {
            output << "      \"measureCountToTarget\": " << jsonNumber(transition.measureCountToTarget.value())
                   << ",\n";
        }
        output << "      \"score\": " << jsonNumber(transition.score) << ",\n";
        output << "      \"reasons\": ";
        writeStringArray(output, transition.reasons, 8);
        output << ",\n      \"riskFlags\": ";
        writeStringArray(output, transition.riskFlags, 8);
        output << ",\n      \"sourceAnchors\": {\n";
        auto anchorIndex = std::size_t{0};
        for (const auto& [name, anchor] : transition.sourceAnchors) {
            output << "        " << jsonString(name) << ": ";
            writeAnchor(output, anchor, 8);
            if (++anchorIndex < transition.sourceAnchors.size()) {
                output << ",";
            }
            output << "\n";
        }
        output << "      }\n";
        output << "    }";
        if (index + 1 < transitions.size()) {
            output << ",";
        }
        output << "\n";
    }
    output << "  ],\n";
}

void writeKeyframes(std::ostringstream& output, const std::vector<playback::Keyframe>& keyframes) {
    output << "[\n";
    for (std::size_t index = 0; index < keyframes.size(); ++index) {
        const auto& keyframe = keyframes[index];
        output << "        {\n";
        output << "          \"at\": " << jsonNumber(keyframe.at) << ",\n";
        output << "          \"value\": " << jsonNumber(keyframe.value) << ",\n";
        output << "          \"interpolation\": " << jsonString(interpolationToString(keyframe.interpolation)) << "\n";
        output << "        }";
        if (index + 1 < keyframes.size()) {
            output << ",";
        }
        output << "\n";
    }
    output << "      ]";
}

void writeCommands(std::ostringstream& output, const std::vector<playback::DeckCommand>& commands) {
    output << "  \"commands\": [\n";
    for (std::size_t index = 0; index < commands.size(); ++index) {
        const auto& command = commands[index];
        output << "    {\n";
        output << "      \"type\": " << jsonString(playback::toString(command.type)) << ",\n";
        output << "      \"at\": " << jsonNumber(command.at);
        if (command.deck.has_value()) {
            output << ",\n      \"deck\": " << command.deck.value();
        }
        if (!command.trackId.empty()) {
            output << ",\n      \"trackId\": " << jsonString(command.trackId.value);
        }
        if (!command.stem.empty()) {
            output << ",\n      \"stem\": " << jsonString(command.stem);
        }
        if (command.cueSeconds.has_value()) {
            output << ",\n      \"cueSeconds\": " << jsonNumber(command.cueSeconds.value());
        }
        if (command.toSeconds.has_value()) {
            output << ",\n      \"toSeconds\": " << jsonNumber(command.toSeconds.value());
        }
        if (command.startSeconds.has_value()) {
            output << ",\n      \"startSeconds\": " << jsonNumber(command.startSeconds.value());
        }
        if (command.lengthBeats.has_value()) {
            output << ",\n      \"lengthBeats\": " << jsonNumber(command.lengthBeats.value());
        }
        if (command.control.has_value()) {
            output << ",\n      \"control\": " << jsonString(playback::toString(command.control.value()));
        }
        if (command.postFader) {
            output << ",\n      \"postFader\": true";
        }
        if (!command.effectParameters.empty()) {
            output << ",\n      \"effectParameters\": {\n";
            auto effectIndex = std::size_t{0};
            for (const auto& [name, value] : command.effectParameters) {
                output << "        " << jsonString(name) << ": " << jsonString(value);
                if (++effectIndex < command.effectParameters.size()) {
                    output << ",";
                }
                output << "\n";
            }
            output << "      }";
        }
        if (!command.keyframes.empty()) {
            output << ",\n      \"keyframes\": ";
            writeKeyframes(output, command.keyframes);
        }
        output << "\n    }";
        if (index + 1 < commands.size()) {
            output << ",";
        }
        output << "\n";
    }
    output << "  ],\n";
}

void writeAnnotations(std::ostringstream& output, const std::vector<playback::PlanAnnotation>& annotations) {
    output << "  \"annotations\": [\n";
    for (std::size_t index = 0; index < annotations.size(); ++index) {
        const auto& annotation = annotations[index];
        output << "    {\n";
        output << "      \"at\": " << jsonNumber(annotation.at);
        if (!annotation.placementId.empty()) {
            output << ",\n      \"placementId\": " << jsonString(annotation.placementId);
        }
        if (!annotation.transitionId.empty()) {
            output << ",\n      \"transitionId\": " << jsonString(annotation.transitionId);
        }
        output << ",\n      \"message\": " << jsonString(annotation.message) << "\n";
        output << "    }";
        if (index + 1 < annotations.size()) {
            output << ",";
        }
        output << "\n";
    }
    output << "  ]\n";
}

}  // namespace

std::string DubstepDJStrategy::strategyId() const {
    return "dubstep-dj";
}

std::vector<std::string> DubstepDJStrategy::supportedGenres() const {
    return {"dubstep"};
}

std::string DubstepDJStrategy::generatePlanPlaceholder() const {
    return R"json({
  "schemaVersion": "autodj.mix-plan.v1",
  "planId": "plan-placeholder-dubstep",
  "strategy": {
    "strategyId": "dubstep-dj",
    "strategyVersion": "0.1.0"
  },
  "tracks": [],
  "transitions": [],
  "commands": [],
  "annotations": [
    {
      "type": "placeholder",
      "message": "DubstepDJStrategy emits an empty MixPlan placeholder in the foundation spec."
    }
  ]
})json";
}

DubstepPocPlanResult DubstepDJStrategy::generatePocPlan(
    const TrackAnalysisSummary& outgoing,
    const std::vector<TrackAnalysisSummary>& incomingCandidates,
    const DubstepPocPlanOptions& options) const {
    DubstepPocPlanResult result;

    if (outgoing.trackId.empty()) {
        addError(result, "missing_outgoing_track_id", "Outgoing track requires a trackId");
        return result;
    }
    if (incomingCandidates.empty()) {
        addError(result, "no_incoming_candidates", "Planner needs at least one incoming candidate");
        return result;
    }

    for (const auto& incoming : incomingCandidates) {
        if (incoming.trackId.empty()) {
            addCandidateRejection(result,
                                  "missing_incoming_track_id",
                                  "Incoming candidate is missing a trackId",
                                  incoming.trackId);
            continue;
        }
        if (sameTrack(outgoing, incoming)) {
            addCandidateRejection(result,
                                  "same_track_candidate",
                                  "Planner will not transition a track into itself",
                                  incoming.trackId);
            continue;
        }
        if (outgoing.normalizedBpm != incoming.normalizedBpm) {
            addCandidateRejection(result,
                                  "bpm_mismatch_for_drop_switch",
                                  "Second-build drop switch requires exact normalized BPM equality",
                                  incoming.trackId);
            continue;
        }

        const auto candidate = buildSecondBuildDropSwitchTemplate(outgoing, incoming);
        if (candidate.ok()) {
            chooseDropSwitch(result, outgoing, incoming, options, candidate.fragment.value());
            return result;
        }

        for (const auto& rejection : candidate.rejectionReasons) {
            addCandidateRejection(result, rejection.code, rejection.message, incoming.trackId);
        }
    }

    result.debugNotes.push_back(
        "No exact-normalized-BPM second-build drop switch candidate was selected; trying drop-end reverb exit");
    for (const auto& incoming : incomingCandidates) {
        if (incoming.trackId.empty() || sameTrack(outgoing, incoming)) {
            continue;
        }

        DropEndReverbExitOptions reverbOptions;
        reverbOptions.allowSecondBuildDropPair = true;
        const auto candidate = buildDropEndReverbExitTemplate(outgoing, incoming, reverbOptions);
        if (candidate.ok()) {
            chooseReverbExit(result, outgoing, incoming, options, candidate.fragment.value());
            return result;
        }

        for (const auto& rejection : candidate.rejectionReasons) {
            addCandidateRejection(result, rejection.code, rejection.message, incoming.trackId);
        }
    }

    addError(result,
             "no_valid_transition_template",
             "No candidate could satisfy the second-build drop switch or drop-end reverb exit templates");
    return result;
}

std::string serializeMixPlanJson(const playback::MixPlan& plan) {
    std::ostringstream output;
    output << "{\n";
    output << "  \"schemaVersion\": " << jsonString(plan.schemaVersion) << ",\n";
    output << "  \"planId\": " << jsonString(plan.planId.value) << ",\n";
    output << "  \"createdAtUtc\": " << jsonString(plan.createdAtUtc) << ",\n";
    output << "  \"strategy\": {\n";
    output << "    \"strategyId\": " << jsonString(plan.strategy.strategyId) << ",\n";
    output << "    \"strategyVersion\": " << jsonString(plan.strategy.strategyVersion);
    if (!plan.strategy.randomSeed.empty()) {
        output << ",\n    \"randomSeed\": " << jsonString(plan.strategy.randomSeed) << "\n";
    } else {
        output << "\n";
    }
    output << "  },\n";
    writeAssets(output, plan.assets);
    writePlacements(output, plan.tracks);
    writeTransitions(output, plan.transitions);
    writeCommands(output, plan.commands);
    writeAnnotations(output, plan.annotations);
    output << "}\n";
    return output.str();
}

}  // namespace autodj::dj
