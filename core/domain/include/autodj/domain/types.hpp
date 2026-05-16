#pragma once

#include <compare>
#include <string>
#include <utility>

namespace autodj::domain {

struct TrackId final {
    std::string value;

    TrackId() = default;
    explicit TrackId(std::string id) : value(std::move(id)) {}

    [[nodiscard]] bool empty() const noexcept { return value.empty(); }

    friend auto operator<=>(const TrackId&, const TrackId&) = default;
};

struct PlanId final {
    std::string value;

    PlanId() = default;
    explicit PlanId(std::string id) : value(std::move(id)) {}

    [[nodiscard]] bool empty() const noexcept { return value.empty(); }

    friend auto operator<=>(const PlanId&, const PlanId&) = default;
};

using TimelineSeconds = double;
using TrackSeconds = double;

}  // namespace autodj::domain

