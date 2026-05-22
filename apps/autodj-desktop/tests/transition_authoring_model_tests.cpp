#include "TransitionAuthoringModel.hpp"

#include "autodj/playback/mix_plan.hpp"

#include <cassert>
#include <string>

namespace {

using autodj::desktop::AuthoringAnchor;
using autodj::desktop::AuthoringDeck;
using autodj::desktop::AuthoringKeyframe;
using autodj::desktop::AuthoringSession;
using autodj::desktop::AutomationLane;

AuthoringSession makeSession() {
    AuthoringSession session;
    session.sessionId = "test-session";
    session.transitionFamily = "drop_switch";
    session.notes = "test notes";
    session.deckA.deck = AuthoringDeck::A;
    session.deckA.trackId = "track-a";
    session.deckA.audioPath = "fixtures/audio/a.mp3";
    session.deckA.analyzedTrackPath = "fixtures/a/analyzed-track.json";
    session.deckA.debugWaveformPath = "fixtures/a/debug-waveform.json";
    session.deckA.centerSeconds = 16.0;
    session.deckA.normalizedBpm = 120.0;
    for (int index = 0; index <= 48; ++index) {
        session.deckA.beats.push_back(static_cast<double>(index) * 0.5);
    }
    session.deckB.deck = AuthoringDeck::B;
    session.deckB.trackId = "track-b";
    session.deckB.audioPath = "fixtures/audio/b.mp3";
    session.deckB.analyzedTrackPath = "fixtures/b/analyzed-track.json";
    session.deckB.debugWaveformPath = "fixtures/b/debug-waveform.json";
    session.deckB.centerSeconds = 8.0;
    session.deckB.normalizedBpm = 120.0;
    session.deckB.beats = session.deckA.beats;
    session.anchors.push_back(AuthoringAnchor{
        .name = "a.dropStart",
        .deck = AuthoringDeck::A,
        .sourceSeconds = 16.0,
        .semanticRef = "song_a.drop.start",
    });
    session.anchors.push_back(AuthoringAnchor{
        .name = "b.dropStart",
        .deck = AuthoringDeck::B,
        .sourceSeconds = 8.0,
        .semanticRef = "song_b.drop.start",
    });
    AutomationLane lane;
    lane.deck = AuthoringDeck::B;
    lane.control = "volume";
    lane.keyframes.push_back(AuthoringKeyframe{
        .deck = AuthoringDeck::B,
        .control = "volume",
        .sourceSeconds = 6.0,
        .value = 0.0,
        .interpolation = "hold",
    });
    lane.keyframes.push_back(AuthoringKeyframe{
        .deck = AuthoringDeck::B,
        .control = "volume",
        .sourceSeconds = 8.0,
        .value = 1.0,
        .interpolation = "smoothstep",
    });
    session.lanes.push_back(lane);
    return session;
}

void bar_beat_labels_use_first_beat_as_one_one() {
    const std::vector<double> beats{0.0, 0.5, 1.0, 1.5, 2.0};
    assert(autodj::desktop::barBeatLabelForTime(beats, 0.0) == "1.1");
    assert(autodj::desktop::barBeatLabelForTime(beats, 1.55) == "1.4");
    assert(autodj::desktop::barBeatLabelForTime(beats, 2.0) == "2.1");
}

void nearest_beat_snapping_is_stable() {
    const std::vector<double> beats{0.0, 0.5, 1.0};
    assert(autodj::desktop::nearestBeatIndex(beats, 0.76).value() == 2);
    assert(autodj::desktop::snapToNearestBeat(beats, 0.74) == 0.5);
}

void session_and_recipe_exports_include_expected_fields() {
    const auto session = makeSession();
    const auto sessionJson = autodj::desktop::writeAuthoringSessionJson(session);
    const auto recipeJson = autodj::desktop::writeTransitionRecipeJson(session);
    assert(sessionJson.find("\"sessionId\": \"test-session\"") != std::string::npos);
    assert(sessionJson.find("\"barBeat\": \"9.1\"") != std::string::npos);
    assert(recipeJson.find("\"recipeId\": \"recipe-test-session\"") != std::string::npos);
    assert(recipeJson.find("\"anchor\": \"b.dropStart\"") != std::string::npos);
    assert(recipeJson.find("\"offsetBeats\": -4") != std::string::npos);
}

void specific_mix_plan_export_parses_with_playback_validator() {
    const auto session = makeSession();
    const auto planJson = autodj::desktop::writeSpecificMixPlanJson(session);
    const auto result = autodj::playback::parseMixPlan(planJson);
    assert(result.validation.ok);
    assert(result.plan.has_value());
    assert(result.plan->commands.size() >= 5);
}

void play_stop_lanes_export_as_deck_commands() {
    auto session = makeSession();
    AutomationLane playLane;
    playLane.deck = AuthoringDeck::B;
    playLane.control = "play";
    playLane.keyframes.push_back(AuthoringKeyframe{
        .deck = AuthoringDeck::B,
        .control = "play",
        .sourceSeconds = 7.0,
        .value = 1.0,
        .interpolation = "hold",
    });
    AutomationLane stopLane;
    stopLane.deck = AuthoringDeck::B;
    stopLane.control = "stop";
    stopLane.keyframes.push_back(AuthoringKeyframe{
        .deck = AuthoringDeck::B,
        .control = "stop",
        .sourceSeconds = 8.0,
        .value = 1.0,
        .interpolation = "hold",
    });
    session.lanes.push_back(playLane);
    session.lanes.push_back(stopLane);
    const auto planJson = autodj::desktop::writeSpecificMixPlanJson(session);
    assert(planJson.find("\"type\": \"play\", \"at\": 1, \"deck\": 2") != std::string::npos);
    assert(planJson.find("\"type\": \"stop\", \"at\": 2, \"deck\": 2") != std::string::npos);
    const auto result = autodj::playback::parseMixPlan(planJson);
    assert(result.validation.ok);
}

}  // namespace

int main() {
    bar_beat_labels_use_first_beat_as_one_one();
    nearest_beat_snapping_is_stable();
    session_and_recipe_exports_include_expected_fields();
    specific_mix_plan_export_parses_with_playback_validator();
    play_stop_lanes_export_as_deck_commands();
    return 0;
}
