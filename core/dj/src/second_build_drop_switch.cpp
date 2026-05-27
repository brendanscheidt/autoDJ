#include "autodj/dj/second_build_drop_switch.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <optional>
#include <sstream>
#include <string>
#include <utility>

namespace autodj::dj {
namespace {

[[nodiscard]] DropSwitchTemplateIssue makeIssue(std::string code, std::string message) {
    return DropSwitchTemplateIssue{
        .code = std::move(code),
        .message = std::move(message),
    };
}

void reject(DropSwitchTemplateResult& result, std::string code, std::string message) {
    result.rejectionReasons.push_back(makeIssue(std::move(code), std::move(message)));
}

void addRiskFlag(DropSwitchTemplateResult& result, std::string flag) {
    if (std::find(result.riskFlags.begin(), result.riskFlags.end(), flag) == result.riskFlags.end()) {
        result.riskFlags.push_back(std::move(flag));
    }
}

[[nodiscard]] bool isFiniteNonNegative(const double value) {
    return std::isfinite(value) && value >= 0.0;
}

[[nodiscard]] bool hasLowConfidence(const std::optional<double> confidence, const double threshold) {
    return confidence.has_value() && confidence.value() < threshold;
}

[[nodiscard]] bool hasMediumConfidence(const std::optional<double> confidence,
                                       const double minimum,
                                       const double complexThreshold) {
    return confidence.has_value() && confidence.value() >= minimum && confidence.value() < complexThreshold;
}

void addSummaryRiskFlags(DropSwitchTemplateResult& result, const TrackAnalysisSummary& summary, const std::string& role) {
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

[[nodiscard]] std::optional<int> sectionStartBeat(const TrackAnalysisSummary& summary, const AnalyzedSection& section) {
    if (section.startBeatIndex.has_value()) {
        return section.startBeatIndex;
    }

    std::optional<int> candidate;
    double bestDistance = 0.0;
    for (const auto& beat : summary.beats) {
        const double distance = std::fabs(beat.timeSeconds - section.startSeconds);
        if (!candidate.has_value() || distance < bestDistance) {
            candidate = beat.index;
            bestDistance = distance;
        }
    }
    return candidate;
}

[[nodiscard]] std::optional<AnalyzedBeat> nearestBeatToSourceSeconds(const TrackAnalysisSummary& summary,
                                                                     const double sourceSeconds) {
    std::optional<AnalyzedBeat> candidate;
    double bestDistance = 0.0;
    for (const auto& beat : summary.beats) {
        const double distance = std::fabs(beat.timeSeconds - sourceSeconds);
        if (!candidate.has_value() || distance < bestDistance) {
            candidate = beat;
            bestDistance = distance;
        }
    }
    return candidate;
}

[[nodiscard]] std::optional<AnalyzedBeat> beatByIndex(const TrackAnalysisSummary& summary, const int beatIndex) {
    for (const auto& beat : summary.beats) {
        if (beat.index == beatIndex) {
            return beat;
        }
    }
    return std::nullopt;
}

[[nodiscard]] std::optional<int> measureIndexFromBeat(const std::optional<int> beatIndex) {
    if (!beatIndex.has_value()) {
        return std::nullopt;
    }
    return beatIndex.value() / TrackAnalysisSummary::beatsPerMeasure;
}

[[nodiscard]] playback::TransitionAnchor makeSectionAnchor(const TrackAnalysisSummary& summary,
                                                           const AnalyzedSection& section,
                                                           const AnalyzedBeat& beat) {
    const auto beatIndex = std::optional<int>{beat.index};
    return playback::TransitionAnchor{
        .trackId = summary.trackId,
        .sectionId = section.id,
        .cueId = {},
        .sourceSeconds = beat.timeSeconds,
        .beatIndex = beatIndex,
        .measureIndex = measureIndexFromBeat(beatIndex),
    };
}

[[nodiscard]] playback::TransitionAnchor makeBeatAnchor(const TrackAnalysisSummary& summary,
                                                        const AnalyzedBeat& beat) {
    const auto beatIndex = std::optional<int>{beat.index};
    return playback::TransitionAnchor{
        .trackId = summary.trackId,
        .sectionId = {},
        .cueId = {},
        .sourceSeconds = beat.timeSeconds,
        .beatIndex = beatIndex,
        .measureIndex = measureIndexFromBeat(beatIndex),
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
                                                      std::vector<playback::Keyframe> keyframes) {
    const double at = keyframes.empty() ? 0.0 : keyframes.front().at;
    return playback::DeckCommand{
        .type = playback::DeckCommandType::Automate,
        .at = at,
        .deck = deck,
        .control = control,
        .keyframes = std::move(keyframes),
    };
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

[[nodiscard]] std::string secondsMessage(const double value) {
    std::ostringstream output;
    output << value;
    return output.str();
}

[[nodiscard]] bool nearlyEqual(const double lhs, const double rhs) {
    return std::fabs(lhs - rhs) < 0.000001;
}

[[nodiscard]] playback::TempoPlan tempoPlan(const double sourceBpm,
                                            const double targetBpm,
                                            const double tempoRatio,
                                            const DropSwitchTemplateOptions& options) {
    return playback::TempoPlan{
        .sourceBpm = sourceBpm,
        .targetBpm = targetBpm,
        .tempoRatio = tempoRatio,
        .preservePitch = true,
        .backend = options.tempoBackend,
        .backendVersion = options.tempoBackendVersion,
        .quality = options.tempoQuality,
        .renderedSourceUri = {},
        .renderedContentHash = {},
        .targetBpmBias = 0.0,
        .validatedBpm = std::nullopt,
        .validationStatus = "pending",
        .requiresRenderedBpmValidation = options.requiresRenderedBpmValidation,
        .warnings = {
            "Rendered tempo-matched asset must be BPM/beat-spacing validated before long drop-switch overlap.",
        },
    };
}

}  // namespace

DropSwitchTemplateResult buildSecondBuildDropSwitchTemplate(const TrackAnalysisSummary& outgoing,
                                                            const TrackAnalysisSummary& incoming,
                                                            const DropSwitchTemplateOptions& options) {
    DropSwitchTemplateResult result;

    if (options.outgoingDeck < 1 || options.incomingDeck < 1 || options.outgoingDeck == options.incomingDeck) {
        reject(result, "invalid_deck_options", "Drop switch requires two distinct positive deck numbers");
        return result;
    }
    if (!isFiniteNonNegative(options.outgoingTimelineStartSeconds)
        || !isFiniteNonNegative(options.outgoingSourceStartSeconds) || options.incomingLoadLeadSeconds < 0.0
        || options.outgoingSilentMeasuresBeforeDrop < 0.0 || options.minimumSectionConfidence < 0.0
        || options.minimumSectionConfidence > 1.0 || options.complexTransitionConfidence < 0.0
        || options.complexTransitionConfidence > 1.0) {
        reject(result, "invalid_template_options", "Drop switch options include invalid timing or confidence values");
        return result;
    }

    if (outgoing.normalizedBpm <= 0.0 || !std::isfinite(outgoing.normalizedBpm)) {
        reject(result, "invalid_normalized_bpm", "Outgoing track normalized BPM must be positive and finite");
        return result;
    }
    if (incoming.normalizedBpm <= 0.0 || !std::isfinite(incoming.normalizedBpm)) {
        reject(result, "invalid_normalized_bpm", "Incoming track normalized BPM must be positive and finite");
        return result;
    }

    if (!nearlyEqual(outgoing.normalizedBpm, incoming.normalizedBpm) && !options.incomingTargetBpm.has_value()) {
        reject(result,
               "bpm_mismatch_for_drop_switch",
               "Second-build drop switch requires exact normalized BPM equality");
        return result;
    }

    const double targetBpm = options.incomingTargetBpm.value_or(incoming.normalizedBpm);
    if (targetBpm <= 0.0 || !std::isfinite(targetBpm)) {
        reject(result, "invalid_target_bpm", "Incoming target BPM must be positive and finite");
        return result;
    }
    if (!nearlyEqual(outgoing.normalizedBpm, targetBpm)) {
        reject(result,
               "outgoing_tempo_ramp_unsupported",
               "Drop switch template currently requires the target BPM to match the outgoing effective BPM");
        return result;
    }
    const double incomingTempoRatio = targetBpm / incoming.normalizedBpm;
    const bool usesIncomingTempoStretch = !nearlyEqual(incomingTempoRatio, 1.0);
    if (usesIncomingTempoStretch) {
        addRiskFlag(result, "incoming_tempo_stretch_requires_validation");
    }

    if (outgoing.builds.size() < 2 || outgoing.drops.size() < 2) {
        reject(result,
               "missing_outgoing_second_build_drop",
               "Outgoing track needs at least two ordered build/drop sections");
        return result;
    }
    if (incoming.drops.empty()) {
        reject(result, "missing_incoming_first_drop", "Incoming track needs a first drop section");
        return result;
    }

    const auto& fromBuild = outgoing.builds[1];
    const auto& fromDrop = outgoing.drops[1];
    const auto& toDrop = incoming.drops[0];

    if (fromBuild.startSeconds >= fromDrop.startSeconds) {
        reject(result, "invalid_build_drop_order", "Outgoing build 2 must start before outgoing drop 2");
        return result;
    }
    if (fromDrop.startSeconds <= options.outgoingSourceStartSeconds) {
        reject(result, "invalid_outgoing_source_window", "Outgoing drop target is before the outgoing source start");
        return result;
    }

    if (hasLowConfidence(fromBuild.confidence, options.minimumSectionConfidence)
        || hasLowConfidence(fromDrop.confidence, options.minimumSectionConfidence)
        || hasLowConfidence(toDrop.confidence, options.minimumSectionConfidence)) {
        reject(result,
               "low_section_confidence",
               "Required outgoing build/drop or incoming drop sections are below the confidence threshold");
        return result;
    }

    if (hasMediumConfidence(fromBuild.confidence, options.minimumSectionConfidence, options.complexTransitionConfidence)
        || hasMediumConfidence(fromDrop.confidence, options.minimumSectionConfidence, options.complexTransitionConfidence)
        || hasMediumConfidence(toDrop.confidence, options.minimumSectionConfidence, options.complexTransitionConfidence)) {
        addRiskFlag(result, "medium_section_confidence");
    }
    addSummaryRiskFlags(result, outgoing, "outgoing");
    addSummaryRiskFlags(result, incoming, "incoming");

    const auto fromBuildBeat = nearestBeatToSourceSeconds(outgoing, fromBuild.startSeconds);
    const auto fromDropBeat = nearestBeatToSourceSeconds(outgoing, fromDrop.startSeconds);
    const auto toDropBeat = nearestBeatToSourceSeconds(incoming, toDrop.startSeconds);
    if (!fromBuildBeat.has_value() || !fromDropBeat.has_value() || !toDropBeat.has_value()) {
        reject(result, "missing_beatgrid_anchor", "Drop switch requires beatgrid markers near semantic cue labels");
        return result;
    }

    const int buildLengthBeats = fromDropBeat->index - fromBuildBeat->index;
    const int outgoingSilentBeatsBeforeDrop =
        static_cast<int>(std::round(options.outgoingSilentMeasuresBeforeDrop * TrackAnalysisSummary::beatsPerMeasure));
    if (buildLengthBeats <= outgoingSilentBeatsBeforeDrop || outgoingSilentBeatsBeforeDrop < 0) {
        reject(result,
               "build_too_short_for_handoff",
               "Outgoing second build is too short to complete the handoff before the aligned drop");
        return result;
    }
    if (buildLengthBeats % TrackAnalysisSummary::beatsPerMeasure != 0) {
        addRiskFlag(result, "non_integer_measure_count_from_beatgrid");
    }

    const int incomingStartBeatIndex = toDropBeat->index - buildLengthBeats;
    const auto incomingStartBeat = beatByIndex(incoming, incomingStartBeatIndex);
    if (!incomingStartBeat.has_value()) {
        reject(result,
               "missing_incoming_predrop_beat",
               "Incoming track does not have enough beatgrid before drop 1 for the outgoing build length");
        return result;
    }

    const int outgoingCutBeatIndex = fromDropBeat->index - outgoingSilentBeatsBeforeDrop;
    const auto outgoingCutBeat = beatByIndex(outgoing, outgoingCutBeatIndex);
    if (!outgoingCutBeat.has_value()) {
        reject(result, "missing_outgoing_cut_beat", "Outgoing beatgrid is missing the pre-drop cut beat");
        return result;
    }

    const double measureCountToTarget =
        static_cast<double>(buildLengthBeats) / static_cast<double>(TrackAnalysisSummary::beatsPerMeasure);
    const double incomingSourceStart = incomingStartBeat->timeSeconds;
    const double outgoingBuildTimelineStart =
        options.outgoingTimelineStartSeconds + (fromBuildBeat->timeSeconds - options.outgoingSourceStartSeconds);
    const double alignedDropTimelineSeconds =
        options.outgoingTimelineStartSeconds + (fromDropBeat->timeSeconds - options.outgoingSourceStartSeconds);
    const double incomingTimelineStartSeconds =
        alignedDropTimelineSeconds - (toDropBeat->timeSeconds - incomingSourceStart) / incomingTempoRatio;
    const double lowHandoffTimelineSeconds =
        outgoingBuildTimelineStart + (alignedDropTimelineSeconds - outgoingBuildTimelineStart) / 2.0;
    const double lowHandoffCommandTimelineSeconds = std::max(incomingTimelineStartSeconds, lowHandoffTimelineSeconds);
    const double incomingFullVolumeTimelineSeconds = std::max(incomingTimelineStartSeconds, lowHandoffTimelineSeconds);
    const double outgoingCutTimelineSeconds =
        options.outgoingTimelineStartSeconds + (outgoingCutBeat->timeSeconds - options.outgoingSourceStartSeconds);
    const double incomingLoadAt = std::max(0.0, incomingTimelineStartSeconds - options.incomingLoadLeadSeconds);
    const double handoffTimelineSeconds = outgoingCutTimelineSeconds;

    if (!isFiniteNonNegative(outgoingBuildTimelineStart) || !isFiniteNonNegative(alignedDropTimelineSeconds)
        || !isFiniteNonNegative(incomingTimelineStartSeconds) || !isFiniteNonNegative(lowHandoffTimelineSeconds)
        || !isFiniteNonNegative(lowHandoffCommandTimelineSeconds) || !isFiniteNonNegative(incomingFullVolumeTimelineSeconds)
        || outgoingCutTimelineSeconds <= outgoingBuildTimelineStart
        || outgoingCutTimelineSeconds > alignedDropTimelineSeconds
        || incomingFullVolumeTimelineSeconds > outgoingCutTimelineSeconds
        || lowHandoffCommandTimelineSeconds > outgoingCutTimelineSeconds
        || alignedDropTimelineSeconds <= outgoingBuildTimelineStart) {
        reject(result, "invalid_drop_switch_timing", "Calculated drop switch timing is not usable");
        return result;
    }

    const auto outgoingSuffix = trackIdSuffix(outgoing);
    const auto incomingSuffix = trackIdSuffix(incoming);
    const std::string outgoingPlacementId = "place-" + outgoingSuffix + "-outgoing-drop-switch";
    const std::string incomingPlacementId = "place-" + incomingSuffix + "-incoming-drop-switch";
    const std::string transitionId = "transition-second-build-drop-switch-" + outgoingSuffix + "-to-" + incomingSuffix;

    DropSwitchTemplatePlanFragment fragment;
    fragment.placements.push_back(playback::TrackPlacement{
        .placementId = outgoingPlacementId,
        .trackId = outgoing.trackId,
        .deck = options.outgoingDeck,
        .sourceStartSeconds = options.outgoingSourceStartSeconds,
        .sourceEndSeconds = outgoingCutBeat->timeSeconds,
        .timelineStartSeconds = options.outgoingTimelineStartSeconds,
        .timelineEndSeconds = outgoingCutTimelineSeconds,
        .role = "primary",
    });
    fragment.placements.push_back(playback::TrackPlacement{
        .placementId = incomingPlacementId,
        .trackId = incoming.trackId,
        .deck = options.incomingDeck,
        .sourceStartSeconds = incomingSourceStart,
        .sourceEndSeconds = incoming.durationSeconds,
        .timelineStartSeconds = incomingTimelineStartSeconds,
        .timelineEndSeconds = incoming.durationSeconds.has_value()
                                  ? std::optional<double>{incomingTimelineStartSeconds
                                                          + (incoming.durationSeconds.value() - incomingSourceStart)
                                                                / incomingTempoRatio}
                                  : std::nullopt,
        .role = "incoming",
        .tempoPlan = usesIncomingTempoStretch
                         ? std::optional<playback::TempoPlan>{
                             tempoPlan(incoming.normalizedBpm, targetBpm, incomingTempoRatio, options)}
                         : std::nullopt,
    });

    fragment.transition = playback::TransitionEdge{
        .transitionId = transitionId,
        .fromPlacementId = outgoingPlacementId,
        .toPlacementId = incomingPlacementId,
        .technique = playback::TransitionTechnique::BuildToDropSwap,
        .templateId = "second_build_drop_switch_v1",
        .timelineStartSeconds = outgoingBuildTimelineStart,
        .timelineEndSeconds = alignedDropTimelineSeconds,
        .score = result.riskFlags.empty() ? 0.9 : 0.78,
        .reasons = {
            "Outgoing track has build 2 into drop 2",
            "Incoming track has drop 1 and enough pre-drop beatgrid for the outgoing build length",
            usesIncomingTempoStretch ? "Incoming track is tempo-matched with preserve-pitch stretch"
                                      : "Normalized BPM values are exactly equal",
            "Semantic cue timestamps are translated to nearest beatgrid beats before timing is calculated",
            "Incoming deck fades from silence to full volume by the build midpoint",
            "Low EQ is handed from outgoing to incoming instantly at the build midpoint",
            "Outgoing deck is hard-cut one measure before the aligned drops",
        },
        .riskFlags = result.riskFlags,
        .measureCountToTarget = measureCountToTarget,
        .alignedDropTimelineSeconds = alignedDropTimelineSeconds,
        .handoffTimelineSeconds = handoffTimelineSeconds,
        .sourceAnchors = {
            {"fromBuildStart", makeSectionAnchor(outgoing, fromBuild, fromBuildBeat.value())},
            {"fromDropStart", makeSectionAnchor(outgoing, fromDrop, fromDropBeat.value())},
            {"toBuildStart", makeBeatAnchor(incoming, incomingStartBeat.value())},
            {"toDropStart", makeSectionAnchor(incoming, toDrop, toDropBeat.value())},
        },
        .tempoPlan = usesIncomingTempoStretch
                         ? std::optional<playback::TempoPlan>{
                             tempoPlan(incoming.normalizedBpm, targetBpm, incomingTempoRatio, options)}
                         : std::nullopt,
    };

    fragment.commands.push_back(loadCommand(options.outgoingTimelineStartSeconds,
                                            options.outgoingDeck,
                                            outgoing,
                                            options.outgoingSourceStartSeconds));
    fragment.commands.push_back(playCommand(options.outgoingTimelineStartSeconds, options.outgoingDeck));
    fragment.commands.push_back(loadCommand(incomingLoadAt, options.incomingDeck, incoming, incomingSourceStart));
    fragment.commands.push_back(playCommand(incomingTimelineStartSeconds, options.incomingDeck));
    if (usesIncomingTempoStretch) {
        auto command = automationCommand(options.incomingDeck,
                                         playback::AutomationControl::Tempo,
                                         {
                                             keyframe(incomingTimelineStartSeconds,
                                                      incomingTempoRatio,
                                                      playback::KeyframeInterpolation::Hold),
                                         });
        command.effectParameters.emplace("sourceBpm", secondsMessage(incoming.normalizedBpm));
        command.effectParameters.emplace("targetBpm", secondsMessage(targetBpm));
        command.effectParameters.emplace("preservePitch", "true");
        command.effectParameters.emplace("backend", options.tempoBackend);
        command.effectParameters.emplace("quality", options.tempoQuality);
        command.effectParameters.emplace(
            "requiresRenderedBpmValidation",
            options.requiresRenderedBpmValidation ? "true" : "false");
        fragment.commands.push_back(std::move(command));
    }
    fragment.commands.push_back(automationCommand(options.incomingDeck,
                                                  playback::AutomationControl::Volume,
                                                  {
                                                      keyframe(incomingTimelineStartSeconds,
                                                               0.0,
                                                               playback::KeyframeInterpolation::Hold),
                                                      keyframe(incomingFullVolumeTimelineSeconds,
                                                               1.0,
                                                               playback::KeyframeInterpolation::Smoothstep),
                                                  }));
    fragment.commands.push_back(automationCommand(options.incomingDeck,
                                                  playback::AutomationControl::EqLow,
                                                  {
                                                      keyframe(incomingTimelineStartSeconds,
                                                               0.0,
                                                               playback::KeyframeInterpolation::Hold),
                                                      keyframe(lowHandoffCommandTimelineSeconds,
                                                               1.0,
                                                               playback::KeyframeInterpolation::Hold),
                                                  }));
    fragment.commands.push_back(automationCommand(options.outgoingDeck,
                                                  playback::AutomationControl::EqLow,
                                                  {
                                                      keyframe(lowHandoffCommandTimelineSeconds,
                                                               0.0,
                                                               playback::KeyframeInterpolation::Hold),
                                                  }));
    fragment.commands.push_back(automationCommand(options.outgoingDeck,
                                                  playback::AutomationControl::Volume,
                                                  {
                                                      keyframe(outgoingBuildTimelineStart,
                                                               1.0,
                                                               playback::KeyframeInterpolation::Hold),
                                                      keyframe(outgoingCutTimelineSeconds,
                                                               0.0,
                                                               playback::KeyframeInterpolation::Hold),
                                                  }));
    fragment.commands.push_back(stopCommand(outgoingCutTimelineSeconds, options.outgoingDeck));
    sortCommands(fragment.commands);

    fragment.annotations.push_back(playback::PlanAnnotation{
        .at = outgoingBuildTimelineStart,
        .placementId = outgoingPlacementId,
        .transitionId = transitionId,
        .message = "Second-build drop switch begins: " + secondsMessage(measureCountToTarget)
                   + " measures until the aligned drop",
    });
    fragment.annotations.push_back(playback::PlanAnnotation{
        .at = lowHandoffCommandTimelineSeconds,
        .placementId = incomingPlacementId,
        .transitionId = transitionId,
        .message = "Build midpoint: incoming deck reaches full volume and takes over low EQ",
    });
    fragment.annotations.push_back(playback::PlanAnnotation{
        .at = outgoingCutTimelineSeconds,
        .placementId = outgoingPlacementId,
        .transitionId = transitionId,
        .message = "Outgoing deck is hard-cut one measure before the aligned drops",
    });
    fragment.annotations.push_back(playback::PlanAnnotation{
        .at = alignedDropTimelineSeconds,
        .placementId = incomingPlacementId,
        .transitionId = transitionId,
        .message = "Incoming track owns the aligned drop; outgoing deck is stopped",
    });

    result.fragment = std::move(fragment);
    return result;
}

}  // namespace autodj::dj
