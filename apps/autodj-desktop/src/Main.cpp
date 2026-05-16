#include "WorkbenchText.hpp"

#include <juce_gui_extra/juce_gui_extra.h>

#include <array>

namespace autodj::desktop {

namespace {

juce::String toJuceString(std::string_view text) {
    return juce::String::fromUTF8(text.data(), static_cast<int>(text.size()));
}

class PlaceholderPanel final : public juce::Component {
public:
    explicit PlaceholderPanel(std::string_view title) {
        titleLabel_.setText(toJuceString(title), juce::dontSendNotification);
        titleLabel_.setJustificationType(juce::Justification::centred);
        titleLabel_.setColour(juce::Label::textColourId, juce::Colours::white);
        titleLabel_.setFont(juce::FontOptions{20.0f, juce::Font::bold});
        addAndMakeVisible(titleLabel_);
    }

    void paint(juce::Graphics& graphics) override {
        const auto bounds = getLocalBounds().toFloat();
        graphics.setColour(juce::Colour{0xff20242b});
        graphics.fillRoundedRectangle(bounds, 8.0f);

        graphics.setColour(juce::Colour{0xff3a414c});
        graphics.drawRoundedRectangle(bounds.reduced(0.5f), 8.0f, 1.0f);
    }

    void resized() override {
        titleLabel_.setBounds(getLocalBounds().reduced(16));
    }

private:
    juce::Label titleLabel_;
};

class MainComponent final : public juce::Component {
public:
    MainComponent()
        : repositoryPanel_{WorkbenchText::RepositoryPanel},
          analysisPanel_{WorkbenchText::AnalysisPanel},
          mixPlanPanel_{WorkbenchText::MixPlanPanel},
          playbackPanel_{WorkbenchText::PlaybackPanel} {
        titleLabel_.setText(toJuceString(WorkbenchText::AppTitle), juce::dontSendNotification);
        titleLabel_.setJustificationType(juce::Justification::centredLeft);
        titleLabel_.setColour(juce::Label::textColourId, juce::Colours::white);
        titleLabel_.setFont(juce::FontOptions{28.0f, juce::Font::bold});

        for (auto* component : panelComponents()) {
            addAndMakeVisible(*component);
        }

        addAndMakeVisible(titleLabel_);
        setSize(920, 620);
    }

    void paint(juce::Graphics& graphics) override {
        graphics.fillAll(juce::Colour{0xff111317});
    }

    void resized() override {
        auto area = getLocalBounds().reduced(24);
        titleLabel_.setBounds(area.removeFromTop(48));
        area.removeFromTop(12);

        constexpr int gap = 12;
        const int columnWidth = (area.getWidth() - gap) / 2;
        const int rowHeight = (area.getHeight() - gap) / 2;

        auto topRow = area.removeFromTop(rowHeight);
        repositoryPanel_.setBounds(topRow.removeFromLeft(columnWidth));
        topRow.removeFromLeft(gap);
        analysisPanel_.setBounds(topRow);

        area.removeFromTop(gap);
        auto bottomRow = area.removeFromTop(rowHeight);
        mixPlanPanel_.setBounds(bottomRow.removeFromLeft(columnWidth));
        bottomRow.removeFromLeft(gap);
        playbackPanel_.setBounds(bottomRow);
    }

private:
    [[nodiscard]] std::array<juce::Component*, 4> panelComponents() noexcept {
        return {&repositoryPanel_, &analysisPanel_, &mixPlanPanel_, &playbackPanel_};
    }

    juce::Label titleLabel_;
    PlaceholderPanel repositoryPanel_;
    PlaceholderPanel analysisPanel_;
    PlaceholderPanel mixPlanPanel_;
    PlaceholderPanel playbackPanel_;
};

class MainWindow final : public juce::DocumentWindow {
public:
    MainWindow()
        : DocumentWindow(toJuceString(WorkbenchText::AppTitle),
                         juce::Colour{0xff111317},
                         DocumentWindow::allButtons) {
        setUsingNativeTitleBar(true);
        setContentOwned(new MainComponent(), true);
        centreWithSize(getWidth(), getHeight());
        setVisible(true);
    }

    void closeButtonPressed() override {
        juce::JUCEApplication::getInstance()->systemRequestedQuit();
    }
};

class AutoDJApplication final : public juce::JUCEApplication {
public:
    const juce::String getApplicationName() override {
        return toJuceString(WorkbenchText::AppTitle);
    }

    const juce::String getApplicationVersion() override {
        return "0.1.0";
    }

    bool moreThanOneInstanceAllowed() override {
        return true;
    }

    void initialise(const juce::String&) override {
        mainWindow_ = std::make_unique<MainWindow>();
    }

    void shutdown() override {
        mainWindow_.reset();
    }

    void systemRequestedQuit() override {
        quit();
    }

    void anotherInstanceStarted(const juce::String&) override {}

private:
    std::unique_ptr<MainWindow> mainWindow_;
};

}  // namespace

}  // namespace autodj::desktop

START_JUCE_APPLICATION(autodj::desktop::AutoDJApplication)

