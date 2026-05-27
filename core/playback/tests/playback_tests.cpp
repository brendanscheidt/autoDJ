#include "autodj/playback/playback.hpp"

#include <cassert>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <limits>
#include <sstream>
#include <string>

namespace {

std::string valid_plan_json() {
    return R"json({
  "schemaVersion": "1.0.0",
  "planId": "plan-test",
  "createdAtUtc": "2026-01-01T00:00:00Z",
  "strategy": {
    "strategyId": "test-strategy",
    "strategyVersion": "1.0.0"
  },
  "assets": [
    {
      "trackId": "track-a",
      "sourceUri": "fixtures/track-a.wav",
      "formatHint": "wav"
    },
    {
      "trackId": "track-b",
      "sourceUri": "fixtures/track-b.wav",
      "formatHint": "wav"
    }
  ],
  "tracks": [
    {
      "placementId": "place-a",
      "trackId": "track-a",
      "deck": 1,
      "sourceStartSeconds": 0.0,
      "timelineStartSeconds": 0.0
    },
    {
      "placementId": "place-b",
      "trackId": "track-b",
      "deck": 2,
      "sourceStartSeconds": 0.0,
      "timelineStartSeconds": 16.0
    }
  ],
  "transitions": [
    {
      "transitionId": "transition-test",
      "fromPlacementId": "place-a",
      "toPlacementId": "place-b",
      "technique": "hard_cut",
      "timelineStartSeconds": 16.0,
      "timelineEndSeconds": 16.0,
      "score": 0.5,
      "reasons": [
        "test transition"
      ]
    }
  ],
  "commands": [
    {
      "type": "load",
      "at": 0.0,
      "deck": 1,
      "trackId": "track-a",
      "cueSeconds": 0.0
    },
    {
      "type": "play",
      "at": 0.0,
      "deck": 1
    }
  ]
})json";
}

std::string plan_with_seek_and_automation_json() {
    return R"json({
  "schemaVersion": "1.0.0",
  "planId": "plan-seek-automation-test",
  "createdAtUtc": "2026-01-01T00:00:00Z",
  "strategy": {
    "strategyId": "test-strategy",
    "strategyVersion": "1.0.0"
  },
  "assets": [
    {
      "trackId": "track-a",
      "sourceUri": "fixtures/track-a.wav"
    }
  ],
  "tracks": [
    {
      "placementId": "place-a",
      "trackId": "track-a",
      "deck": 1,
      "sourceStartSeconds": 0.0,
      "timelineStartSeconds": 0.0
    }
  ],
  "transitions": [
    {
      "transitionId": "transition-test",
      "fromPlacementId": "place-a",
      "toPlacementId": "place-a",
      "technique": "hard_cut",
      "timelineStartSeconds": 0.0,
      "timelineEndSeconds": 0.0,
      "score": 0.5,
      "reasons": [
        "test transition"
      ]
    }
  ],
  "commands": [
    {
      "type": "load",
      "at": 0.0,
      "deck": 1,
      "trackId": "track-a",
      "cueSeconds": 2.0
    },
    {
      "type": "play",
      "at": 0.0,
      "deck": 1
    },
    {
      "type": "automate",
      "deck": 1,
      "control": "volume",
      "keyframes": [
        {
          "at": 0.0,
          "value": 0.0,
          "interpolation": "hold"
        },
        {
          "at": 10.0,
          "value": 1.0,
          "interpolation": "linear"
        }
      ]
    },
    {
      "type": "automate",
      "control": "crossfader",
      "keyframes": [
        {
          "at": 0.0,
          "value": -1.0,
          "interpolation": "hold"
        },
        {
          "at": 10.0,
          "value": 1.0,
          "interpolation": "linear"
        }
      ]
    },
    {
      "type": "seek",
      "at": 20.0,
      "deck": 1,
      "toSeconds": 5.0
    }
  ]
})json";
}

std::string same_time_priority_plan_json() {
    return R"json({
  "schemaVersion": "1.0.0",
  "planId": "plan-same-time-priority-test",
  "createdAtUtc": "2026-01-01T00:00:00Z",
  "strategy": {
    "strategyId": "test-strategy",
    "strategyVersion": "1.0.0"
  },
  "assets": [
    {
      "trackId": "track-old",
      "sourceUri": "fixtures/track-old.wav"
    },
    {
      "trackId": "track-new",
      "sourceUri": "fixtures/track-new.wav"
    }
  ],
  "tracks": [
    {
      "placementId": "place-old",
      "trackId": "track-old",
      "deck": 1,
      "sourceStartSeconds": 0.0,
      "timelineStartSeconds": 0.0
    },
    {
      "placementId": "place-new",
      "trackId": "track-new",
      "deck": 1,
      "sourceStartSeconds": 12.0,
      "timelineStartSeconds": 8.0
    }
  ],
  "transitions": [
    {
      "transitionId": "transition-test",
      "fromPlacementId": "place-old",
      "toPlacementId": "place-new",
      "technique": "hard_cut",
      "timelineStartSeconds": 8.0,
      "timelineEndSeconds": 8.0,
      "score": 0.5,
      "reasons": [
        "test transition"
      ]
    }
  ],
  "commands": [
    {
      "type": "load",
      "at": 0.0,
      "deck": 1,
      "trackId": "track-old",
      "cueSeconds": 0.0
    },
    {
      "type": "play",
      "at": 0.0,
      "deck": 1
    },
    {
      "type": "play",
      "at": 8.0,
      "deck": 1
    },
    {
      "type": "load",
      "at": 8.0,
      "deck": 1,
      "trackId": "track-new",
      "cueSeconds": 12.0
    },
    {
      "type": "stop",
      "at": 8.0,
      "deck": 1
    }
  ]
})json";
}

std::string read_file_text(const std::filesystem::path& path) {
    std::ifstream input{path};
    std::ostringstream buffer;
    buffer << input.rdbuf();
    return buffer.str();
}

bool contains_error_code(const autodj::playback::PlanValidationResult& result, const std::string& code) {
    for (const auto& error : result.errors) {
        if (error.code == code) {
            return true;
        }
    }
    return false;
}

bool nearly_equal(const double left, const double right) {
    return std::fabs(left - right) < 0.000001;
}

void initial_state_is_stopped_without_plan() {
    const autodj::playback::PlaybackEngine engine;
    const auto state = engine.getState();

    assert(state.transport == autodj::playback::TransportState::Stopped);
    assert(state.timelineSeconds == 0.0);
    assert(!state.hasLoadedPlan);
}

void load_plan_rejects_empty_placeholder() {
    autodj::playback::PlaybackEngine engine;

    const auto result = engine.loadPlan("   \n\t");
    const auto state = engine.getState();

    assert(!result.ok);
    assert(result.errors.size() == 1);
    assert(result.errors.front().code == "empty_plan");
    assert(!state.hasLoadedPlan);
    assert(state.transport == autodj::playback::TransportState::Stopped);
}

void load_plan_accepts_valid_mix_plan() {
    autodj::playback::PlaybackEngine engine;

    const auto result = engine.loadPlan(valid_plan_json());
    const auto state = engine.getState();

    assert(result.ok);
    assert(result.errors.empty());
    assert(state.hasLoadedPlan);
    assert(state.transport == autodj::playback::TransportState::Stopped);
    assert(state.timelineSeconds == 0.0);
}

void parse_mix_plan_reads_contract_fixture_poc_fields() {
    const auto fixturePath = std::filesystem::path{AUTODJ_CONTRACTS_DIR} / "examples" / "mix-plan.stub.json";
    const auto parsed = autodj::playback::parseMixPlan(read_file_text(fixturePath));

    assert(parsed.validation.ok);
    assert(parsed.plan.has_value());

    const auto& plan = parsed.plan.value();
    assert(plan.assets.size() == 3);
    assert(plan.assets[0].sourceBpm == 140.0);
    assert(plan.assets[1].sourceBpm == 150.0);
    assert(plan.tracks.size() == 3);
    assert(plan.tracks[1].tempoPlan.has_value());
    assert(plan.tracks[1].tempoPlan->sourceBpm == 150.0);
    assert(plan.tracks[1].tempoPlan->targetBpm == 140.0);
    assert(plan.tracks[1].tempoPlan->preservePitch == true);
    assert(plan.tracks[1].tempoPlan->backend == "soundstretch");
    assert(plan.tracks[1].tempoPlan->requiresRenderedBpmValidation == true);
    assert(plan.transitions.size() == 2);
    assert(plan.transitions[0].technique == autodj::playback::TransitionTechnique::BuildToDropSwap);
    assert(plan.transitions[0].templateId == "second_build_drop_switch_v1");
    assert(plan.transitions[0].measureCountToTarget == 8.0);
    assert(plan.transitions[0].tempoPlan.has_value());
    assert(plan.transitions[0].tempoPlan->tempoRatio.has_value());
    assert(nearly_equal(plan.transitions[0].tempoPlan->tempoRatio.value(), 0.933333));
    assert(plan.transitions[1].technique == autodj::playback::TransitionTechnique::WashOut);
    assert(plan.transitions[1].templateId == "drop_end_wash_out_v1");
    assert(plan.transitions[1].sourceAnchors.contains("toFirstBeat"));

    bool foundReverbTailCommand = false;
    bool foundTempoCommand = false;
    for (const auto& command : plan.commands) {
        if (command.type == autodj::playback::DeckCommandType::Automate && command.control.has_value()
            && command.control.value() == autodj::playback::AutomationControl::ReverbTailGain) {
            foundReverbTailCommand = true;
            assert(command.postFader);
            assert(command.effectParameters.contains("reverbDecaySeconds"));
            assert(command.keyframes.size() == 2);
        }
        if (command.type == autodj::playback::DeckCommandType::Automate && command.control.has_value()
            && command.control.value() == autodj::playback::AutomationControl::Tempo) {
            foundTempoCommand = true;
            assert(command.effectParameters.contains("preservePitch"));
            assert(command.effectParameters.contains("requiresRenderedBpmValidation"));
            assert(command.keyframes.size() == 1);
            assert(nearly_equal(command.keyframes.front().value, 0.933333));
        }
    }
    assert(foundReverbTailCommand);
    assert(foundTempoCommand);
}

void parse_mix_plan_rejects_malformed_json() {
    const auto parsed = autodj::playback::parseMixPlan("{");

    assert(!parsed.validation.ok);
    assert(!parsed.plan.has_value());
    assert(contains_error_code(parsed.validation, "malformed_json"));
}

void parse_mix_plan_rejects_missing_required_fields() {
    const auto parsed = autodj::playback::parseMixPlan(R"json({"schemaVersion":"1.0.0"})json");

    assert(!parsed.validation.ok);
    assert(!parsed.plan.has_value());
    assert(contains_error_code(parsed.validation, "missing_string"));
    assert(contains_error_code(parsed.validation, "missing_array"));
}

void parse_mix_plan_rejects_unknown_transition_placement() {
    auto json = valid_plan_json();
    const auto oldText = std::string{R"json("toPlacementId": "place-b")json"};
    const auto replacement = std::string{R"json("toPlacementId": "place-missing")json"};
    json.replace(json.find(oldText), oldText.size(), replacement);

    const auto parsed = autodj::playback::parseMixPlan(json);

    assert(!parsed.validation.ok);
    assert(contains_error_code(parsed.validation, "unknown_to_placement"));
}

void parse_mix_plan_rejects_unsorted_commands() {
    auto json = valid_plan_json();
    const auto oldText = std::string{R"json("type": "load",
      "at": 0.0)json"};
    const auto replacement = std::string{R"json("type": "load",
      "at": 99.0)json"};
    json.replace(json.find(oldText), oldText.size(), replacement);

    const auto parsed = autodj::playback::parseMixPlan(json);

    assert(!parsed.validation.ok);
    assert(contains_error_code(parsed.validation, "commands_not_sorted"));
}

void parse_mix_plan_rejects_invalid_template_invariants() {
    const auto parsed = autodj::playback::parseMixPlan(R"json({
  "schemaVersion": "1.0.0",
  "planId": "plan-bad-template",
  "createdAtUtc": "2026-01-01T00:00:00Z",
  "strategy": {
    "strategyId": "test-strategy",
    "strategyVersion": "1.0.0"
  },
  "tracks": [
    {
      "placementId": "place-a",
      "trackId": "track-a",
      "deck": 1,
      "sourceStartSeconds": 0.0,
      "timelineStartSeconds": 0.0
    },
    {
      "placementId": "place-b",
      "trackId": "track-b",
      "deck": 2,
      "sourceStartSeconds": 0.0,
      "timelineStartSeconds": 16.0
    }
  ],
  "transitions": [
    {
      "transitionId": "transition-bad",
      "fromPlacementId": "place-a",
      "toPlacementId": "place-b",
      "technique": "build_to_drop_swap",
      "templateId": "second_build_drop_switch_v1",
      "timelineStartSeconds": 0.0,
      "timelineEndSeconds": 16.0,
      "alignedDropTimelineSeconds": 8.0,
      "handoffTimelineSeconds": 12.0,
      "score": 0.5,
      "reasons": [
        "bad handoff"
      ]
    }
  ],
  "commands": [
    {
      "type": "load",
      "at": 0.0,
      "deck": 1,
      "trackId": "track-a",
      "cueSeconds": 0.0
    }
  ]
})json");

    assert(!parsed.validation.ok);
    assert(contains_error_code(parsed.validation, "missing_measure_count"));
    assert(contains_error_code(parsed.validation, "invalid_handoff"));
}

void parse_mix_plan_rejects_invalid_tempo_plan_numbers() {
    const auto parsed = autodj::playback::parseMixPlan(R"json({
  "schemaVersion": "1.0.0",
  "planId": "plan-bad-tempo",
  "createdAtUtc": "2026-01-01T00:00:00Z",
  "strategy": {
    "strategyId": "test-strategy",
    "strategyVersion": "1.0.0"
  },
  "tracks": [
    {
      "placementId": "place-a",
      "trackId": "track-a",
      "deck": 1,
      "sourceStartSeconds": 0.0,
      "timelineStartSeconds": 0.0,
      "tempoPlan": {
        "sourceBpm": 140.0,
        "targetBpm": 0.0,
        "tempoRatio": 0.0,
        "preservePitch": true
      }
    }
  ],
  "transitions": [
    {
      "transitionId": "transition-test",
      "fromPlacementId": "place-a",
      "toPlacementId": "place-a",
      "technique": "hard_cut",
      "timelineStartSeconds": 0.0,
      "timelineEndSeconds": 0.0,
      "score": 0.5,
      "reasons": [
        "test transition"
      ]
    }
  ],
  "commands": [
    {
      "type": "load",
      "at": 0.0,
      "deck": 1,
      "trackId": "track-a",
      "cueSeconds": 0.0
    }
  ]
})json");

    assert(!parsed.validation.ok);
    assert(contains_error_code(parsed.validation, "invalid_tempo_plan"));
}

void execution_state_advances_loaded_playing_deck_source_time() {
    autodj::playback::PlaybackEngine engine;
    const auto result = engine.loadPlan(valid_plan_json());
    assert(result.ok);

    const auto execution = engine.evaluateAt(10.0);

    assert(execution.timelineSeconds == 10.0);
    assert(execution.decks.contains(1));
    const auto& deck = execution.decks.at(1);
    assert(deck.loaded);
    assert(deck.playing);
    assert(deck.trackId.value == "track-a");
    assert(nearly_equal(deck.sourceSeconds, 10.0));
}

void execution_state_recomputes_after_seek_without_incremental_guessing() {
    autodj::playback::PlaybackEngine engine;
    const auto result = engine.loadPlan(plan_with_seek_and_automation_json());
    assert(result.ok);

    const auto directExecution = engine.evaluateAt(30.0);
    assert(directExecution.decks.contains(1));
    assert(nearly_equal(directExecution.decks.at(1).sourceSeconds, 15.0));

    assert(engine.seek(30.0));
    const auto seekExecution = engine.getExecutionState();
    assert(seekExecution.decks.contains(1));
    assert(nearly_equal(seekExecution.decks.at(1).sourceSeconds, 15.0));
}

void execution_state_interpolates_deck_and_global_automation() {
    autodj::playback::PlaybackEngine engine;
    const auto result = engine.loadPlan(plan_with_seek_and_automation_json());
    assert(result.ok);

    const auto execution = engine.evaluateAt(5.0);

    assert(execution.decks.contains(1));
    const auto& deck = execution.decks.at(1);
    assert(deck.controls.contains(autodj::playback::AutomationControl::Volume));
    assert(nearly_equal(deck.controls.at(autodj::playback::AutomationControl::Volume).value, 0.5));
    assert(execution.globalControls.contains(autodj::playback::AutomationControl::Crossfader));
    assert(nearly_equal(execution.globalControls.at(autodj::playback::AutomationControl::Crossfader).value, 0.0));
}

void execution_state_uses_deterministic_same_time_priority() {
    autodj::playback::PlaybackEngine engine;
    const auto result = engine.loadPlan(same_time_priority_plan_json());
    assert(result.ok);

    const auto execution = engine.evaluateAt(8.0);

    assert(execution.decks.contains(1));
    const auto& deck = execution.decks.at(1);
    assert(deck.loaded);
    assert(deck.playing);
    assert(deck.trackId.value == "track-new");
    assert(nearly_equal(deck.sourceSeconds, 12.0));
}

void invalid_plan_cannot_start_playback() {
    autodj::playback::PlaybackEngine engine;
    const auto result = engine.loadPlan(R"json({"schemaVersion":"1.0.0"})json");
    assert(!result.ok);

    engine.play();

    const auto state = engine.getState();
    assert(!state.hasLoadedPlan);
    assert(state.transport == autodj::playback::TransportState::Stopped);
    assert(engine.getExecutionState().decks.empty());
}

void play_requires_loaded_plan() {
    autodj::playback::PlaybackEngine engine;

    engine.play();

    assert(engine.getState().transport == autodj::playback::TransportState::Stopped);
}

void transport_state_transitions_are_deterministic() {
    autodj::playback::PlaybackEngine engine;
    (void)engine.loadPlan(valid_plan_json());

    engine.play();
    assert(engine.getState().transport == autodj::playback::TransportState::Playing);

    engine.pause();
    assert(engine.getState().transport == autodj::playback::TransportState::Paused);

    engine.stop();
    assert(engine.getState().transport == autodj::playback::TransportState::Stopped);
    assert(engine.getState().timelineSeconds == 0.0);
}

void seek_accepts_non_negative_finite_times() {
    autodj::playback::PlaybackEngine engine;
    (void)engine.loadPlan(valid_plan_json());

    const bool seeked = engine.seek(42.25);

    assert(seeked);
    assert(engine.getState().timelineSeconds == 42.25);
}

void seek_rejects_negative_and_non_finite_times() {
    autodj::playback::PlaybackEngine engine;
    (void)engine.loadPlan(valid_plan_json());

    assert(engine.seek(5.0));
    assert(!engine.seek(-1.0));
    assert(engine.getState().timelineSeconds == 5.0);

    assert(!engine.seek(std::numeric_limits<double>::infinity()));
    assert(engine.getState().timelineSeconds == 5.0);
}

void loading_invalid_plan_resets_state() {
    autodj::playback::PlaybackEngine engine;
    (void)engine.loadPlan(valid_plan_json());
    engine.play();
    assert(engine.seek(12.0));

    const auto result = engine.loadPlan("");
    const auto state = engine.getState();

    assert(!result.ok);
    assert(!state.hasLoadedPlan);
    assert(state.transport == autodj::playback::TransportState::Stopped);
    assert(state.timelineSeconds == 0.0);
}

}  // namespace

int main() {
    initial_state_is_stopped_without_plan();
    load_plan_rejects_empty_placeholder();
    load_plan_accepts_valid_mix_plan();
    parse_mix_plan_reads_contract_fixture_poc_fields();
    parse_mix_plan_rejects_malformed_json();
    parse_mix_plan_rejects_missing_required_fields();
    parse_mix_plan_rejects_unknown_transition_placement();
    parse_mix_plan_rejects_unsorted_commands();
    parse_mix_plan_rejects_invalid_template_invariants();
    parse_mix_plan_rejects_invalid_tempo_plan_numbers();
    execution_state_advances_loaded_playing_deck_source_time();
    execution_state_recomputes_after_seek_without_incremental_guessing();
    execution_state_interpolates_deck_and_global_automation();
    execution_state_uses_deterministic_same_time_priority();
    invalid_plan_cannot_start_playback();
    play_requires_loaded_plan();
    transport_state_transitions_are_deterministic();
    seek_accepts_non_negative_finite_times();
    seek_rejects_negative_and_non_finite_times();
    loading_invalid_plan_resets_state();

    return 0;
}
