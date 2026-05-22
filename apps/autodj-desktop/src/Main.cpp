#include "TransitionAuthoringModel.hpp"
#include "WorkbenchText.hpp"

#include <juce_audio_utils/juce_audio_utils.h>
#include <juce_gui_extra/juce_gui_extra.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <functional>
#include <memory>
#include <optional>
#include <vector>

namespace autodj::desktop {

namespace {

const auto background = juce::Colour{0xff0d1014};
const auto panel = juce::Colour{0xff171b21};
const auto panelLine = juce::Colour{0xff343b46};
const auto text = juce::Colour{0xfff2f4f7};
const auto muted = juce::Colour{0xff98a2b3};
const auto accent = juce::Colour{0xff1e90ff};
const auto cueColour = juce::Colour{0xffff405a};
const auto sectionColour = juce::Colour{0x3349b66a};

struct WavePoint final {
    double timeSeconds{0.0};
    double min{0.0};
    double max{0.0};
    double rms{0.0};
    double low{0.0};
    double mid{0.0};
    double high{0.0};
};

struct SectionMarker final {
    std::string id;
    std::string type;
    double startSeconds{0.0};
    double endSeconds{0.0};
};

struct CueMarker final {
    std::string id;
    std::string type;
    double timeSeconds{0.0};
};

struct DeckVisualState final {
    AuthoringDeckState model;
    std::vector<WavePoint> waveform;
    std::vector<SectionMarker> sections;
    std::vector<CueMarker> cues;
    bool analyzedLoaded{false};
    bool waveformLoaded{false};
    bool audioLoaded{false};
    std::string error;
};

[[nodiscard]] juce::String toJuceString(std::string_view value) {
    return juce::String::fromUTF8(value.data(), static_cast<int>(value.size()));
}

[[nodiscard]] std::string toStdString(const juce::String& value) {
    return value.toStdString();
}

[[nodiscard]] const juce::DynamicObject* objectOf(const juce::var& value) {
    return value.getDynamicObject();
}

[[nodiscard]] juce::var propertyOf(const juce::var& value, const char* name) {
    if (const auto* object = objectOf(value)) {
        return object->getProperty(name);
    }
    return {};
}

[[nodiscard]] double numberProperty(const juce::var& value, const char* name, const double fallback = 0.0) {
    const auto property = propertyOf(value, name);
    return property.isDouble() || property.isInt() ? static_cast<double>(property) : fallback;
}

[[nodiscard]] std::string stringProperty(const juce::var& value, const char* name, std::string fallback = {}) {
    const auto property = propertyOf(value, name);
    if (property.isString()) {
        return toStdString(property.toString());
    }
    return fallback;
}

[[nodiscard]] AuthoringDeck deckFromString(const std::string& value) noexcept {
    return value == "b" || value == "B" ? AuthoringDeck::B : AuthoringDeck::A;
}

[[nodiscard]] juce::Colour waveformColour(const WavePoint& point) {
    const auto low = juce::jlimit(0.0, 1.0, point.low);
    const auto mid = juce::jlimit(0.0, 1.0, point.mid);
    const auto high = juce::jlimit(0.0, 1.0, point.high);
    const auto red = static_cast<juce::uint8>(juce::jlimit(35.0, 255.0, 45.0 + low * 205.0 + mid * 75.0));
    const auto green = static_cast<juce::uint8>(juce::jlimit(30.0, 255.0, 35.0 + mid * 185.0 + high * 40.0));
    const auto blue = static_cast<juce::uint8>(juce::jlimit(40.0, 255.0, 55.0 + high * 200.0 + mid * 55.0));
    return juce::Colour{red, green, blue}.withAlpha(0.9f);
}

class ControlSlider final : public juce::Slider {
public:
    std::function<void()> onAddKeyframe;
    std::function<void(double)> onAddHardCut;

    explicit ControlSlider(juce::Slider::SliderStyle style) : juce::Slider(style, juce::Slider::TextBoxBelow) {
        setRange(0.0, 1.0, 0.001);
        setValue(1.0, juce::dontSendNotification);
        setColour(juce::Slider::thumbColourId, accent);
        setColour(juce::Slider::trackColourId, accent.withAlpha(0.65f));
        setColour(juce::Slider::textBoxTextColourId, text);
        setColour(juce::Slider::textBoxBackgroundColourId, juce::Colour{0xff11151b});
    }

    void mouseDown(const juce::MouseEvent& event) override {
        if (event.mods.isPopupMenu()) {
            juce::PopupMenu menu;
            menu.addItem(1, "Add keyframe");
            menu.addItem(2, "Hard cut to current value");
            menu.addItem(3, "Hard cut to 0");
            menu.addItem(4, "Hard cut to 1");
            menu.showMenuAsync(juce::PopupMenu::Options{}, [this](const int result) {
                if (result == 1 && onAddKeyframe) {
                    onAddKeyframe();
                }
                if (result == 2 && onAddHardCut) {
                    onAddHardCut(getValue());
                }
                if (result == 3 && onAddHardCut) {
                    onAddHardCut(0.0);
                }
                if (result == 4 && onAddHardCut) {
                    onAddHardCut(1.0);
                }
            });
            return;
        }
        juce::Slider::mouseDown(event);
    }
};

class TransportButton final : public juce::TextButton {
public:
    std::function<void()> onPrimaryClick;
    std::function<void()> onAddKeyframe;

    void mouseDown(const juce::MouseEvent& event) override {
        if (event.mods.isPopupMenu()) {
            juce::PopupMenu menu;
            menu.addItem(1, "Add automation event");
            menu.showMenuAsync(juce::PopupMenu::Options{}, [this](const int result) {
                if (result == 1 && onAddKeyframe) {
                    onAddKeyframe();
                }
            });
            return;
        }
        juce::TextButton::mouseDown(event);
    }
};

class DeckWaveformComponent final : public juce::Component {
public:
    DeckWaveformComponent(DeckVisualState& state, std::function<void()> changed)
        : state_{state}, onStateChanged_{std::move(changed)} {}

    void paint(juce::Graphics& graphics) override {
        const auto bounds = getLocalBounds().toFloat();
        graphics.fillAll(panel);
        graphics.setColour(panelLine);
        graphics.drawRect(getLocalBounds());

        const auto viewDuration = std::max(0.25, state_.model.zoomSeconds);
        const auto viewStart = state_.model.centerSeconds - viewDuration / 2.0;
        const auto viewEnd = viewStart + viewDuration;
        const auto timeToX = [&](const double seconds) {
            return bounds.getX() + static_cast<float>((seconds - viewStart) / viewDuration) * bounds.getWidth();
        };

        for (const auto& section : state_.sections) {
            if (section.endSeconds < viewStart || section.startSeconds > viewEnd) {
                continue;
            }
            const auto x1 = timeToX(section.startSeconds);
            const auto x2 = timeToX(section.endSeconds);
            graphics.setColour(sectionColour);
            graphics.fillRect(juce::Rectangle<float>{x1, bounds.getY(), std::max(1.0f, x2 - x1), bounds.getHeight()});
            graphics.setColour(juce::Colours::white.withAlpha(0.52f));
            graphics.drawText(toJuceString(section.type), static_cast<int>(x1) + 4, 4, 120, 18, juce::Justification::centredLeft);
        }

        const auto midY = bounds.getCentreY();
        const auto amp = bounds.getHeight() * 0.42f;
        for (const auto& point : state_.waveform) {
            if (point.timeSeconds < viewStart || point.timeSeconds > viewEnd) {
                continue;
            }
            const auto x = timeToX(point.timeSeconds);
            const auto y1 = midY - static_cast<float>(juce::jlimit(-1.0, 1.0, point.max)) * amp;
            const auto y2 = midY - static_cast<float>(juce::jlimit(-1.0, 1.0, point.min)) * amp;
            graphics.setColour(waveformColour(point));
            graphics.drawVerticalLine(static_cast<int>(std::round(x)), y1, y2);
        }

        for (std::size_t index = 0; index < state_.model.beats.size(); ++index) {
            const auto beat = state_.model.beats[index];
            if (beat < viewStart || beat > viewEnd) {
                continue;
            }
            const auto x = timeToX(beat);
            const auto isBar = index % 4 == 0;
            graphics.setColour(isBar ? accent.withAlpha(0.72f) : juce::Colours::white.withAlpha(0.18f));
            graphics.drawVerticalLine(static_cast<int>(std::round(x)), bounds.getY(), bounds.getBottom());
            if (isBar && viewDuration <= 32.0) {
                graphics.setColour(accent.brighter(0.7f));
                graphics.drawText(toJuceString(beatIndexToBarBeat(index)), static_cast<int>(x) + 3, 20, 58, 18, juce::Justification::left);
            }
        }

        for (const auto& cue : state_.cues) {
            if (cue.timeSeconds < viewStart || cue.timeSeconds > viewEnd) {
                continue;
            }
            const auto x = timeToX(cue.timeSeconds);
            graphics.setColour(cueColour);
            graphics.drawVerticalLine(static_cast<int>(std::round(x)), bounds.getY(), bounds.getBottom());
            graphics.drawText(toJuceString(cue.type), static_cast<int>(x) + 4, static_cast<int>(bounds.getBottom()) - 22, 110, 18, juce::Justification::left);
        }

        graphics.setColour(juce::Colours::white);
        graphics.drawVerticalLine(static_cast<int>(std::round(bounds.getCentreX())), bounds.getY(), bounds.getBottom());
        graphics.setColour(text);
        graphics.setFont(juce::FontOptions{18.0f, juce::Font::bold});
        graphics.drawText(
            juce::String(deckName(state_.model.deck)).toUpperCase() + "  "
                + toJuceString(state_.model.title.empty() ? state_.model.trackId : state_.model.title)
                + "  " + toJuceString(barBeatLabelForTime(state_.model.beats, state_.model.centerSeconds)),
            getLocalBounds().reduced(8),
            juce::Justification::topLeft);

        if (!state_.error.empty()) {
            graphics.setColour(juce::Colours::orange);
            graphics.drawText(toJuceString(state_.error), getLocalBounds().reduced(8), juce::Justification::bottomLeft);
        }
    }

    void mouseDown(const juce::MouseEvent& event) override {
        dragging_ = true;
        dragStartX_ = event.position.x;
        dragStartCenter_ = state_.model.centerSeconds;
    }

    void mouseDrag(const juce::MouseEvent& event) override {
        if (!dragging_) {
            return;
        }
        const auto deltaX = event.position.x - dragStartX_;
        const auto secondsPerPixel = state_.model.zoomSeconds / std::max(1, getWidth());
        state_.model.centerSeconds = std::max(0.0, dragStartCenter_ - deltaX * secondsPerPixel);
        if (onStateChanged_) {
            onStateChanged_();
        }
        repaint();
    }

    void mouseUp(const juce::MouseEvent&) override { dragging_ = false; }

    void mouseWheelMove(const juce::MouseEvent&, const juce::MouseWheelDetails& wheel) override {
        const auto factor = wheel.deltaY > 0.0f ? 0.82 : 1.22;
        state_.model.zoomSeconds = juce::jlimit(0.25, 256.0, state_.model.zoomSeconds * factor);
        if (onStateChanged_) {
            onStateChanged_();
        }
        repaint();
    }

private:
    DeckVisualState& state_;
    std::function<void()> onStateChanged_;
    bool dragging_{false};
    float dragStartX_{0.0f};
    double dragStartCenter_{0.0};
};

class AutomationLaneComponent final : public juce::Component {
public:
    AutomationLaneComponent(std::vector<AutomationLane>& lanes, DeckVisualState& deckA, DeckVisualState& deckB)
        : lanes_{lanes}, deckA_{deckA}, deckB_{deckB} {}

    void paint(juce::Graphics& graphics) override {
        graphics.fillAll(juce::Colour{0xff10141a});
        if (lanes_.empty()) {
            graphics.setColour(muted);
            graphics.drawText("Right-click a mixer control and choose Add keyframe.", getLocalBounds(), juce::Justification::centred);
            return;
        }

        const auto laneHeight = std::max(44, getHeight() / static_cast<int>(lanes_.size()));
        for (std::size_t laneIndex = 0; laneIndex < lanes_.size(); ++laneIndex) {
            auto laneBounds = getLocalBounds().removeFromTop(static_cast<int>(laneIndex + 1) * laneHeight)
                                  .removeFromBottom(laneHeight)
                                  .reduced(4);
            const auto& lane = lanes_[laneIndex];
            const auto& deck = lane.deck == AuthoringDeck::A ? deckA_ : deckB_;
            paintLane(graphics, lane, deck, laneBounds, laneIndex);
        }
    }

    void mouseDown(const juce::MouseEvent& event) override {
        selectedLane_.reset();
        selectedFrame_.reset();
        const auto hit = hitTestKeyframe(event.position);
        if (hit.has_value()) {
            selectedLane_ = hit->first;
            selectedFrame_ = hit->second;
        }
    }

    void mouseDrag(const juce::MouseEvent& event) override {
        if (!selectedLane_.has_value() || !selectedFrame_.has_value()) {
            return;
        }
        auto& lane = lanes_[selectedLane_.value()];
        auto& keyframe = lane.keyframes[selectedFrame_.value()];
        const auto& deck = lane.deck == AuthoringDeck::A ? deckA_ : deckB_;
        const auto laneHeight = std::max(44, getHeight() / static_cast<int>(std::max<std::size_t>(1, lanes_.size())));
        const auto laneTop = static_cast<int>(selectedLane_.value()) * laneHeight;
        const auto bounds = plotBoundsForLane(juce::Rectangle<int>{0, laneTop, getWidth(), laneHeight}.reduced(4));
        const auto sourceSeconds = xToTime(deck, bounds, event.position.x);
        keyframe.sourceSeconds = event.mods.isShiftDown() ? sourceSeconds : snapToNearestBeat(deck.model.beats, sourceSeconds);
        if (!isEventControl(lane.control)) {
            const auto normalizedY = 1.0 - (event.position.y - static_cast<float>(bounds.getY())) / std::max(1.0f, static_cast<float>(bounds.getHeight()));
            keyframe.value = juce::jlimit(0.0, 1.0, static_cast<double>(normalizedY));
        }
        repaint();
    }

    void mouseUp(const juce::MouseEvent&) override {
        if (selectedLane_.has_value()) {
            sortLane(lanes_[selectedLane_.value()]);
        }
        selectedLane_.reset();
        selectedFrame_.reset();
        repaint();
    }

private:
    [[nodiscard]] static juce::Rectangle<int> plotBoundsForLane(juce::Rectangle<int> bounds) {
        bounds.removeFromLeft(92);
        return bounds.reduced(4);
    }

    void paintLane(juce::Graphics& graphics,
                   const AutomationLane& lane,
                   const DeckVisualState& deck,
                   juce::Rectangle<int> bounds,
                   std::size_t laneIndex) {
        graphics.setColour(panel);
        graphics.fillRect(bounds);
        graphics.setColour(panelLine);
        graphics.drawRect(bounds);
        graphics.setColour(text);
        graphics.drawText(juce::String(deckName(lane.deck)).toUpperCase() + "." + toJuceString(lane.control),
                          bounds.removeFromLeft(92),
                          juce::Justification::centredLeft);
        const auto plot = bounds.reduced(4);
        const auto viewStart = deck.model.centerSeconds - deck.model.zoomSeconds / 2.0;
        const auto viewEnd = deck.model.centerSeconds + deck.model.zoomSeconds / 2.0;
        for (std::size_t beatIndex = 0; beatIndex < deck.model.beats.size(); ++beatIndex) {
            const auto beat = deck.model.beats[beatIndex];
            if (beat < viewStart || beat > viewEnd) {
                continue;
            }
            const auto x = timeToX(deck, plot, beat);
            const auto isBar = beatIndex % 4 == 0;
            graphics.setColour(isBar ? accent.withAlpha(0.42f) : juce::Colours::white.withAlpha(0.14f));
            graphics.drawVerticalLine(static_cast<int>(x), plot.getY(), plot.getBottom());
            if (isBar && deck.model.zoomSeconds <= 64.0) {
                graphics.setColour(muted);
                graphics.drawText(toJuceString(beatIndexToBarBeat(beatIndex)), static_cast<int>(x) + 2, plot.getY(), 48, 16, juce::Justification::left);
            }
        }
        juce::Path path;
        auto startedPath = false;
        for (const auto& keyframe : lane.keyframes) {
            const auto x = timeToX(deck, plot, keyframe.sourceSeconds);
            const auto keyValue = isEventControl(lane.control) ? 1.0 : keyframe.value;
            const auto y = plot.getBottom() - static_cast<float>(keyValue) * static_cast<float>(plot.getHeight());
            if (startedPath) {
                path.lineTo(x, y);
            } else {
                path.startNewSubPath(x, y);
                startedPath = true;
            }
        }
        graphics.setColour(accent.withAlpha(0.8f));
        graphics.strokePath(path, juce::PathStrokeType{2.0f});
        graphics.setColour(accent);
        for (const auto& keyframe : lane.keyframes) {
            const auto x = timeToX(deck, plot, keyframe.sourceSeconds);
            const auto keyValue = isEventControl(lane.control) ? 1.0 : keyframe.value;
            const auto y = plot.getBottom() - static_cast<float>(keyValue) * static_cast<float>(plot.getHeight());
            graphics.fillEllipse(x - 5.0f, y - 5.0f, 10.0f, 10.0f);
        }
        graphics.setColour(muted);
        graphics.drawText(toJuceString(std::to_string(laneIndex + 1)), plot, juce::Justification::topRight);
    }

    [[nodiscard]] float timeToX(const DeckVisualState& deck, juce::Rectangle<int> bounds, const double seconds) const {
        const auto viewStart = deck.model.centerSeconds - deck.model.zoomSeconds / 2.0;
        return static_cast<float>(bounds.getX()) + static_cast<float>((seconds - viewStart) / deck.model.zoomSeconds) * static_cast<float>(bounds.getWidth());
    }

    [[nodiscard]] double xToTime(const DeckVisualState& deck, juce::Rectangle<int> bounds, const float x) const {
        const auto viewStart = deck.model.centerSeconds - deck.model.zoomSeconds / 2.0;
        return std::max(0.0, viewStart + (x - static_cast<float>(bounds.getX())) / std::max(1.0f, static_cast<float>(bounds.getWidth())) * deck.model.zoomSeconds);
    }

    [[nodiscard]] std::optional<std::pair<std::size_t, std::size_t>> hitTestKeyframe(juce::Point<float> point) const {
        if (lanes_.empty()) {
            return std::nullopt;
        }
        const auto laneHeight = std::max(44, getHeight() / static_cast<int>(lanes_.size()));
        for (std::size_t laneIndex = 0; laneIndex < lanes_.size(); ++laneIndex) {
            const auto laneBounds = juce::Rectangle<int>{0, static_cast<int>(laneIndex) * laneHeight, getWidth(), laneHeight}.reduced(4);
            const auto bounds = plotBoundsForLane(laneBounds);
            const auto& lane = lanes_[laneIndex];
            const auto& deck = lane.deck == AuthoringDeck::A ? deckA_ : deckB_;
            for (std::size_t frameIndex = 0; frameIndex < lane.keyframes.size(); ++frameIndex) {
                const auto& keyframe = lane.keyframes[frameIndex];
                const auto x = timeToX(deck, bounds, keyframe.sourceSeconds);
                const auto keyValue = isEventControl(lane.control) ? 1.0 : keyframe.value;
                const auto y = bounds.getBottom() - static_cast<float>(keyValue) * static_cast<float>(bounds.getHeight());
                if (std::abs(point.x - x) <= 18.0f && std::abs(point.y - y) <= 18.0f) {
                    return std::pair{laneIndex, frameIndex};
                }
            }
        }
        return std::nullopt;
    }

    std::vector<AutomationLane>& lanes_;
    DeckVisualState& deckA_;
    DeckVisualState& deckB_;
    std::optional<std::size_t> selectedLane_;
    std::optional<std::size_t> selectedFrame_;
};

class MainComponent final : public juce::AudioAppComponent, private juce::Timer {
public:
    MainComponent()
        : waveformA_{deckA_, [this] { repaintAll(); }},
          waveformB_{deckB_, [this] { repaintAll(); }},
          lanes_{automationLanes_, deckA_, deckB_},
          volumeA_{juce::Slider::LinearVertical},
          volumeB_{juce::Slider::LinearVertical},
          lowA_{juce::Slider::RotaryHorizontalVerticalDrag},
          midA_{juce::Slider::RotaryHorizontalVerticalDrag},
          highA_{juce::Slider::RotaryHorizontalVerticalDrag},
          reverbA_{juce::Slider::RotaryHorizontalVerticalDrag},
          lowB_{juce::Slider::RotaryHorizontalVerticalDrag},
          midB_{juce::Slider::RotaryHorizontalVerticalDrag},
          highB_{juce::Slider::RotaryHorizontalVerticalDrag},
          reverbB_{juce::Slider::RotaryHorizontalVerticalDrag} {
        formatManager_.registerBasicFormats();
        deckA_.model.deck = AuthoringDeck::A;
        deckB_.model.deck = AuthoringDeck::B;
        deckA_.model.zoomSeconds = 16.0;
        deckB_.model.zoomSeconds = 16.0;

        configureButtons();
        configureTransportButtons();
        configureSliders();
        addAndMakeVisible(waveformA_);
        addAndMakeVisible(waveformB_);
        addAndMakeVisible(lanes_);
        addAndMakeVisible(status_);
        setSize(1500, 920);
        setAudioChannels(0, 2);
        startTimerHz(30);
    }

    ~MainComponent() override {
        shutdownAudio();
        deckAPlayer_.transport.setSource(nullptr);
        deckBPlayer_.transport.setSource(nullptr);
    }

    void prepareToPlay(int samplesPerBlockExpected, double sampleRate) override {
        sampleRate_ = sampleRate;
        deckAPlayer_.transport.prepareToPlay(samplesPerBlockExpected, sampleRate);
        deckBPlayer_.transport.prepareToPlay(samplesPerBlockExpected, sampleRate);
        deckAPlayer_.reverb.setSampleRate(sampleRate);
        deckBPlayer_.reverb.setSampleRate(sampleRate);
        temp_.setSize(2, samplesPerBlockExpected);
    }

    void getNextAudioBlock(const juce::AudioSourceChannelInfo& bufferToFill) override {
        bufferToFill.clearActiveBufferRegion();
        renderDeck(deckAPlayer_, deckA_, bufferToFill);
        renderDeck(deckBPlayer_, deckB_, bufferToFill);
    }

    void releaseResources() override {
        deckAPlayer_.transport.releaseResources();
        deckBPlayer_.transport.releaseResources();
    }

    void paint(juce::Graphics& graphics) override {
        graphics.fillAll(background);
        graphics.setColour(text);
        graphics.setFont(juce::FontOptions{24.0f, juce::Font::bold});
        graphics.drawText("Transition Recipe Authoring Workbench", 18, 10, getWidth() - 36, 34, juce::Justification::centredLeft);
    }

    void resized() override {
        auto area = getLocalBounds().reduced(18);
        area.removeFromTop(40);
        auto top = area.removeFromTop(86);
        auto x = top.getX();
        auto y = top.getY();
        constexpr auto controlWidth = 124;
        constexpr auto controlHeight = 34;
        constexpr auto gap = 4;
        for (auto* button : topButtons_) {
            if (x + controlWidth > top.getRight()) {
                x = top.getX();
                y += controlHeight + gap;
            }
            button->setBounds(x, y, controlWidth, controlHeight);
            x += controlWidth + gap;
        }
        area.removeFromTop(8);

        auto waveArea = area.removeFromTop(std::max(260, area.getHeight() / 3));
        waveformA_.setBounds(waveArea.removeFromTop(waveArea.getHeight() / 2).reduced(0, 2));
        waveformB_.setBounds(waveArea.reduced(0, 2));
        area.removeFromTop(8);

        auto mixer = area.removeFromTop(188);
        auto sharedTransport = mixer.removeFromTop(34);
        playBoth_.setBounds(sharedTransport.withSizeKeepingCentre(140, 30));
        auto mixerA = mixer.removeFromLeft(mixer.getWidth() / 2).reduced(4);
        auto mixerB = mixer.reduced(4);
        layoutMixer(mixerA, playA_, stopA_, volumeA_, lowA_, midA_, highA_, reverbA_);
        layoutMixer(mixerB, playB_, stopB_, volumeB_, lowB_, midB_, highB_, reverbB_);
        area.removeFromTop(8);

        lanes_.setBounds(area.removeFromTop(std::max(170, area.getHeight() - 48)));
        status_.setBounds(area);
    }

private:
    struct DeckPlayer final {
        juce::AudioTransportSource transport;
        std::unique_ptr<juce::AudioFormatReaderSource> readerSource;
        juce::Reverb reverb;
        bool previewStarted{false};
        double lowState[2]{0.0, 0.0};
        double highLowState[2]{0.0, 0.0};
    };

    void configureButtons() {
        struct ButtonConfig final {
            juce::TextButton* button;
            const char* text;
            std::function<void()> action;
        };
        const std::array<ButtonConfig, 12> configs{{
            {&loadAudioA_, "Load A Audio", [this] { loadAudio(deckA_, deckAPlayer_); }},
            {&loadAnalyzedA_, "Load A Analysis", [this] { loadAnalyzed(deckA_); }},
            {&loadWaveA_, "Load A Wave", [this] { loadWaveform(deckA_); }},
            {&loadAudioB_, "Load B Audio", [this] { loadAudio(deckB_, deckBPlayer_); }},
            {&loadAnalyzedB_, "Load B Analysis", [this] { loadAnalyzed(deckB_); }},
            {&loadWaveB_, "Load B Wave", [this] { loadWaveform(deckB_); }},
            {&anchorA_, "Anchor A", [this] { tagAnchor(deckA_, selectedAnchorA_.getText().toStdString()); }},
            {&anchorB_, "Anchor B", [this] { tagAnchor(deckB_, selectedAnchorB_.getText().toStdString()); }},
            {&loadSession_, "Load Session", [this] { loadSession(); }},
            {&exportSession_, "Save Session", [this] { exportText("Save session", "transition-authoring-session.json", writeAuthoringSessionJson(makeSession())); }},
            {&exportPlan_, "Export MixPlan", [this] { exportText("Save MixPlan", "mix-plan.json", writeSpecificMixPlanJson(makeSession())); }},
            {&exportRecipe_, "Export Recipe", [this] { exportText("Save recipe", "transition-recipe.json", writeTransitionRecipeJson(makeSession())); }},
        }};

        selectedAnchorA_.addItem("a.buildStart", 1);
        selectedAnchorA_.addItem("a.dropStart", 2);
        selectedAnchorA_.addItem("a.cutTime", 3);
        selectedAnchorA_.addItem("a.dropEnd", 4);
        selectedAnchorA_.setSelectedId(2);
        selectedAnchorB_.addItem("b.playStart", 1);
        selectedAnchorB_.addItem("b.dropStart", 2);
        selectedAnchorB_.addItem("b.firstBeat", 3);
        selectedAnchorB_.setSelectedId(2);
        addAndMakeVisible(selectedAnchorA_);
        addAndMakeVisible(selectedAnchorB_);

        for (const auto& config : configs) {
            config.button->setButtonText(config.text);
            config.button->onClick = config.action;
            config.button->setColour(juce::TextButton::buttonColourId, panel);
            config.button->setColour(juce::TextButton::textColourOffId, text);
            addAndMakeVisible(*config.button);
            topButtons_.push_back(config.button);
        }
        topButtons_.insert(topButtons_.begin() + 6, &selectedAnchorA_);
        topButtons_.insert(topButtons_.begin() + 8, &selectedAnchorB_);
    }

    void configureTransportButtons() {
        const std::array<std::pair<TransportButton*, const char*>, 5> buttons{{
            {&playA_, "Play A"},
            {&stopA_, "Stop A"},
            {&playB_, "Play B"},
            {&stopB_, "Stop B"},
            {&playBoth_, "Play Both"},
        }};
        for (auto [button, label] : buttons) {
            button->setButtonText(label);
            button->setColour(juce::TextButton::buttonColourId, panel);
            button->setColour(juce::TextButton::textColourOffId, text);
            addAndMakeVisible(*button);
        }
        playA_.onClick = [this] { globalPreviewActive_ = false; playDeck(deckA_, deckAPlayer_); };
        stopA_.onClick = [this] { stopDeck(deckAPlayer_); };
        playB_.onClick = [this] { globalPreviewActive_ = false; playDeck(deckB_, deckBPlayer_); };
        stopB_.onClick = [this] { stopDeck(deckBPlayer_); };
        playBoth_.onClick = [this] { startGlobalPreview(); };
        playA_.onAddKeyframe = [this] { addEventKeyframe(deckA_, "play"); };
        stopA_.onAddKeyframe = [this] { addEventKeyframe(deckA_, "stop"); };
        playB_.onAddKeyframe = [this] { addEventKeyframe(deckB_, "play"); };
        stopB_.onAddKeyframe = [this] { addEventKeyframe(deckB_, "stop"); };
        playBoth_.onAddKeyframe = [this] {
            addEventKeyframe(deckA_, "play");
            addEventKeyframe(deckB_, "play");
        };
    }

    void configureSliders() {
        for (auto* slider : {&volumeA_, &volumeB_, &lowA_, &midA_, &highA_, &reverbA_, &lowB_, &midB_, &highB_, &reverbB_}) {
            addAndMakeVisible(*slider);
        }
        volumeA_.setValue(1.0);
        volumeB_.setValue(1.0);
        lowA_.setValue(1.0);
        midA_.setValue(1.0);
        highA_.setValue(1.0);
        lowB_.setValue(1.0);
        midB_.setValue(1.0);
        highB_.setValue(1.0);
        reverbA_.setValue(0.0);
        reverbB_.setValue(0.0);

        volumeA_.onAddKeyframe = [this] { addKeyframe(deckA_, "volume", volumeA_.getValue()); };
        volumeB_.onAddKeyframe = [this] { addKeyframe(deckB_, "volume", volumeB_.getValue()); };
        lowA_.onAddKeyframe = [this] { addKeyframe(deckA_, "eqLow", lowA_.getValue()); };
        midA_.onAddKeyframe = [this] { addKeyframe(deckA_, "eqMid", midA_.getValue()); };
        highA_.onAddKeyframe = [this] { addKeyframe(deckA_, "eqHigh", highA_.getValue()); };
        reverbA_.onAddKeyframe = [this] { addKeyframe(deckA_, "reverbWet", reverbA_.getValue()); };
        lowB_.onAddKeyframe = [this] { addKeyframe(deckB_, "eqLow", lowB_.getValue()); };
        midB_.onAddKeyframe = [this] { addKeyframe(deckB_, "eqMid", midB_.getValue()); };
        highB_.onAddKeyframe = [this] { addKeyframe(deckB_, "eqHigh", highB_.getValue()); };
        reverbB_.onAddKeyframe = [this] { addKeyframe(deckB_, "reverbWet", reverbB_.getValue()); };
        volumeA_.onAddHardCut = [this](double value) { addHardCut(deckA_, "volume", volumeA_.getValue(), value); };
        volumeB_.onAddHardCut = [this](double value) { addHardCut(deckB_, "volume", volumeB_.getValue(), value); };
        lowA_.onAddHardCut = [this](double value) { addHardCut(deckA_, "eqLow", lowA_.getValue(), value); };
        midA_.onAddHardCut = [this](double value) { addHardCut(deckA_, "eqMid", midA_.getValue(), value); };
        highA_.onAddHardCut = [this](double value) { addHardCut(deckA_, "eqHigh", highA_.getValue(), value); };
        reverbA_.onAddHardCut = [this](double value) { addHardCut(deckA_, "reverbWet", reverbA_.getValue(), value); };
        lowB_.onAddHardCut = [this](double value) { addHardCut(deckB_, "eqLow", lowB_.getValue(), value); };
        midB_.onAddHardCut = [this](double value) { addHardCut(deckB_, "eqMid", midB_.getValue(), value); };
        highB_.onAddHardCut = [this](double value) { addHardCut(deckB_, "eqHigh", highB_.getValue(), value); };
        reverbB_.onAddHardCut = [this](double value) { addHardCut(deckB_, "reverbWet", reverbB_.getValue(), value); };
    }

    void layoutMixer(juce::Rectangle<int> area,
                     TransportButton& play,
                     TransportButton& stop,
                     ControlSlider& volume,
                     ControlSlider& low,
                     ControlSlider& mid,
                     ControlSlider& high,
                     ControlSlider& reverb) {
        auto transport = area.removeFromTop(34);
        play.setBounds(transport.removeFromLeft(92).reduced(4));
        stop.setBounds(transport.removeFromLeft(92).reduced(4));
        volume.setBounds(area.removeFromLeft(70).reduced(6));
        low.setBounds(area.removeFromLeft(96).reduced(6));
        mid.setBounds(area.removeFromLeft(96).reduced(6));
        high.setBounds(area.removeFromLeft(96).reduced(6));
        reverb.setBounds(area.removeFromLeft(112).reduced(6));
    }

    void chooseFileToOpen(const juce::String& title, const juce::String& wildcard, std::function<void(juce::File)> onChosen) {
        fileChooser_ = std::make_unique<juce::FileChooser>(title, juce::File{}, wildcard);
        fileChooser_->launchAsync(juce::FileBrowserComponent::openMode | juce::FileBrowserComponent::canSelectFiles,
                                  [this, onChosen = std::move(onChosen)](const juce::FileChooser& chooser) {
                                      const auto file = chooser.getResult();
                                      if (file.existsAsFile()) {
                                          onChosen(file);
                                      }
                                  });
    }

    void chooseFileToSave(const juce::String& title, const juce::String& filename, std::function<void(juce::File)> onChosen) {
        const auto defaultFile = juce::File::getSpecialLocation(juce::File::userDesktopDirectory).getChildFile(filename);
        fileChooser_ = std::make_unique<juce::FileChooser>(title, defaultFile);
        fileChooser_->launchAsync(juce::FileBrowserComponent::saveMode | juce::FileBrowserComponent::canSelectFiles
                                      | juce::FileBrowserComponent::warnAboutOverwriting,
                                  [this, onChosen = std::move(onChosen)](const juce::FileChooser& chooser) {
                                      const auto file = chooser.getResult();
                                      if (file != juce::File{}) {
                                          onChosen(file);
                                      }
                                  });
    }

    void loadAudio(DeckVisualState& deck, DeckPlayer& player) {
        auto* deckPtr = &deck;
        auto* playerPtr = &player;
        chooseFileToOpen("Load deck audio", "*.wav;*.mp3;*.flac;*.aiff;*.aif", [this, deckPtr, playerPtr](const juce::File file) {
            loadAudioFile(*deckPtr, *playerPtr, file);
        });
    }

    bool loadAudioFile(DeckVisualState& deck, DeckPlayer& player, const juce::File& file, const bool clearAuthoring = true) {
        std::unique_ptr<juce::AudioFormatReader> reader{formatManager_.createReaderFor(file)};
        if (!reader) {
            deck.error = "Could not read audio: " + toStdString(file.getFullPathName());
            repaintAll();
            return false;
        }
        const auto sourceSampleRate = reader->sampleRate;
        auto source = std::make_unique<juce::AudioFormatReaderSource>(reader.release(), true);
        player.transport.setSource(source.get(), 0, nullptr, sourceSampleRate);
        player.readerSource = std::move(source);
        deck.model.audioPath = toStdString(file.getFullPathName());
        deck.audioLoaded = true;
        deck.error.clear();
        if (clearAuthoring) {
            clearAuthoringForDeck(deck.model.deck);
        }
        repaintAll();
        return true;
    }

    void loadAnalyzed(DeckVisualState& deck) {
        auto* deckPtr = &deck;
        chooseFileToOpen("Load analyzed-track.json", "*.json", [this, deckPtr](const juce::File file) {
            loadAnalyzedFile(*deckPtr, file);
        });
    }

    bool loadAnalyzedFile(DeckVisualState& deck, const juce::File& file, const bool clearAuthoring = true) {
        const auto parsed = juce::JSON::parse(file);
        if (!objectOf(parsed)) {
            deck.error = "Invalid analyzed-track JSON";
            repaintAll();
            return false;
        }
        deck.model.analyzedTrackPath = toStdString(file.getFullPathName());
        deck.model.trackId = stringProperty(parsed, "trackId", deck.model.trackId);
        deck.model.title = stringProperty(parsed, "title", deck.model.trackId);
        deck.model.durationSeconds = numberProperty(parsed, "durationSeconds", deck.model.durationSeconds);
        const auto tempo = propertyOf(parsed, "tempo");
        deck.model.normalizedBpm = numberProperty(tempo, "normalizedBpm", numberProperty(tempo, "bpm", deck.model.normalizedBpm));
        deck.model.beats.clear();
        const auto beatGrid = propertyOf(parsed, "beatGrid");
        if (const auto* beats = propertyOf(beatGrid, "beats").getArray()) {
            for (const auto& beat : *beats) {
                deck.model.beats.push_back(numberProperty(beat, "timeSeconds", 0.0));
            }
        }
        deck.sections.clear();
        if (const auto* sections = propertyOf(parsed, "sections").getArray()) {
            for (const auto& section : *sections) {
                deck.sections.push_back(SectionMarker{
                    .id = stringProperty(section, "id"),
                    .type = stringProperty(section, "type"),
                    .startSeconds = numberProperty(section, "startSeconds"),
                    .endSeconds = numberProperty(section, "endSeconds", numberProperty(section, "startSeconds")),
                });
            }
        }
        deck.cues.clear();
        if (const auto* cues = propertyOf(parsed, "cuePoints").getArray()) {
            for (const auto& cue : *cues) {
                deck.cues.push_back(CueMarker{
                    .id = stringProperty(cue, "id"),
                    .type = stringProperty(cue, "type"),
                    .timeSeconds = numberProperty(cue, "timeSeconds"),
                });
            }
        }
        deck.analyzedLoaded = true;
        deck.error = deck.model.beats.empty() ? "Analyzed track has no beatgrid beats" : "";
        if (clearAuthoring) {
            clearAuthoringForDeck(deck.model.deck);
        }
        repaintAll();
        return deck.analyzedLoaded && !deck.model.beats.empty();
    }

    void loadWaveform(DeckVisualState& deck) {
        auto* deckPtr = &deck;
        chooseFileToOpen("Load debug-waveform.json", "*.json", [this, deckPtr](const juce::File file) {
            loadWaveformFile(*deckPtr, file);
        });
    }

    bool loadWaveformFile(DeckVisualState& deck, const juce::File& file, const bool clearAuthoring = true) {
        const auto parsed = juce::JSON::parse(file);
        if (!objectOf(parsed)) {
            deck.error = "Invalid debug-waveform JSON";
            repaintAll();
            return false;
        }
        deck.waveform.clear();
        if (const auto* points = propertyOf(parsed, "points").getArray()) {
            for (const auto& point : *points) {
                deck.waveform.push_back(WavePoint{
                    .timeSeconds = numberProperty(point, "timeSeconds"),
                    .min = numberProperty(point, "min"),
                    .max = numberProperty(point, "max"),
                    .rms = numberProperty(point, "rms"),
                    .low = numberProperty(point, "low"),
                    .mid = numberProperty(point, "mid"),
                    .high = numberProperty(point, "high"),
                });
            }
        }
        deck.model.debugWaveformPath = toStdString(file.getFullPathName());
        deck.waveformLoaded = !deck.waveform.empty();
        deck.error = deck.waveformLoaded ? "" : "Debug waveform has no points";
        if (clearAuthoring) {
            clearAuthoringForDeck(deck.model.deck);
        }
        repaintAll();
        return deck.waveformLoaded;
    }

    void loadSession() {
        chooseFileToOpen("Load transition authoring session", "*.json", [this](const juce::File file) {
            const auto parsed = juce::JSON::parse(file);
            if (!objectOf(parsed)) {
                setStatus("Invalid authoring session JSON");
                return;
            }

            sessionId_ = stringProperty(parsed, "sessionId", sessionId_);
            transitionFamily_ = stringProperty(parsed, "transitionFamily", transitionFamily_);
            notes_ = stringProperty(parsed, "notes", notes_);
            anchors_.clear();
            automationLanes_.clear();

            if (const auto* decks = propertyOf(parsed, "decks").getArray()) {
                for (const auto& deckJson : *decks) {
                    const auto deckId = deckFromString(stringProperty(deckJson, "deck"));
                    auto& deck = deckId == AuthoringDeck::A ? deckA_ : deckB_;
                    auto& player = deckId == AuthoringDeck::A ? deckAPlayer_ : deckBPlayer_;
                    deck.model.deck = deckId;
                    deck.model.trackId = stringProperty(deckJson, "trackId", deck.model.trackId);
                    deck.model.centerSeconds = numberProperty(deckJson, "centerSeconds", deck.model.centerSeconds);
                    deck.model.previewStartDelaySeconds = numberProperty(deckJson, "previewStartDelaySeconds", deck.model.previewStartDelaySeconds);
                    deck.model.zoomSeconds = numberProperty(deckJson, "zoomSeconds", deck.model.zoomSeconds);

                    const auto audioPath = stringProperty(deckJson, "audioPath");
                    const auto analyzedPath = stringProperty(deckJson, "analyzedTrackPath");
                    const auto waveformPath = stringProperty(deckJson, "debugWaveformPath");
                    if (!audioPath.empty()) {
                        loadAudioFile(deck, player, juce::File{toJuceString(audioPath)}, false);
                    }
                    if (!analyzedPath.empty()) {
                        loadAnalyzedFile(deck, juce::File{toJuceString(analyzedPath)}, false);
                    }
                    if (!waveformPath.empty()) {
                        loadWaveformFile(deck, juce::File{toJuceString(waveformPath)}, false);
                    }
                    deck.model.centerSeconds = numberProperty(deckJson, "centerSeconds", deck.model.centerSeconds);
                    deck.model.previewStartDelaySeconds = numberProperty(deckJson, "previewStartDelaySeconds", deck.model.previewStartDelaySeconds);
                    deck.model.zoomSeconds = numberProperty(deckJson, "zoomSeconds", deck.model.zoomSeconds);
                }
            }

            if (const auto* anchors = propertyOf(parsed, "anchors").getArray()) {
                for (const auto& anchorJson : *anchors) {
                    anchors_.push_back(AuthoringAnchor{
                        .name = stringProperty(anchorJson, "name"),
                        .deck = deckFromString(stringProperty(anchorJson, "deck")),
                        .sourceSeconds = numberProperty(anchorJson, "sourceSeconds"),
                        .semanticRef = stringProperty(anchorJson, "semanticRef"),
                    });
                }
            }

            if (const auto* lanes = propertyOf(parsed, "lanes").getArray()) {
                for (const auto& laneJson : *lanes) {
                    AutomationLane lane;
                    lane.deck = deckFromString(stringProperty(laneJson, "deck"));
                    lane.control = stringProperty(laneJson, "control", "volume");
                    if (const auto* keyframes = propertyOf(laneJson, "keyframes").getArray()) {
                        for (const auto& keyframeJson : *keyframes) {
                            lane.keyframes.push_back(AuthoringKeyframe{
                                .deck = lane.deck,
                                .control = lane.control,
                                .sourceSeconds = numberProperty(keyframeJson, "sourceSeconds"),
                                .value = juce::jlimit(0.0, 1.0, numberProperty(keyframeJson, "value")),
                                .interpolation = stringProperty(keyframeJson, "interpolation", "linear"),
                            });
                        }
                    }
                    sortLane(lane);
                    automationLanes_.push_back(std::move(lane));
                }
            }

            setStatus("Loaded session " + file.getFileName());
            repaintAll();
        });
    }

    void clearAuthoringForDeck(const AuthoringDeck deck) {
        automationLanes_.erase(std::remove_if(automationLanes_.begin(), automationLanes_.end(), [&](const auto& lane) {
                                   return lane.deck == deck;
                               }),
                               automationLanes_.end());
        anchors_.erase(std::remove_if(anchors_.begin(), anchors_.end(), [&](const auto& anchor) {
                           return anchor.deck == deck;
                       }),
                       anchors_.end());
        lanes_.repaint();
    }

    void playDeck(DeckVisualState& deck, DeckPlayer& player) {
        if (!deck.audioLoaded) {
            deck.error = "Load audio before playback";
            repaintAll();
            return;
        }
        player.transport.setPosition(deck.model.centerSeconds);
        player.transport.start();
    }

    void stopDeck(DeckPlayer& player) {
        player.transport.stop();
        if (!deckAPlayer_.transport.isPlaying() && !deckBPlayer_.transport.isPlaying()) {
            globalPreviewActive_ = false;
        }
    }

    void startGlobalPreview() {
        globalPreviewActive_ = true;
        globalPreviewElapsedSeconds_ = 0.0;
        lastTimerMilliseconds_ = juce::Time::getMillisecondCounterHiRes();
        deckAPlayer_.previewStarted = false;
        deckBPlayer_.previewStarted = false;
        if (!hasLane(deckA_.model.deck, "play") && deckA_.model.previewStartDelaySeconds <= 0.0) {
            playDeck(deckA_, deckAPlayer_);
            deckAPlayer_.previewStarted = true;
        } else {
            deckAPlayer_.transport.stop();
        }
        if (!hasLane(deckB_.model.deck, "play") && deckB_.model.previewStartDelaySeconds <= 0.0) {
            playDeck(deckB_, deckBPlayer_);
            deckBPlayer_.previewStarted = true;
        } else {
            deckBPlayer_.transport.stop();
        }
    }

    void tagAnchor(const DeckVisualState& deck, std::string name) {
        auto session = makeSession();
        (void)session;
        anchors_.erase(std::remove_if(anchors_.begin(), anchors_.end(), [&](const auto& anchor) {
                           return anchor.name == name;
                       }),
                       anchors_.end());
        anchors_.push_back(AuthoringAnchor{
            .name = std::move(name),
            .deck = deck.model.deck,
            .sourceSeconds = snapToNearestBeat(deck.model.beats, deck.model.centerSeconds),
            .semanticRef = "",
        });
        setStatus("Tagged anchor at " + juce::String(deckName(deck.model.deck)).toUpperCase() + " "
                  + toJuceString(barBeatLabelForTime(deck.model.beats, deck.model.centerSeconds)));
    }

    void addKeyframe(const DeckVisualState& deck, std::string control, const double value) {
        auto& lane = laneFor(deck.model.deck, control);
        const auto sourceSeconds = snapToNearestBeat(deck.model.beats, deck.model.centerSeconds);
        lane.keyframes.push_back(AuthoringKeyframe{
            .deck = deck.model.deck,
            .control = std::move(control),
            .sourceSeconds = sourceSeconds,
            .value = juce::jlimit(0.0, 1.0, value),
            .interpolation = "smoothstep",
        });
        sortLane(lane);
        lanes_.repaint();
    }

    void addHardCut(const DeckVisualState& deck, std::string control, const double fromValue, const double toValue) {
        auto& lane = laneFor(deck.model.deck, control);
        const auto sourceSeconds = snapToNearestBeat(deck.model.beats, deck.model.centerSeconds);
        lane.keyframes.push_back(AuthoringKeyframe{
            .deck = deck.model.deck,
            .control = control,
            .sourceSeconds = sourceSeconds,
            .value = juce::jlimit(0.0, 1.0, fromValue),
            .interpolation = "hold",
        });
        lane.keyframes.push_back(AuthoringKeyframe{
            .deck = deck.model.deck,
            .control = std::move(control),
            .sourceSeconds = sourceSeconds,
            .value = juce::jlimit(0.0, 1.0, toValue),
            .interpolation = "hold",
        });
        sortLane(lane);
        lanes_.repaint();
    }

    void addEventKeyframe(const DeckVisualState& deck, std::string control) {
        auto& lane = laneFor(deck.model.deck, control);
        const auto sourceSeconds = snapToNearestBeat(deck.model.beats, deck.model.centerSeconds);
        lane.keyframes.push_back(AuthoringKeyframe{
            .deck = deck.model.deck,
            .control = std::move(control),
            .sourceSeconds = sourceSeconds,
            .value = 1.0,
            .interpolation = "hold",
        });
        sortLane(lane);
        lanes_.repaint();
    }

    AutomationLane& laneFor(AuthoringDeck deck, const std::string& control) {
        for (auto& lane : automationLanes_) {
            if (lane.deck == deck && lane.control == control) {
                return lane;
            }
        }
        automationLanes_.push_back(AutomationLane{.deck = deck, .control = control});
        return automationLanes_.back();
    }

    [[nodiscard]] bool hasLane(const AuthoringDeck deck, std::string_view control) const {
        return std::any_of(automationLanes_.begin(), automationLanes_.end(), [&](const auto& lane) {
            return lane.deck == deck && lane.control == control && !lane.keyframes.empty();
        });
    }

    [[nodiscard]] bool crossedEvent(const AuthoringDeck deck,
                                    std::string_view control,
                                    const double previousSeconds,
                                    const double currentSeconds) const {
        constexpr auto epsilon = 0.000001;
        for (const auto& lane : automationLanes_) {
            if (lane.deck != deck || lane.control != control) {
                continue;
            }
            for (const auto& keyframe : lane.keyframes) {
                if (keyframe.sourceSeconds > previousSeconds + epsilon
                    && keyframe.sourceSeconds <= currentSeconds + epsilon) {
                    return true;
                }
                if (std::abs(keyframe.sourceSeconds - currentSeconds) <= epsilon) {
                    return true;
                }
            }
        }
        return false;
    }

    AuthoringSession makeSession() const {
        AuthoringSession session;
        session.sessionId = sessionId_;
        session.transitionFamily = transitionFamily_;
        session.notes = notes_;
        session.deckA = deckA_.model;
        session.deckB = deckB_.model;
        session.anchors = anchors_;
        session.lanes = automationLanes_;
        return session;
    }

    void exportText(const juce::String& title, const juce::String& filename, const std::string& content) {
        chooseFileToSave(title, filename, [this, content](const juce::File file) {
        if (file.replaceWithText(toJuceString(content))) {
            setStatus("Wrote " + file.getFullPathName());
        } else {
            setStatus("Could not write " + file.getFullPathName());
        }
        });
    }

    [[nodiscard]] double laneValue(AuthoringDeck deck, std::string_view control, const double sourceSeconds, const double fallback) const {
        for (const auto& lane : automationLanes_) {
            if (lane.deck != deck || lane.control != control || lane.keyframes.empty()) {
                continue;
            }
            constexpr auto epsilon = 0.000001;
            if (sourceSeconds < lane.keyframes.front().sourceSeconds - epsilon) {
                return fallback;
            }
            if (std::abs(sourceSeconds - lane.keyframes.front().sourceSeconds) <= epsilon) {
                auto value = lane.keyframes.front().value;
                for (std::size_t index = 1; index < lane.keyframes.size(); ++index) {
                    if (std::abs(lane.keyframes[index].sourceSeconds - lane.keyframes.front().sourceSeconds) > epsilon) {
                        break;
                    }
                    value = lane.keyframes[index].value;
                }
                return value;
            }
            for (std::size_t index = 1; index < lane.keyframes.size(); ++index) {
                const auto& previous = lane.keyframes[index - 1];
                const auto& next = lane.keyframes[index];
                if (std::abs(sourceSeconds - next.sourceSeconds) <= epsilon) {
                    auto value = next.value;
                    for (std::size_t duplicate = index + 1; duplicate < lane.keyframes.size(); ++duplicate) {
                        if (std::abs(lane.keyframes[duplicate].sourceSeconds - next.sourceSeconds) > epsilon) {
                            break;
                        }
                        value = lane.keyframes[duplicate].value;
                    }
                    return value;
                }
                if (sourceSeconds < next.sourceSeconds) {
                    const auto span = std::max(0.000001, next.sourceSeconds - previous.sourceSeconds);
                    auto progress = juce::jlimit(0.0, 1.0, (sourceSeconds - previous.sourceSeconds) / span);
                    if (next.interpolation == "hold") {
                        return previous.value;
                    }
                    if (next.interpolation == "smoothstep") {
                        progress = progress * progress * (3.0 - 2.0 * progress);
                    } else if (next.interpolation == "exponential") {
                        progress *= progress;
                    }
                    return previous.value * (1.0 - progress) + next.value * progress;
                }
            }
            return lane.keyframes.back().value;
        }
        return fallback;
    }

    void renderDeck(DeckPlayer& player, const DeckVisualState& deck, const juce::AudioSourceChannelInfo& output) {
        if (!player.transport.isPlaying()) {
            return;
        }
        temp_.setSize(output.buffer->getNumChannels(), output.numSamples, false, false, true);
        temp_.clear();
        juce::AudioSourceChannelInfo info{&temp_, 0, output.numSamples};
        player.transport.getNextAudioBlock(info);

        const auto sourceSeconds = player.transport.getCurrentPosition();
        const auto volume = laneValue(deck.model.deck, "volume", sourceSeconds, deck.model.deck == AuthoringDeck::A ? volumeA_.getValue() : volumeB_.getValue());
        const auto eqLow = laneValue(deck.model.deck, "eqLow", sourceSeconds, deck.model.deck == AuthoringDeck::A ? lowA_.getValue() : lowB_.getValue());
        const auto eqMid = laneValue(deck.model.deck, "eqMid", sourceSeconds, deck.model.deck == AuthoringDeck::A ? midA_.getValue() : midB_.getValue());
        const auto eqHigh = laneValue(deck.model.deck, "eqHigh", sourceSeconds, deck.model.deck == AuthoringDeck::A ? highA_.getValue() : highB_.getValue());
        const auto reverbWet = laneValue(deck.model.deck, "reverbWet", sourceSeconds, deck.model.deck == AuthoringDeck::A ? reverbA_.getValue() : reverbB_.getValue());
        processDeckBuffer(player, temp_, output.numSamples, volume, eqLow, eqMid, eqHigh, reverbWet);

        for (int channel = 0; channel < output.buffer->getNumChannels(); ++channel) {
            output.buffer->addFrom(channel, output.startSample, temp_, channel, 0, output.numSamples);
        }
    }

    void processDeckBuffer(DeckPlayer& player,
                           juce::AudioBuffer<float>& buffer,
                           int samples,
                           double volume,
                           double eqLow,
                           double eqMid,
                           double eqHigh,
                           double reverbWet) {
        const auto lowAlpha = 1.0 - std::exp(-2.0 * juce::MathConstants<double>::pi * 180.0 / std::max(1.0, sampleRate_));
        const auto highAlpha = 1.0 - std::exp(-2.0 * juce::MathConstants<double>::pi * 2200.0 / std::max(1.0, sampleRate_));
        reverbSend_.setSize(std::max(2, buffer.getNumChannels()), samples, false, false, true);
        reverbSend_.clear();
        for (int channel = 0; channel < buffer.getNumChannels(); ++channel) {
            auto* data = buffer.getWritePointer(channel);
            auto* send = reverbSend_.getWritePointer(channel);
            auto& lowState = player.lowState[std::min(channel, 1)];
            auto& highLowState = player.highLowState[std::min(channel, 1)];
            for (int sample = 0; sample < samples; ++sample) {
                const auto input = static_cast<double>(data[sample]);
                lowState += lowAlpha * (input - lowState);
                highLowState += highAlpha * (input - highLowState);
                const auto low = lowState;
                const auto high = input - highLowState;
                const auto mid = input - low - high;
                const auto eqSignal = low * eqLow + mid * eqMid + high * eqHigh;
                const auto dryDuck = 1.0 - juce::jlimit(0.0, 0.9, reverbWet * 0.9);
                const auto sendGate = volume > 0.0001 ? 1.0 : 0.0;
                send[sample] = static_cast<float>(eqSignal * reverbWet * sendGate);
                data[sample] = static_cast<float>(eqSignal * volume * dryDuck);
            }
        }
        if (buffer.getNumChannels() == 1) {
            reverbSend_.copyFrom(1, 0, reverbSend_, 0, 0, samples);
        }
        juce::Reverb::Parameters params;
        params.roomSize = 0.92f;
        params.damping = 0.18f;
        params.wetLevel = 1.0f;
        params.dryLevel = 0.0f;
        params.width = 1.0f;
        player.reverb.setParameters(params);
        player.reverb.processStereo(reverbSend_.getWritePointer(0), reverbSend_.getWritePointer(1), samples);
        const auto wetReturnGain = static_cast<float>(reverbWet * 2.5);
        for (int channel = 0; channel < buffer.getNumChannels(); ++channel) {
            buffer.addFrom(channel, 0, reverbSend_, channel, 0, samples, wetReturnGain);
        }
    }

    void timerCallback() override {
        const auto nowMilliseconds = juce::Time::getMillisecondCounterHiRes();
        const auto elapsedSeconds = lastTimerMilliseconds_ > 0.0
                                        ? std::max(0.0, (nowMilliseconds - lastTimerMilliseconds_) / 1000.0)
                                        : 0.0;
        lastTimerMilliseconds_ = nowMilliseconds;
        if (globalPreviewActive_) {
            globalPreviewElapsedSeconds_ += elapsedSeconds;
        }
        updateDeckTransport(deckA_, deckAPlayer_, elapsedSeconds);
        updateDeckTransport(deckB_, deckBPlayer_, elapsedSeconds);
        updateAutomatedControls();
        if (globalPreviewActive_ && !deckAPlayer_.transport.isPlaying() && !deckBPlayer_.transport.isPlaying()
            && !hasLane(deckA_.model.deck, "play") && !hasLane(deckB_.model.deck, "play")) {
            globalPreviewActive_ = false;
        }
        repaintAll();
    }

    void updateDeckTransport(DeckVisualState& deck, DeckPlayer& player, const double elapsedSeconds) {
        const auto previous = deck.model.centerSeconds;
        const auto hasPlayAutomation = hasLane(deck.model.deck, "play");
        if (player.transport.isPlaying()) {
            deck.model.centerSeconds = player.transport.getCurrentPosition();
        } else if (globalPreviewActive_ && hasPlayAutomation) {
            deck.model.centerSeconds = std::max(0.0, deck.model.centerSeconds + elapsedSeconds);
        }
        const auto current = deck.model.centerSeconds;
        if (globalPreviewActive_ && !hasPlayAutomation && !player.previewStarted
            && globalPreviewElapsedSeconds_ >= deck.model.previewStartDelaySeconds && deck.audioLoaded) {
            player.transport.setPosition(current);
            player.transport.start();
            player.previewStarted = true;
        }
        if (globalPreviewActive_ && hasPlayAutomation && !player.transport.isPlaying() && deck.audioLoaded
            && crossedEvent(deck.model.deck, "play", previous, current)) {
            player.transport.setPosition(current);
            player.transport.start();
        }
        if (player.transport.isPlaying() && crossedEvent(deck.model.deck, "stop", previous, current)) {
            player.transport.stop();
        }
    }

    void updateAutomatedControls() {
        updateAutomatedControlsForDeck(deckA_, volumeA_, lowA_, midA_, highA_, reverbA_,
                                       deckAPlayer_.transport.isPlaying() || globalPreviewActive_);
        updateAutomatedControlsForDeck(deckB_, volumeB_, lowB_, midB_, highB_, reverbB_,
                                       deckBPlayer_.transport.isPlaying() || globalPreviewActive_);
    }

    void updateAutomatedControlsForDeck(const DeckVisualState& deck,
                                        ControlSlider& volume,
                                        ControlSlider& low,
                                        ControlSlider& mid,
                                        ControlSlider& high,
                                        ControlSlider& reverb,
                                        const bool active) {
        if (!active) {
            return;
        }
        const auto sourceSeconds = deck.model.centerSeconds;
        updateControlIfAutomated(deck.model.deck, "volume", sourceSeconds, volume);
        updateControlIfAutomated(deck.model.deck, "eqLow", sourceSeconds, low);
        updateControlIfAutomated(deck.model.deck, "eqMid", sourceSeconds, mid);
        updateControlIfAutomated(deck.model.deck, "eqHigh", sourceSeconds, high);
        updateControlIfAutomated(deck.model.deck, "reverbWet", sourceSeconds, reverb);
    }

    void updateControlIfAutomated(const AuthoringDeck deck,
                                  std::string_view control,
                                  const double sourceSeconds,
                                  ControlSlider& slider) {
        if (!hasLane(deck, control)) {
            return;
        }
        slider.setValue(laneValue(deck, control, sourceSeconds, slider.getValue()), juce::dontSendNotification);
    }

    void setStatus(const juce::String& message) {
        status_.setText(message, juce::dontSendNotification);
    }

    void repaintAll() {
        waveformA_.repaint();
        waveformB_.repaint();
        lanes_.repaint();
        const auto status = "A " + toJuceString(barBeatLabelForTime(deckA_.model.beats, deckA_.model.centerSeconds))
                            + " | B " + toJuceString(barBeatLabelForTime(deckB_.model.beats, deckB_.model.centerSeconds));
        status_.setText(status, juce::dontSendNotification);
    }

    juce::AudioFormatManager formatManager_;
    std::unique_ptr<juce::FileChooser> fileChooser_;
    double sampleRate_{44100.0};
    double lastTimerMilliseconds_{0.0};
    double globalPreviewElapsedSeconds_{0.0};
    bool globalPreviewActive_{false};
    juce::AudioBuffer<float> temp_;
    juce::AudioBuffer<float> reverbSend_;
    DeckVisualState deckA_;
    DeckVisualState deckB_;
    DeckPlayer deckAPlayer_;
    DeckPlayer deckBPlayer_;
    std::string sessionId_{"authoring-session"};
    std::string transitionFamily_{"drop_switch"};
    std::string notes_{"Exported from native transition authoring workbench."};
    std::vector<AutomationLane> automationLanes_;
    std::vector<AuthoringAnchor> anchors_;
    DeckWaveformComponent waveformA_;
    DeckWaveformComponent waveformB_;
    AutomationLaneComponent lanes_;
    juce::Label status_;
    juce::TextButton loadAudioA_, loadAnalyzedA_, loadWaveA_, loadAudioB_, loadAnalyzedB_, loadWaveB_;
    TransportButton playA_, stopA_, playB_, stopB_, playBoth_;
    juce::TextButton anchorA_, anchorB_, loadSession_, exportSession_, exportPlan_, exportRecipe_;
    juce::ComboBox selectedAnchorA_, selectedAnchorB_;
    std::vector<juce::Component*> topButtons_;
    ControlSlider volumeA_, volumeB_, lowA_, midA_, highA_, reverbA_, lowB_, midB_, highB_, reverbB_;
};

class MainWindow final : public juce::DocumentWindow {
public:
    MainWindow()
        : DocumentWindow(toJuceString(WorkbenchText::AppTitle),
                         background,
                         DocumentWindow::allButtons) {
        setUsingNativeTitleBar(true);
        setContentOwned(new MainComponent(), true);
        centreWithSize(getWidth(), getHeight());
        setVisible(true);
    }

    void closeButtonPressed() override { juce::JUCEApplication::getInstance()->systemRequestedQuit(); }
};

class AutoDJApplication final : public juce::JUCEApplication {
public:
    const juce::String getApplicationName() override { return toJuceString(WorkbenchText::AppTitle); }
    const juce::String getApplicationVersion() override { return "0.1.0"; }
    bool moreThanOneInstanceAllowed() override { return true; }
    void initialise(const juce::String&) override { mainWindow_ = std::make_unique<MainWindow>(); }
    void shutdown() override { mainWindow_.reset(); }
    void systemRequestedQuit() override { quit(); }
    void anotherInstanceStarted(const juce::String&) override {}

private:
    std::unique_ptr<MainWindow> mainWindow_;
};

}  // namespace

}  // namespace autodj::desktop

START_JUCE_APPLICATION(autodj::desktop::AutoDJApplication)
