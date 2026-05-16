#pragma once

#include <string>
#include <vector>

namespace autodj::dj {

class IDJStrategy {
public:
    virtual ~IDJStrategy() = default;

    [[nodiscard]] virtual std::string strategyId() const = 0;
    [[nodiscard]] virtual std::vector<std::string> supportedGenres() const = 0;
    [[nodiscard]] virtual std::string generatePlanPlaceholder() const = 0;
};

}  // namespace autodj::dj

