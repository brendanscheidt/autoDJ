#include "autodj/dj/dubstep_dj_strategy.hpp"

namespace autodj::dj {

std::string DubstepDJStrategy::strategyId() const {
    return "dubstep-dj";
}

std::vector<std::string> DubstepDJStrategy::supportedGenres() const {
    return {"dubstep"};
}

std::string DubstepDJStrategy::generatePlanPlaceholder() const {
    return R"json({
  "schemaVersion": "autodj.mix-plan.v1",
  "planId": "plan-placeholder-dubstep",
  "strategy": {
    "strategyId": "dubstep-dj",
    "strategyVersion": "0.1.0"
  },
  "tracks": [],
  "transitions": [],
  "commands": [],
  "annotations": [
    {
      "type": "placeholder",
      "message": "DubstepDJStrategy emits an empty MixPlan placeholder in the foundation spec."
    }
  ]
})json";
}

}  // namespace autodj::dj

