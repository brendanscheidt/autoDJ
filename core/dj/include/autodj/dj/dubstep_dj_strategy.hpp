#pragma once

#include "autodj/dj/dj_strategy.hpp"

#include <string>
#include <vector>

namespace autodj::dj {

class DubstepDJStrategy final : public IDJStrategy {
public:
    [[nodiscard]] std::string strategyId() const override;
    [[nodiscard]] std::vector<std::string> supportedGenres() const override;
    [[nodiscard]] std::string generatePlanPlaceholder() const override;
};

}  // namespace autodj::dj

