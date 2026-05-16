#include "WorkbenchText.hpp"

#include <algorithm>
#include <array>
#include <cassert>
#include <string_view>

namespace {

void app_title_is_present() {
    assert(autodj::desktop::WorkbenchText::AppTitle == "AutoDJ");
}

void expected_placeholder_panels_are_present() {
    constexpr auto panels = autodj::desktop::workbenchPanelNames();
    static_assert(panels.size() == 4);

    constexpr std::array<std::string_view, 4> expected{
        "Repository",
        "Analysis",
        "Mix Plan",
        "Playback",
    };

    for (const auto expectedPanel : expected) {
        const auto found = std::find(panels.begin(), panels.end(), expectedPanel);
        assert(found != panels.end());
    }
}

void panel_names_are_not_empty() {
    constexpr auto panels = autodj::desktop::workbenchPanelNames();

    for (const auto panel : panels) {
        assert(!panel.empty());
    }
}

}  // namespace

int main() {
    app_title_is_present();
    expected_placeholder_panels_are_present();
    panel_names_are_not_empty();

    return 0;
}

