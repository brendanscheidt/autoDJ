#pragma once

#include <array>
#include <string_view>

namespace autodj::desktop {

struct WorkbenchText final {
    static constexpr std::string_view AppTitle{"AutoDJ"};
    static constexpr std::string_view RepositoryPanel{"Repository"};
    static constexpr std::string_view AnalysisPanel{"Analysis"};
    static constexpr std::string_view MixPlanPanel{"Mix Plan"};
    static constexpr std::string_view PlaybackPanel{"Playback"};
};

[[nodiscard]] constexpr std::array<std::string_view, 4> workbenchPanelNames() noexcept {
    return {
        WorkbenchText::RepositoryPanel,
        WorkbenchText::AnalysisPanel,
        WorkbenchText::MixPlanPanel,
        WorkbenchText::PlaybackPanel,
    };
}

}  // namespace autodj::desktop

