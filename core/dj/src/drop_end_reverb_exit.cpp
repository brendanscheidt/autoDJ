#include "autodj/dj/drop_end_reverb_exit.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <optional>
#include <sstream>
#include <string>
#include <utility>

namespace autodj::dj {
namespace {

[[nodiscard]] DropEndReverbExitIssue makeIssue(std::string code, std::string message) {
    return DropEndReverbExitIssue{
        .code = std::move(code),
        .message = std::move(message),
    };
}

void reject(DropEndReverbExitResult& result, std::string code, std::string message) {
    result.rejectionReasons.push_back(makeIssue(std::move(code), std::move(message)));
}

void addRiskFlag(DropEndReverbExitResult& result, std::string flag) {
    if (std::find(result.riskFlags.begin(), result.riskFlags.end(), flag) == result.riskFlags.end()) {
        result.riskFlags.push_back(std::move(flag));
    }
}

[[nodiscard]] bool isFiniteNonNegative(const double value) {
    return std::isfinite(value) && value >= 0.0;
}

void addSummaryRiskFlags(DropEndReverbExitResult& result,
                         const TrackAnalysisSummary& summary,
                         const std::string& role) {
    for (const auto& riskFlag : summary.riskFlags) {
        addRiskFlag(result, role + "_" + riskFlag);
    }
    for (const auto& warning : summary.qualityWarnings) {
        if (!warning.empty()) {
            addRiskFlag(result, role + "_analysis_warning");
            break;
        }
    }
}

[[nodiscard]] bool hasUsableSecondBuildDropPair(const TrackAnalysisSummary& summary, const double confidenceThreshold) {
    if (summary.builds.size() < 2 || summary.drops.size() < 2) {
        return false;
    }
    const auto& build = summary.builds[1];
    const auto& drop = summary.drops[1];
    if (build.startSeconds >= drop.startSeconds) {
        return false;
    }
    if (build.confidence.has_value() && build.confidence.value() < confidenceThreshold) {
        return false;
    }
    if (drop.confidence.has_value() && drop.confidence.value() < confidenceThreshold) {
        return false;
    }
    return true;
}

[[nodiscard]] std::optional<int> nearestBeatIndex(const TrackAnalysisSummary& summary, const double timeSeconds) {
    std::optional<int> candidate;
    double bestDistance = 0.0;
    for (const auto& beat : summary.beats) {
        const double distance = std::fabs(beat.timeSeconds - timeSeconds);
        if (!candidate.has_value() || distance < bestDistance) {
            candidate = beat.index;
            bestDistance = distance;
        }
    }
    return candidate;
}

[[nodiscard]] std::optional<int> measureIndexFromBeat(const std::optional<int> beatIndex) {
    if (!beatIndex.has_value()) {
        return std::nullopt;
    }
    return beatIndex.value() / TrackAnalysisSummary::beatsPerMeasure;
}

[[nodiscard]] std::optional<AnalyzedBeat> firstBeat(const TrackAnalysisSummary& summary) {
    if (summary.beats.empty()) {
        return std::nullopt;
    }
    return summary.beats.front();
}

[[nodiscard]] playback::TransitionAnchor makeDropEndAnchor(const TrackAnalysisSummary& summary,
                                                           const AnalyzedSection& section) {
    const auto beatIndex = section.endBeatIndex.has_value() ? section.endBeatIndex : nearestBeatIndex(summary, section.endSeconds);
    return playback::TransitionAnchor{
        .trackId = summary.trackId,
        .sectionId = section.id,
        .cueId = {},
        .sourceSeconds = section.endSeconds,
        .beatIndex = beatIndex,
        .measureIndex = measureIndexFromBeat(beatIndex),
    };
}

[[nodiscard]] playback::TransitionAnchor makeFirstBeatAnchor(const TrackAnalysisSummary& summary,
                                                             const AnalyzedBeat& beat) {
    return playback::TransitionAnchor{
        .trackId = summary.trackId,
        .sectionId = {},
        .cueId = {},
        .sourceSeconds = beat.timeSeconds,
        .beatIndex = beat.index,
        .measureIndex = measureIndexFromBeat(beat.index),
    };
}

[[nodiscard]] playback::DeckCommand loadCommand(const double at,
                                                const int deck,
                                                const TrackAnalysisSummary& track,
                                                const double cueSeconds) {
    return playback::DeckCommand{
        .type = playback::DeckCommandType::Load,
        .at = at,
        .deck = deck,
        .trackId = track.trackId,
        .stem = "full",
        .cueSeconds = cueSeconds,
    };
}

[[nodiscard]] playback::DeckCommand playCommand(const double at, const int deck) {
    return playback::DeckCommand{
        .type = playback::DeckCommandType::Play,
        .at = at,
        .deck = deck,
    };
}

[[nodiscard]] playback::DeckCommand stopCommand(const double at, const int deck) {
    return playback::DeckCommand{
        .type = playback::DeckCommandType::Stop,
        .at = at,
        .deck = deck,
    };
}

[[nodiscard]] playback::Keyframe keyframe(const double at,
                                          const double value,
                                          const playback::KeyframeInterpolation interpolation) {
    return playback::Keyframe{
        .at = at,
        .value = value,
        .interpolation = interpolation,
    };
}

[[nodiscard]] playback::DeckCommand automationCommand(std::optional<int> deck,
                                                      const playback::AutomationControl control,
                                                      std::vector<playback::Keyframe> keyframes,
                                                      const bool postFader = false,
                                                      const double reverbDecaySeconds = 0.0) {
    playback::DeckCommand command{
        .type = playback::DeckCommandType::Automate,
        .at = keyframes.empty() ? 0.0 : keyframes.front().at,
        .deck = deck,
        .control = control,
        .keyframes = std::move(keyframes),
        .postFader = postFader,
    };
    if (postFader) {
        command.effectParameters.emplace("style", "cdj");
        std::ostringstream decayValue;
        decayValue << reverbDecaySeconds;
        command.effectParameters.emplace("reverbDecaySeconds", decayValue.str());
    }
    return command;
}

[[nodiscard]] int commandPriority(const playback::DeckCommand& command) {
    switch (command.type) {
        case playback::DeckCommandType::Stop:
        case playback::DeckCommandType::ClearLoop:
            return 0;
        case playback::DeckCommandType::Load:
            return 1;
        case playback::DeckCommandType::Seek:
            return 2;
        case playback::DeckCommandType::Automate:
        case playback::DeckCommandType::SetLoop:
            return 3;
        case playback::DeckCommandType::Play:
            return 4;
    }
    return 5;
}

void sortCommands(std::vector<playback::DeckCommand>& commands) {
    std::stable_sort(commands.begin(), commands.end(), [](const playback::DeckCommand& lhs,
                                                          const playback::DeckCommand& rhs) {
        if (lhs.at == rhs.at) {
            return commandPriority(lhs) < commandPriority(rhs);
        }
        return lhs.at < rhs.at;
    });
}

[[nodiscard]] std::string trackIdSuffix(const TrackAnalysisSummary& summary) {
    std::string suffix;
    suffix.reserve(summary.trackId.value.size());
    for (const auto character : summary.trackId.value) {
        if ((character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z')
            || (character >= '0' && character <= '9')) {
            suffix.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(character))));
        } else {
            suffix.push_back('-');
        }
    }
    if (suffix.empty()) {
        return "track";
    }
    return suffix;
}

[[nodiscard]] std::string measuresMessage(const double value) {
    std::ostringstream output;
    output << value;
    return output.str();
}

}  // namespace

DropEndReverbExitResult buildDropEndReverbExitTemplate(const TrackAnalysisSummary& outgoing,
                                                       const TrackAnalysisSummary& incoming,
                                                       const DropEndReverbExitOptions& options) {
    DropEndReverbExitResult result;

    if (options.outgoingDeck < 1 || options.incomingDeck < 1 || options.outgoingDeck == options.incomingDeck) {
        reject(result, "invalid_deck_options", "Drop-end reverb exit requires two distinct positive deck numbers");
        return result;
    }
    if (!isFiniteNonNegative(options.outgoingTimelineStartSeconds)
        || !isFiniteNonNegative(options.outgoingSourceStartSeconds) || options.incomingLoadLeadSeconds < 0.0
        || options.reverbRampMeasures <= 0.0 || options.finalDryFadeMeasures <= 0.0
        || options.incomingLowRestoreMeasures <= 0.0 || options.midReverbWet < 0.0 || options.midReverbWet > 1.0
        || options.reverbDecaySeconds <= 0.0 || options.reverbTailSeconds <= 0.0
        || options.minimumSectionConfidence < 0.0
        || options.minimumSectionConfidence > 1.0) {
        reject(result, "invalid_template_options", "Drop-end reverb exit options include invalid values");
        return result;
    }
    if (outgoing.normalizedBpm <= 0.0 || incoming.normalizedBpm <= 0.0 || !std::isfinite(outgoing.normalizedBpm)
        || !std::isfinite(incoming.normalizedBpm)) {
        reject(result, "invalid_normalized_bpm", "Both tracks need positive finite normalized BPM values");
        return result;
    }
    if (!options.allowSecondBuildDropPair && hasUsableSecondBuildDropPair(outgoing, options.minimumSectionConfidence)) {
        reject(result,
               "outgoing_second_build_drop_available",
               "Drop-end reverb exit is reserved for tracks without a usable second build/drop pair");
        return result;
    }
    if (outgoing.drops.empty()) {
        reject(result, "missing_outgoing_drop_end", "Outgoing track needs a usable drop end");
        return result;
    }
    const auto firstIncomingBeat = firstBeat(incoming);
    if (!firstIncomingBeat.has_value()) {
        reject(result, "missing_incoming_first_beat", "Incoming track needs a beatgrid beat to start from");
        return result;
    }

    const auto& drop = outgoing.drops.front();
    if (drop.endSeconds <= drop.startSeconds || drop.endSeconds <= options.outgoingSourceStartSeconds) {
        reject(result, "missing_outgoing_drop_end", "Outgoing drop end must be after the drop start and source start");
        return result;
    }
    if (drop.confidence.has_value() && drop.confidence.value() < options.minimumSectionConfidence) {
        reject(result, "low_drop_confidence", "Outgoing drop confidence is below the threshold for reverb exit");
        return result;
    }
    if (drop.confidence.has_value() && drop.confidence.value() < 0.85) {
        addRiskFlag(result, "medium_drop_confidence");
    }
    addSummaryRiskFlags(result, outgoing, "outgoing");
    addSummaryRiskFlags(result, incoming, "incoming");

    const double outgoingMeasureSeconds = 60.0 / outgoing.normalizedBpm * TrackAnalysisSummary::beatsPerMeasure;
    const double dropStartTimelineSeconds =
        options.outgoingTimelineStartSeconds + (drop.startSeconds - options.outgoingSourceStartSeconds);
    const double dropEndTimelineSeconds =
        options.outgoingTimelineStartSeconds + (drop.endSeconds - options.outgoingSourceStartSeconds);
    const double desiredRampStart = dropEndTimelineSeconds - options.reverbRampMeasures * outgoingMeasureSeconds;
    const double rampStartTimelineSeconds = std::max(dropStartTimelineSeconds, desiredRampStart);
    const double actualRampMeasures = (dropEndTimelineSeconds - rampStartTimelineSeconds) / outgoingMeasureSeconds;
    if (actualRampMeasures + 0.000001 < options.reverbRampMeasures) {
        addRiskFlag(result, "reverb_exit_ramp_clamped");
    }
    const double reverbMidpointTimelineSeconds =
        rampStartTimelineSeconds + (dropEndTimelineSeconds - rampStartTimelineSeconds) / 2.0;
    const double tailEndTimelineSeconds = dropEndTimelineSeconds + options.reverbTailSeconds;
    const double incomingSourceStartSeconds = firstIncomingBeat->timeSeconds;
    const double incomingLoadAt = std::max(0.0, dropEndTimelineSeconds - options.incomingLoadLeadSeconds);

    if (!isFiniteNonNegative(dropStartTimelineSeconds) || !isFiniteNonNegative(dropEndTimelineSeconds)
        || !isFiniteNonNegative(rampStartTimelineSeconds) || tailEndTimelineSeconds <= dropEndTimelineSeconds
        || reverbMidpointTimelineSeconds > dropEndTimelineSeconds) {
        reject(result, "invalid_reverb_exit_timing", "Calculated reverb-exit timing is not usable");
        return result;
    }

    const auto outgoingSuffix = trackIdSuffix(outgoing);
    const auto incomingSuffix = trackIdSuffix(incoming);
    const std::string outgoingPlacementId = "place-" + outgoingSuffix + "-outgoing-reverb-exit";
    const std::string incomingPlacementId = "place-" + incomingSuffix + "-incoming-reverb-exit";
    const std::string transitionId = "transition-drop-end-reverb-exit-" + outgoingSuffix + "-to-" + incomingSuffix;

    DropEndReverbExitPlanFragment fragment;
    fragment.placements.push_back(playback::TrackPlacement{
        .placementId = outgoingPlacementId,
        .trackId = outgoing.trackId,
        .deck = options.outgoingDeck,
        .sourceStartSeconds = options.outgoingSourceStartSeconds,
        .sourceEndSeconds = drop.endSeconds,
        .timelineStartSeconds = options.outgoingTimelineStartSeconds,
        .timelineEndSeconds = tailEndTimelineSeconds,
        .role = "primary",
    });
    fragment.placements.push_back(playback::TrackPlacement{
        .placementId = incomingPlacementId,
        .trackId = incoming.trackId,
        .deck = options.incomingDeck,
        .sourceStartSeconds = incomingSourceStartSeconds,
        .sourceEndSeconds = incoming.durationSeconds,
        .timelineStartSeconds = dropEndTimelineSeconds,
        .timelineEndSeconds = incoming.durationSeconds.has_value()
                                  ? std::optional<double>{dropEndTimelineSeconds
                                                          + (incoming.durationSeconds.value() - incomingSourceStartSeconds)}
                                  : std::nullopt,
        .role = "incoming",
    });

    fragment.transition = playback::TransitionEdge{
        .transitionId = transitionId,
        .fromPlacementId = outgoingPlacementId,
        .toPlacementId = incomingPlacementId,
        .technique = playback::TransitionTechnique::DropEndReverbExit,
        .templateId = "drop_end_reverb_exit_v1",
        .timelineStartSeconds = rampStartTimelineSeconds,
        .timelineEndSeconds = tailEndTimelineSeconds,
        .score = result.riskFlags.empty() ? 0.78 : 0.68,
        .reasons = {
            "Outgoing track has a usable drop end",
            "Incoming track starts from its first beatgrid beat",
            "Outgoing mid/high reverb ramps only over the final two measures of the drop",
            "Incoming track starts full volume and full-band exactly at the outgoing drop end",
            "Outgoing dry signal hard-cuts at the drop end while a ten-second post-fader reverb tail remains",
        },
        .riskFlags = result.riskFlags,
        .measureCountToTarget = actualRampMeasures,
        .handoffTimelineSeconds = dropEndTimelineSeconds,
        .sourceAnchors = {
            {"fromDropEnd", makeDropEndAnchor(outgoing, drop)},
            {"toFirstBeat", makeFirstBeatAnchor(incoming, firstIncomingBeat.value())},
        },
    };

    fragment.commands.push_back(loadCommand(options.outgoingTimelineStartSeconds,
                                            options.outgoingDeck,
                                            outgoing,
                                            options.outgoingSourceStartSeconds));
    fragment.commands.push_back(playCommand(options.outgoingTimelineStartSeconds, options.outgoingDeck));
    fragment.commands.push_back(automationCommand(options.outgoingDeck,
                                                  playback::AutomationControl::ReverbWet,
                                                  {
                                                      keyframe(rampStartTimelineSeconds,
                                                               0.0,
                                                               playback::KeyframeInterpolation::Hold),
                                                      keyframe(reverbMidpointTimelineSeconds,
                                                               options.midReverbWet,
                                                               playback::KeyframeInterpolation::Linear),
                                                      keyframe(dropEndTimelineSeconds,
                                                               1.0,
                                                               playback::KeyframeInterpolation::Linear),
                                                  },
                                                  true,
                                                  options.reverbDecaySeconds));
    fragment.commands.push_back(automationCommand(options.outgoingDeck,
                                                  playback::AutomationControl::Volume,
                                                  {
                                                      keyframe(dropEndTimelineSeconds,
                                                               0.0,
                                                               playback::KeyframeInterpolation::Hold),
                                                  }));
    fragment.commands.push_back(automationCommand(options.outgoingDeck,
                                                  playback::AutomationControl::ReverbTailGain,
                                                  {
                                                      keyframe(dropEndTimelineSeconds,
                                                               1.0,
                                                               playback::KeyframeInterpolation::Hold),
                                                      keyframe(tailEndTimelineSeconds,
                                                               0.0,
                                                               playback::KeyframeInterpolation::Smoothstep),
                                                  },
                                                  true,
                                                  options.reverbDecaySeconds));
    fragment.commands.push_back(loadCommand(incomingLoadAt, options.incomingDeck, incoming, incomingSourceStartSeconds));
    fragment.commands.push_back(playCommand(dropEndTimelineSeconds, options.incomingDeck));
    fragment.commands.push_back(stopCommand(tailEndTimelineSeconds, options.outgoingDeck));
    sortCommands(fragment.commands);

    fragment.annotations.push_back(playback::PlanAnnotation{
        .at = rampStartTimelineSeconds,
        .placementId = outgoingPlacementId,
        .transitionId = transitionId,
        .message = "Drop-end reverb exit begins with " + measuresMessage(actualRampMeasures)
                   + " measures of ramp before the outgoing drop end",
    });
    fragment.annotations.push_back(playback::PlanAnnotation{
        .at = dropEndTimelineSeconds,
        .placementId = incomingPlacementId,
        .transitionId = transitionId,
        .message = "Incoming track starts full-band while the outgoing reverb tail decays for ten seconds",
    });

    result.fragment = std::move(fragment);
    return result;
}

}  // namespace autodj::dj
