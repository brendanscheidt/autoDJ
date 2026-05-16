#include "autodj/dj/dj.hpp"

#include <algorithm>
#include <cassert>
#include <string>
#include <type_traits>

namespace {

void dubstep_strategy_implements_strategy_contract() {
    static_assert(std::is_base_of_v<autodj::dj::IDJStrategy, autodj::dj::DubstepDJStrategy>);

    const autodj::dj::DubstepDJStrategy concrete;
    const autodj::dj::IDJStrategy& strategy = concrete;

    assert(strategy.strategyId() == "dubstep-dj");
}

void dubstep_strategy_reports_dubstep_support() {
    const autodj::dj::DubstepDJStrategy strategy;

    const auto genres = strategy.supportedGenres();
    const auto found = std::find(genres.begin(), genres.end(), "dubstep");

    assert(found != genres.end());
    assert(genres.size() == 1);
}

void placeholder_plan_is_mix_plan_shaped() {
    const autodj::dj::DubstepDJStrategy strategy;

    const std::string plan = strategy.generatePlanPlaceholder();

    assert(plan.find("\"schemaVersion\": \"autodj.mix-plan.v1\"") != std::string::npos);
    assert(plan.find("\"planId\": \"plan-placeholder-dubstep\"") != std::string::npos);
    assert(plan.find("\"strategyId\": \"dubstep-dj\"") != std::string::npos);
    assert(plan.find("\"tracks\": []") != std::string::npos);
    assert(plan.find("\"transitions\": []") != std::string::npos);
    assert(plan.find("\"commands\": []") != std::string::npos);
}

void placeholder_plan_does_not_reference_audio_files() {
    const autodj::dj::DubstepDJStrategy strategy;

    const std::string plan = strategy.generatePlanPlaceholder();

    assert(plan.find("file://") == std::string::npos);
    assert(plan.find(".wav") == std::string::npos);
    assert(plan.find(".mp3") == std::string::npos);
}

}  // namespace

int main() {
    dubstep_strategy_implements_strategy_contract();
    dubstep_strategy_reports_dubstep_support();
    placeholder_plan_is_mix_plan_shaped();
    placeholder_plan_does_not_reference_audio_files();

    return 0;
}

