#include "autodj/playback/playback.hpp"

#include <cassert>
#include <limits>

namespace {

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

void load_plan_accepts_non_empty_placeholder() {
    autodj::playback::PlaybackEngine engine;

    const auto result = engine.loadPlan("{\"schemaVersion\":\"autodj.mix-plan.v1\"}");
    const auto state = engine.getState();

    assert(result.ok);
    assert(result.errors.empty());
    assert(state.hasLoadedPlan);
    assert(state.transport == autodj::playback::TransportState::Stopped);
    assert(state.timelineSeconds == 0.0);
}

void play_requires_loaded_plan() {
    autodj::playback::PlaybackEngine engine;

    engine.play();

    assert(engine.getState().transport == autodj::playback::TransportState::Stopped);
}

void transport_state_transitions_are_deterministic() {
    autodj::playback::PlaybackEngine engine;
    (void)engine.loadPlan("{\"planId\":\"plan-test\"}");

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
    (void)engine.loadPlan("{\"planId\":\"plan-test\"}");

    const bool seeked = engine.seek(42.25);

    assert(seeked);
    assert(engine.getState().timelineSeconds == 42.25);
}

void seek_rejects_negative_and_non_finite_times() {
    autodj::playback::PlaybackEngine engine;
    (void)engine.loadPlan("{\"planId\":\"plan-test\"}");

    assert(engine.seek(5.0));
    assert(!engine.seek(-1.0));
    assert(engine.getState().timelineSeconds == 5.0);

    assert(!engine.seek(std::numeric_limits<double>::infinity()));
    assert(engine.getState().timelineSeconds == 5.0);
}

void loading_invalid_plan_resets_state() {
    autodj::playback::PlaybackEngine engine;
    (void)engine.loadPlan("{\"planId\":\"plan-test\"}");
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
    load_plan_accepts_non_empty_placeholder();
    play_requires_loaded_plan();
    transport_state_transitions_are_deterministic();
    seek_accepts_non_negative_finite_times();
    seek_rejects_negative_and_non_finite_times();
    loading_invalid_plan_resets_state();

    return 0;
}

