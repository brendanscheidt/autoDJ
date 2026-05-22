#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <iomanip>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace autodj::desktop {

enum class AuthoringDeck {
    A,
    B,
};

struct AuthoringKeyframe final {
    AuthoringDeck deck{AuthoringDeck::A};
    std::string control{"volume"};
    double sourceSeconds{0.0};
    double value{0.0};
    std::string interpolation{"linear"};
};

struct AutomationLane final {
    AuthoringDeck deck{AuthoringDeck::A};
    std::string control{"volume"};
    std::vector<AuthoringKeyframe> keyframes;
};

struct AuthoringDeckState final {
    AuthoringDeck deck{AuthoringDeck::A};
    std::string trackId;
    std::string title;
    std::string audioPath;
    std::string analyzedTrackPath;
    std::string debugWaveformPath;
    double normalizedBpm{0.0};
    double durationSeconds{0.0};
    double centerSeconds{0.0};
    double previewStartDelaySeconds{0.0};
    double zoomSeconds{16.0};
    std::vector<double> beats;
};

struct AuthoringAnchor final {
    std::string name;
    AuthoringDeck deck{AuthoringDeck::A};
    double sourceSeconds{0.0};
    std::string semanticRef;
};

struct AuthoringSession final {
    std::string sessionId{"transition-authoring-session"};
    std::string transitionFamily{"drop_switch"};
    std::string notes;
    AuthoringDeckState deckA;
    AuthoringDeckState deckB{.deck = AuthoringDeck::B};
    std::vector<AuthoringAnchor> anchors;
    std::vector<AutomationLane> lanes;
};

[[nodiscard]] inline char deckName(const AuthoringDeck deck) noexcept {
    return deck == AuthoringDeck::A ? 'a' : 'b';
}

[[nodiscard]] inline int deckNumber(const AuthoringDeck deck) noexcept {
    return deck == AuthoringDeck::A ? 1 : 2;
}

[[nodiscard]] inline std::string jsonEscape(std::string_view value) {
    std::string escaped;
    escaped.reserve(value.size());
    for (const auto character : value) {
        switch (character) {
            case '\\':
                escaped += "\\\\";
                break;
            case '"':
                escaped += "\\\"";
                break;
            case '\n':
                escaped += "\\n";
                break;
            case '\r':
                escaped += "\\r";
                break;
            case '\t':
                escaped += "\\t";
                break;
            default:
                escaped.push_back(character);
                break;
        }
    }
    return escaped;
}

[[nodiscard]] inline std::string quote(std::string_view value) {
    return "\"" + jsonEscape(value) + "\"";
}

[[nodiscard]] inline std::string number(const double value) {
    std::ostringstream output;
    output << std::fixed << std::setprecision(6) << value;
    auto text = output.str();
    while (text.size() > 1 && text.back() == '0') {
        text.pop_back();
    }
    if (!text.empty() && text.back() == '.') {
        text.pop_back();
    }
    return text.empty() ? "0" : text;
}

[[nodiscard]] inline std::optional<std::size_t> nearestBeatIndex(const std::vector<double>& beats,
                                                                 const double sourceSeconds) noexcept {
    if (beats.empty() || !std::isfinite(sourceSeconds)) {
        return std::nullopt;
    }
    const auto lower = std::lower_bound(beats.begin(), beats.end(), sourceSeconds);
    if (lower == beats.begin()) {
        return static_cast<std::size_t>(0);
    }
    if (lower == beats.end()) {
        return beats.size() - 1;
    }
    const auto rightIndex = static_cast<std::size_t>(std::distance(beats.begin(), lower));
    const auto leftIndex = rightIndex - 1;
    const auto leftDistance = std::abs(sourceSeconds - beats[leftIndex]);
    const auto rightDistance = std::abs(beats[rightIndex] - sourceSeconds);
    return rightDistance < leftDistance ? rightIndex : leftIndex;
}

[[nodiscard]] inline double snapToNearestBeat(const std::vector<double>& beats, const double sourceSeconds) noexcept {
    const auto index = nearestBeatIndex(beats, sourceSeconds);
    if (!index.has_value()) {
        return sourceSeconds;
    }
    return beats[index.value()];
}

[[nodiscard]] inline std::string beatIndexToBarBeat(const std::size_t beatIndex, const int beatsPerBar = 4) {
    const auto safeBeatsPerBar = beatsPerBar <= 0 ? 4 : beatsPerBar;
    const auto bar = beatIndex / static_cast<std::size_t>(safeBeatsPerBar) + 1;
    const auto beat = beatIndex % static_cast<std::size_t>(safeBeatsPerBar) + 1;
    return std::to_string(bar) + "." + std::to_string(beat);
}

[[nodiscard]] inline std::string barBeatLabelForTime(const std::vector<double>& beats,
                                                     const double sourceSeconds,
                                                     const int beatsPerBar = 4) {
    const auto index = nearestBeatIndex(beats, sourceSeconds);
    if (!index.has_value()) {
        return "--";
    }
    return beatIndexToBarBeat(index.value(), beatsPerBar);
}

inline void sortLane(AutomationLane& lane) {
    std::stable_sort(lane.keyframes.begin(), lane.keyframes.end(), [](const auto& left, const auto& right) {
        return left.sourceSeconds < right.sourceSeconds;
    });
}

[[nodiscard]] inline bool isEventControl(std::string_view control) noexcept {
    return control == "play" || control == "stop";
}

[[nodiscard]] inline double beatDurationSeconds(const AuthoringDeckState& deck) noexcept {
    if (deck.beats.size() >= 2) {
        double total = 0.0;
        std::size_t count = 0;
        for (std::size_t index = 1; index < deck.beats.size(); ++index) {
            const auto delta = deck.beats[index] - deck.beats[index - 1];
            if (delta > 0.0 && std::isfinite(delta)) {
                total += delta;
                ++count;
            }
        }
        if (count > 0) {
            return total / static_cast<double>(count);
        }
    }
    return deck.normalizedBpm > 0.0 ? 60.0 / deck.normalizedBpm : 60.0 / 140.0;
}

[[nodiscard]] inline const AuthoringDeckState& deckStateFor(const AuthoringSession& session, const AuthoringDeck deck) {
    return deck == AuthoringDeck::A ? session.deckA : session.deckB;
}

[[nodiscard]] inline std::string writeAuthoringSessionJson(const AuthoringSession& session) {
    std::ostringstream output;
    output << "{\n";
    output << "  \"schemaVersion\": \"1.0.0\",\n";
    output << "  \"sessionId\": " << quote(session.sessionId) << ",\n";
    output << "  \"transitionFamily\": " << quote(session.transitionFamily) << ",\n";
    output << "  \"notes\": " << quote(session.notes) << ",\n";
    output << "  \"decks\": [\n";
    const auto writeDeck = [&](const AuthoringDeckState& deck, const bool last) {
        output << "    {\n";
        output << "      \"deck\": " << quote(std::string(1, deckName(deck.deck))) << ",\n";
        output << "      \"trackId\": " << quote(deck.trackId) << ",\n";
        output << "      \"audioPath\": " << quote(deck.audioPath) << ",\n";
        output << "      \"analyzedTrackPath\": " << quote(deck.analyzedTrackPath) << ",\n";
        output << "      \"debugWaveformPath\": " << quote(deck.debugWaveformPath) << ",\n";
        output << "      \"centerSeconds\": " << number(deck.centerSeconds) << ",\n";
        output << "      \"previewStartDelaySeconds\": " << number(deck.previewStartDelaySeconds) << ",\n";
        output << "      \"zoomSeconds\": " << number(deck.zoomSeconds) << "\n";
        output << "    }" << (last ? "\n" : ",\n");
    };
    writeDeck(session.deckA, false);
    writeDeck(session.deckB, true);
    output << "  ],\n";
    output << "  \"anchors\": [\n";
    for (std::size_t index = 0; index < session.anchors.size(); ++index) {
        const auto& anchor = session.anchors[index];
        const auto& deck = deckStateFor(session, anchor.deck);
        output << "    {\"name\": " << quote(anchor.name)
               << ", \"deck\": " << quote(std::string(1, deckName(anchor.deck)))
               << ", \"sourceSeconds\": " << number(anchor.sourceSeconds)
               << ", \"barBeat\": " << quote(barBeatLabelForTime(deck.beats, anchor.sourceSeconds))
               << ", \"semanticRef\": " << quote(anchor.semanticRef)
               << "}" << (index + 1 == session.anchors.size() ? "\n" : ",\n");
    }
    output << "  ],\n";
    output << "  \"lanes\": [\n";
    for (std::size_t laneIndex = 0; laneIndex < session.lanes.size(); ++laneIndex) {
        const auto& lane = session.lanes[laneIndex];
        output << "    {\"deck\": " << quote(std::string(1, deckName(lane.deck)))
               << ", \"control\": " << quote(lane.control) << ", \"keyframes\": [";
        for (std::size_t frameIndex = 0; frameIndex < lane.keyframes.size(); ++frameIndex) {
            const auto& keyframe = lane.keyframes[frameIndex];
            output << "{\"sourceSeconds\": " << number(keyframe.sourceSeconds)
                   << ", \"value\": " << number(keyframe.value)
                   << ", \"interpolation\": " << quote(keyframe.interpolation) << "}";
            if (frameIndex + 1 != lane.keyframes.size()) {
                output << ", ";
            }
        }
        output << "]}" << (laneIndex + 1 == session.lanes.size() ? "\n" : ",\n");
    }
    output << "  ]\n";
    output << "}\n";
    return output.str();
}

[[nodiscard]] inline std::optional<AuthoringAnchor> nearestAnchorForDeck(const std::vector<AuthoringAnchor>& anchors,
                                                                         const AuthoringDeck deck,
                                                                         const double sourceSeconds) {
    std::optional<AuthoringAnchor> nearest;
    auto bestDistance = std::numeric_limits<double>::max();
    for (const auto& anchor : anchors) {
        if (anchor.deck != deck) {
            continue;
        }
        const auto distance = std::abs(anchor.sourceSeconds - sourceSeconds);
        if (distance < bestDistance) {
            bestDistance = distance;
            nearest = anchor;
        }
    }
    return nearest;
}

[[nodiscard]] inline std::string writeTransitionRecipeJson(const AuthoringSession& session) {
    std::ostringstream output;
    output << "{\n";
    output << "  \"schemaVersion\": \"1.0.0\",\n";
    output << "  \"recipeId\": " << quote("recipe-" + session.sessionId) << ",\n";
    output << "  \"transitionFamily\": " << quote(session.transitionFamily) << ",\n";
    output << "  \"semanticRequirements\": {\n";
    output << "    \"exactBpmRequired\": true,\n";
    output << "    \"camelotKeyCompatibility\": \"placeholder\",\n";
    output << "    \"requiredAnchors\": [";
    for (std::size_t index = 0; index < session.anchors.size(); ++index) {
        output << quote(session.anchors[index].name);
        if (index + 1 != session.anchors.size()) {
            output << ", ";
        }
    }
    output << "],\n";
    output << "    \"energyNotes\": \"\",\n";
    output << "    \"humanNotes\": " << quote(session.notes) << "\n";
    output << "  },\n";
    output << "  \"anchors\": [\n";
    for (std::size_t index = 0; index < session.anchors.size(); ++index) {
        const auto& anchor = session.anchors[index];
        output << "    {\"name\": " << quote(anchor.name)
               << ", \"deck\": " << quote(std::string(1, deckName(anchor.deck)))
               << ", \"semanticRef\": " << quote(anchor.semanticRef.empty() ? anchor.name : anchor.semanticRef)
               << "}" << (index + 1 == session.anchors.size() ? "\n" : ",\n");
    }
    output << "  ],\n";
    output << "  \"automation\": [\n";
    for (std::size_t laneIndex = 0; laneIndex < session.lanes.size(); ++laneIndex) {
        const auto& lane = session.lanes[laneIndex];
        const auto& deck = deckStateFor(session, lane.deck);
        const auto beatSeconds = beatDurationSeconds(deck);
        output << "    {\"deck\": " << quote(std::string(1, deckName(lane.deck)))
               << ", \"control\": " << quote(lane.control) << ", \"keyframes\": [";
        for (std::size_t frameIndex = 0; frameIndex < lane.keyframes.size(); ++frameIndex) {
            const auto& keyframe = lane.keyframes[frameIndex];
            const auto anchor = nearestAnchorForDeck(session.anchors, lane.deck, keyframe.sourceSeconds);
            const auto anchorName = anchor.has_value() ? anchor->name : std::string{"unanchored"};
            const auto anchorSeconds = anchor.has_value() ? anchor->sourceSeconds : keyframe.sourceSeconds;
            output << "{\"anchor\": " << quote(anchorName)
                   << ", \"offsetBeats\": " << number((keyframe.sourceSeconds - anchorSeconds) / beatSeconds)
                   << ", \"value\": " << number(keyframe.value)
                   << ", \"interpolation\": " << quote(keyframe.interpolation) << "}";
            if (frameIndex + 1 != lane.keyframes.size()) {
                output << ", ";
            }
        }
        output << "]}" << (laneIndex + 1 == session.lanes.size() ? "\n" : ",\n");
    }
    output << "  ],\n";
    output << "  \"warnings\": []\n";
    output << "}\n";
    return output.str();
}

[[nodiscard]] inline std::string mixPlanTechniqueForFamily(std::string_view family) {
    if (family == "drop_switch") {
        return "build_to_drop_swap";
    }
    if (family == "double_drop") {
        return "drop_double";
    }
    if (family == "reverb_exit") {
        return "drop_end_reverb_exit";
    }
    return "hard_cut";
}

[[nodiscard]] inline std::string writeSpecificMixPlanJson(const AuthoringSession& session) {
    auto earliestDelta = 0.0;
    auto latestDelta = 32.0;
    for (const auto& lane : session.lanes) {
        const auto& deck = deckStateFor(session, lane.deck);
        for (const auto& keyframe : lane.keyframes) {
            const auto delta = keyframe.sourceSeconds - deck.centerSeconds;
            earliestDelta = std::min(earliestDelta, delta);
            latestDelta = std::max(latestDelta, delta);
        }
    }
    const auto sourceStartA = std::max(0.0, session.deckA.centerSeconds + earliestDelta);
    const auto sourceStartB = std::max(0.0, session.deckB.centerSeconds + earliestDelta);
    const auto duration = std::max(4.0, latestDelta - earliestDelta);
    const auto previewDelayA = std::max(0.0, session.deckA.previewStartDelaySeconds);
    const auto previewDelayB = std::max(0.0, session.deckB.previewStartDelaySeconds);
    const auto planDuration = duration + std::max(previewDelayA, previewDelayB);

    std::ostringstream output;
    output << "{\n";
    output << "  \"schemaVersion\": \"1.0.0\",\n";
    output << "  \"planId\": " << quote("manual-" + session.sessionId) << ",\n";
    output << "  \"createdAtUtc\": \"2026-05-20T00:00:00Z\",\n";
    output << "  \"strategy\": {\"strategyId\": \"transition-authoring-workbench\", \"strategyVersion\": \"0.1.0\"},\n";
    output << "  \"assets\": [\n";
    output << "    {\"trackId\": " << quote(session.deckA.trackId) << ", \"sourceUri\": " << quote(session.deckA.audioPath) << "},\n";
    output << "    {\"trackId\": " << quote(session.deckB.trackId) << ", \"sourceUri\": " << quote(session.deckB.audioPath) << "}\n";
    output << "  ],\n";
    output << "  \"tracks\": [\n";
    output << "    {\"placementId\": \"place-a\", \"trackId\": " << quote(session.deckA.trackId)
           << ", \"deck\": 1, \"sourceStartSeconds\": " << number(sourceStartA)
           << ", \"timelineStartSeconds\": " << number(previewDelayA)
           << ", \"timelineEndSeconds\": " << number(previewDelayA + duration)
           << ", \"role\": \"primary\"},\n";
    output << "    {\"placementId\": \"place-b\", \"trackId\": " << quote(session.deckB.trackId)
           << ", \"deck\": 2, \"sourceStartSeconds\": " << number(sourceStartB)
           << ", \"timelineStartSeconds\": " << number(previewDelayB)
           << ", \"timelineEndSeconds\": " << number(previewDelayB + duration)
           << ", \"role\": \"incoming\"}\n";
    output << "  ],\n";
    output << "  \"transitions\": [{\"transitionId\": \"transition-authored\", \"fromPlacementId\": \"place-a\", \"toPlacementId\": \"place-b\", \"technique\": "
           << quote(mixPlanTechniqueForFamily(session.transitionFamily))
           << ", \"templateId\": \"transition_authoring_workbench_v1\", \"timelineStartSeconds\": 0, \"timelineEndSeconds\": "
           << number(planDuration) << ", \"score\": 1, \"reasons\": [" << quote(session.notes) << "]}],\n";
    output << "  \"commands\": [\n";
    struct CommandJson final {
        double at{0.0};
        std::string text;
    };
    std::vector<CommandJson> commands;
    commands.push_back(CommandJson{
        .at = 0.0,
        .text = "    {\"type\": \"load\", \"at\": 0, \"deck\": 1, \"trackId\": " + quote(session.deckA.trackId)
                + ", \"stem\": \"full\", \"cueSeconds\": " + number(sourceStartA) + "}",
    });
    commands.push_back(CommandJson{
        .at = 0.0,
        .text = "    {\"type\": \"load\", \"at\": 0, \"deck\": 2, \"trackId\": " + quote(session.deckB.trackId)
                + ", \"stem\": \"full\", \"cueSeconds\": " + number(sourceStartB) + "}",
    });
    const auto hasPlayLane = [&](const AuthoringDeck deck) {
        return std::any_of(session.lanes.begin(), session.lanes.end(), [&](const auto& lane) {
            return lane.deck == deck && lane.control == "play" && !lane.keyframes.empty();
        });
    };
    if (!hasPlayLane(AuthoringDeck::A)) {
        commands.push_back(CommandJson{.at = previewDelayA,
                                       .text = "    {\"type\": \"play\", \"at\": " + number(previewDelayA) + ", \"deck\": 1}"});
    }
    if (!hasPlayLane(AuthoringDeck::B)) {
        commands.push_back(CommandJson{.at = previewDelayB,
                                       .text = "    {\"type\": \"play\", \"at\": " + number(previewDelayB) + ", \"deck\": 2}"});
    }
    for (const auto& lane : session.lanes) {
        const auto& deck = deckStateFor(session, lane.deck);
        const auto sourceStart = lane.deck == AuthoringDeck::A ? sourceStartA : sourceStartB;
        const auto previewDelay = lane.deck == AuthoringDeck::A ? previewDelayA : previewDelayB;
        if (isEventControl(lane.control)) {
            for (const auto& keyframe : lane.keyframes) {
                const auto at = std::max(0.0, previewDelay + keyframe.sourceSeconds - sourceStart);
                commands.push_back(CommandJson{
                    .at = at,
                    .text = "    {\"type\": " + quote(lane.control) + ", \"at\": " + number(at)
                            + ", \"deck\": " + std::to_string(deckNumber(lane.deck)) + "}",
                });
            }
            continue;
        }
        std::ostringstream command;
        auto firstAt = 0.0;
        if (!lane.keyframes.empty()) {
            firstAt = std::max(0.0, previewDelay + lane.keyframes.front().sourceSeconds - sourceStart);
        }
        command << "    {\"type\": \"automate\", \"deck\": " << deckNumber(lane.deck)
                << ", \"control\": " << quote(lane.control) << ", \"keyframes\": [";
        for (std::size_t index = 0; index < lane.keyframes.size(); ++index) {
            const auto& keyframe = lane.keyframes[index];
            command << "{\"at\": " << number(std::max(0.0, previewDelay + keyframe.sourceSeconds - sourceStart))
                    << ", \"value\": " << number(keyframe.value)
                    << ", \"interpolation\": " << quote(keyframe.interpolation) << "}";
            if (index + 1 != lane.keyframes.size()) {
                command << ", ";
            }
        }
        command << "]}";
        commands.push_back(CommandJson{.at = firstAt, .text = command.str()});
    }
    std::stable_sort(commands.begin(), commands.end(), [](const auto& left, const auto& right) {
        return left.at < right.at;
    });
    for (std::size_t index = 0; index < commands.size(); ++index) {
        output << commands[index].text;
        if (index + 1 != commands.size()) {
            output << ",\n";
        }
    }
    output << "\n  ],\n";
    output << "  \"annotations\": [{\"at\": 0, \"transitionId\": \"transition-authored\", \"message\": \"Exported from transition authoring workbench\"}]\n";
    output << "}\n";
    return output.str();
}

}  // namespace autodj::desktop
