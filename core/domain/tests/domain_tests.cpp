#include "autodj/domain/domain.hpp"

#include <cassert>
#include <type_traits>

namespace {

void track_ids_store_and_compare_values() {
    const autodj::domain::TrackId first{"track-local-001"};
    const autodj::domain::TrackId same{"track-local-001"};
    const autodj::domain::TrackId other{"track-local-002"};

    assert(first.value == "track-local-001");
    assert(!first.empty());
    assert(first == same);
    assert(first != other);
}

void plan_ids_store_and_compare_values() {
    const autodj::domain::PlanId plan{"plan-seed-001"};
    const autodj::domain::PlanId same{"plan-seed-001"};
    const autodj::domain::PlanId other{"plan-seed-002"};

    assert(plan.value == "plan-seed-001");
    assert(!plan.empty());
    assert(plan == same);
    assert(plan != other);
}

void default_ids_are_empty() {
    const autodj::domain::TrackId track;
    const autodj::domain::PlanId plan;

    assert(track.empty());
    assert(plan.empty());
}

void time_types_are_numeric_seconds() {
    static_assert(std::is_same_v<autodj::domain::TimelineSeconds, double>);
    static_assert(std::is_same_v<autodj::domain::TrackSeconds, double>);

    const autodj::domain::TimelineSeconds timelineStart = 12.5;
    const autodj::domain::TrackSeconds cuePoint = 4.0;

    assert(timelineStart > cuePoint);
}

}  // namespace

int main() {
    track_ids_store_and_compare_values();
    plan_ids_store_and_compare_values();
    default_ids_are_empty();
    time_types_are_numeric_seconds();

    return 0;
}

