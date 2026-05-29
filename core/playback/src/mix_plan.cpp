#include "autodj/playback/mix_plan.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>

namespace autodj::playback {
namespace {

struct JsonValue final {
    enum class Type {
        Null,
        Boolean,
        Number,
        String,
        Array,
        Object,
    };

    Type type{Type::Null};
    bool booleanValue{false};
    double numberValue{0.0};
    std::string stringValue;
    std::vector<JsonValue> arrayValue;
    std::map<std::string, JsonValue> objectValue;
};

class JsonParser final {
public:
    explicit JsonParser(std::string_view input) : input_{input} {}

    [[nodiscard]] std::optional<JsonValue> parse() {
        skipWhitespace();
        auto value = parseValue();
        if (!value.has_value()) {
            return std::nullopt;
        }

        skipWhitespace();
        if (position_ != input_.size()) {
            fail("Unexpected trailing JSON content");
            return std::nullopt;
        }
        return value;
    }

    [[nodiscard]] const std::string& error() const noexcept { return error_; }

private:
    void skipWhitespace() {
        while (position_ < input_.size() && std::isspace(static_cast<unsigned char>(input_[position_]))) {
            ++position_;
        }
    }

    [[nodiscard]] bool consume(const char expected) {
        if (position_ >= input_.size() || input_[position_] != expected) {
            return false;
        }
        ++position_;
        return true;
    }

    [[nodiscard]] bool consumeLiteral(std::string_view literal) {
        if (input_.substr(position_, literal.size()) != literal) {
            return false;
        }
        position_ += literal.size();
        return true;
    }

    [[nodiscard]] std::optional<JsonValue> parseValue() {
        skipWhitespace();
        if (position_ >= input_.size()) {
            fail("Unexpected end of JSON");
            return std::nullopt;
        }

        const auto character = input_[position_];
        if (character == '{') {
            return parseObject();
        }
        if (character == '[') {
            return parseArray();
        }
        if (character == '"') {
            auto parsedString = parseString();
            if (!parsedString.has_value()) {
                return std::nullopt;
            }
            JsonValue value;
            value.type = JsonValue::Type::String;
            value.stringValue = std::move(parsedString.value());
            return value;
        }
        if (character == '-' || std::isdigit(static_cast<unsigned char>(character))) {
            return parseNumber();
        }
        if (consumeLiteral("true")) {
            JsonValue value;
            value.type = JsonValue::Type::Boolean;
            value.booleanValue = true;
            return value;
        }
        if (consumeLiteral("false")) {
            JsonValue value;
            value.type = JsonValue::Type::Boolean;
            value.booleanValue = false;
            return value;
        }
        if (consumeLiteral("null")) {
            return JsonValue{};
        }

        fail("Unexpected JSON value");
        return std::nullopt;
    }

    [[nodiscard]] std::optional<JsonValue> parseObject() {
        if (!consume('{')) {
            fail("Expected object");
            return std::nullopt;
        }

        JsonValue object;
        object.type = JsonValue::Type::Object;

        skipWhitespace();
        if (consume('}')) {
            return object;
        }

        while (true) {
            skipWhitespace();
            auto key = parseString();
            if (!key.has_value()) {
                return std::nullopt;
            }

            skipWhitespace();
            if (!consume(':')) {
                fail("Expected ':' after object key");
                return std::nullopt;
            }

            auto value = parseValue();
            if (!value.has_value()) {
                return std::nullopt;
            }

            object.objectValue.emplace(std::move(key.value()), std::move(value.value()));

            skipWhitespace();
            if (consume('}')) {
                return object;
            }
            if (!consume(',')) {
                fail("Expected ',' or '}' in object");
                return std::nullopt;
            }
        }
    }

    [[nodiscard]] std::optional<JsonValue> parseArray() {
        if (!consume('[')) {
            fail("Expected array");
            return std::nullopt;
        }

        JsonValue array;
        array.type = JsonValue::Type::Array;

        skipWhitespace();
        if (consume(']')) {
            return array;
        }

        while (true) {
            auto value = parseValue();
            if (!value.has_value()) {
                return std::nullopt;
            }
            array.arrayValue.push_back(std::move(value.value()));

            skipWhitespace();
            if (consume(']')) {
                return array;
            }
            if (!consume(',')) {
                fail("Expected ',' or ']' in array");
                return std::nullopt;
            }
        }
    }

    [[nodiscard]] std::optional<std::string> parseString() {
        if (!consume('"')) {
            fail("Expected JSON string");
            return std::nullopt;
        }

        std::string value;
        while (position_ < input_.size()) {
            const auto character = input_[position_++];
            if (character == '"') {
                return value;
            }

            if (static_cast<unsigned char>(character) < 0x20U) {
                fail("Unescaped control character in JSON string");
                return std::nullopt;
            }

            if (character != '\\') {
                value.push_back(character);
                continue;
            }

            if (position_ >= input_.size()) {
                fail("Unterminated JSON escape");
                return std::nullopt;
            }

            const auto escaped = input_[position_++];
            switch (escaped) {
                case '"':
                case '\\':
                case '/':
                    value.push_back(escaped);
                    break;
                case 'b':
                    value.push_back('\b');
                    break;
                case 'f':
                    value.push_back('\f');
                    break;
                case 'n':
                    value.push_back('\n');
                    break;
                case 'r':
                    value.push_back('\r');
                    break;
                case 't':
                    value.push_back('\t');
                    break;
                case 'u': {
                    auto codepoint = parseFourDigitHexEscape();
                    if (!codepoint.has_value()) {
                        return std::nullopt;
                    }
                    if (codepoint.value() > 0x7fU) {
                        fail("Only ASCII unicode escapes are supported in MixPlan JSON");
                        return std::nullopt;
                    }
                    value.push_back(static_cast<char>(codepoint.value()));
                    break;
                }
                default:
                    fail("Invalid JSON escape");
                    return std::nullopt;
            }
        }

        fail("Unterminated JSON string");
        return std::nullopt;
    }

    [[nodiscard]] std::optional<unsigned int> parseFourDigitHexEscape() {
        if (position_ + 4 > input_.size()) {
            fail("Incomplete unicode escape");
            return std::nullopt;
        }

        unsigned int value = 0;
        for (int index = 0; index < 4; ++index) {
            const auto character = input_[position_++];
            value <<= 4;
            if (character >= '0' && character <= '9') {
                value += static_cast<unsigned int>(character - '0');
            } else if (character >= 'a' && character <= 'f') {
                value += static_cast<unsigned int>(character - 'a' + 10);
            } else if (character >= 'A' && character <= 'F') {
                value += static_cast<unsigned int>(character - 'A' + 10);
            } else {
                fail("Invalid unicode escape");
                return std::nullopt;
            }
        }
        return value;
    }

    [[nodiscard]] std::optional<JsonValue> parseNumber() {
        const auto start = position_;

        if (input_[position_] == '-') {
            ++position_;
        }
        if (position_ >= input_.size()) {
            fail("Invalid JSON number");
            return std::nullopt;
        }

        if (input_[position_] == '0') {
            ++position_;
        } else if (std::isdigit(static_cast<unsigned char>(input_[position_]))) {
            while (position_ < input_.size() && std::isdigit(static_cast<unsigned char>(input_[position_]))) {
                ++position_;
            }
        } else {
            fail("Invalid JSON number");
            return std::nullopt;
        }

        if (position_ < input_.size() && input_[position_] == '.') {
            ++position_;
            if (position_ >= input_.size() || !std::isdigit(static_cast<unsigned char>(input_[position_]))) {
                fail("Invalid JSON number fraction");
                return std::nullopt;
            }
            while (position_ < input_.size() && std::isdigit(static_cast<unsigned char>(input_[position_]))) {
                ++position_;
            }
        }

        if (position_ < input_.size() && (input_[position_] == 'e' || input_[position_] == 'E')) {
            ++position_;
            if (position_ < input_.size() && (input_[position_] == '+' || input_[position_] == '-')) {
                ++position_;
            }
            if (position_ >= input_.size() || !std::isdigit(static_cast<unsigned char>(input_[position_]))) {
                fail("Invalid JSON number exponent");
                return std::nullopt;
            }
            while (position_ < input_.size() && std::isdigit(static_cast<unsigned char>(input_[position_]))) {
                ++position_;
            }
        }

        try {
            JsonValue value;
            value.type = JsonValue::Type::Number;
            value.numberValue = std::stod(std::string{input_.substr(start, position_ - start)});
            return value;
        } catch (const std::exception&) {
            fail("Invalid JSON number");
            return std::nullopt;
        }
    }

    void fail(std::string message) {
        if (error_.empty()) {
            std::ostringstream output;
            output << message << " at byte " << position_;
            error_ = output.str();
        }
    }

    std::string_view input_;
    std::size_t position_{0};
    std::string error_;
};

[[nodiscard]] bool isBlank(std::string_view value) {
    return std::ranges::all_of(value, [](const char character) {
        return character == ' ' || character == '\t' || character == '\r' || character == '\n';
    });
}

void addError(PlanValidationResult& result, std::string code, std::string message) {
    result.errors.push_back(PlanValidationIssue{
        .code = std::move(code),
        .message = std::move(message),
    });
}

void addWarning(PlanValidationResult& result, std::string code, std::string message) {
    result.warnings.push_back(PlanValidationIssue{
        .code = std::move(code),
        .message = std::move(message),
    });
}

[[nodiscard]] const JsonValue* findField(const std::map<std::string, JsonValue>& object, const std::string& field) {
    const auto iterator = object.find(field);
    if (iterator == object.end()) {
        return nullptr;
    }
    return &iterator->second;
}

[[nodiscard]] const std::map<std::string, JsonValue>* requiredObject(const std::map<std::string, JsonValue>& object,
                                                                     const std::string& field,
                                                                     PlanValidationResult& result) {
    const auto* value = findField(object, field);
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        addError(result, "missing_object", "Missing required object field: " + field);
        return nullptr;
    }
    return &value->objectValue;
}

[[nodiscard]] const std::map<std::string, JsonValue>* optionalObject(const std::map<std::string, JsonValue>& object,
                                                                     const std::string& field,
                                                                     PlanValidationResult& result) {
    const auto* value = findField(object, field);
    if (value == nullptr) {
        return nullptr;
    }
    if (value->type != JsonValue::Type::Object) {
        addError(result, "invalid_object", "Expected object field: " + field);
        return nullptr;
    }
    return &value->objectValue;
}

[[nodiscard]] const std::vector<JsonValue>* requiredArray(const std::map<std::string, JsonValue>& object,
                                                          const std::string& field,
                                                          PlanValidationResult& result) {
    const auto* value = findField(object, field);
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        addError(result, "missing_array", "Missing required array field: " + field);
        return nullptr;
    }
    return &value->arrayValue;
}

[[nodiscard]] const std::vector<JsonValue>* optionalArray(const std::map<std::string, JsonValue>& object,
                                                          const std::string& field,
                                                          PlanValidationResult& result) {
    const auto* value = findField(object, field);
    if (value == nullptr) {
        return nullptr;
    }
    if (value->type != JsonValue::Type::Array) {
        addError(result, "invalid_array", "Expected array field: " + field);
        return nullptr;
    }
    return &value->arrayValue;
}

[[nodiscard]] std::optional<std::string> requiredString(const std::map<std::string, JsonValue>& object,
                                                        const std::string& field,
                                                        PlanValidationResult& result) {
    const auto* value = findField(object, field);
    if (value == nullptr || value->type != JsonValue::Type::String || value->stringValue.empty()) {
        addError(result, "missing_string", "Missing required string field: " + field);
        return std::nullopt;
    }
    return value->stringValue;
}

[[nodiscard]] std::string optionalString(const std::map<std::string, JsonValue>& object,
                                         const std::string& field,
                                         PlanValidationResult& result) {
    const auto* value = findField(object, field);
    if (value == nullptr) {
        return {};
    }
    if (value->type != JsonValue::Type::String) {
        addError(result, "invalid_string", "Expected string field: " + field);
        return {};
    }
    return value->stringValue;
}

[[nodiscard]] std::optional<double> requiredNumber(const std::map<std::string, JsonValue>& object,
                                                   const std::string& field,
                                                   PlanValidationResult& result,
                                                   const bool allowNegative = false) {
    const auto* value = findField(object, field);
    if (value == nullptr || value->type != JsonValue::Type::Number || !std::isfinite(value->numberValue)
        || (!allowNegative && value->numberValue < 0.0)) {
        addError(result, "invalid_number", "Missing or invalid number field: " + field);
        return std::nullopt;
    }
    return value->numberValue;
}

[[nodiscard]] std::optional<double> optionalNumber(const std::map<std::string, JsonValue>& object,
                                                   const std::string& field,
                                                   PlanValidationResult& result,
                                                   const bool allowNegative = false) {
    const auto* value = findField(object, field);
    if (value == nullptr) {
        return std::nullopt;
    }
    if (value->type != JsonValue::Type::Number || !std::isfinite(value->numberValue)
        || (!allowNegative && value->numberValue < 0.0)) {
        addError(result, "invalid_number", "Invalid number field: " + field);
        return std::nullopt;
    }
    return value->numberValue;
}

[[nodiscard]] std::optional<int> requiredPositiveInteger(const std::map<std::string, JsonValue>& object,
                                                         const std::string& field,
                                                         PlanValidationResult& result) {
    const auto value = requiredNumber(object, field, result);
    if (!value.has_value()) {
        return std::nullopt;
    }
    const auto rounded = std::floor(value.value());
    if (value.value() != rounded || value.value() < 1.0) {
        addError(result, "invalid_integer", "Expected positive integer field: " + field);
        return std::nullopt;
    }
    return static_cast<int>(rounded);
}

[[nodiscard]] std::optional<int> optionalNonNegativeInteger(const std::map<std::string, JsonValue>& object,
                                                            const std::string& field,
                                                            PlanValidationResult& result) {
    const auto value = optionalNumber(object, field, result);
    if (!value.has_value()) {
        return std::nullopt;
    }
    const auto rounded = std::floor(value.value());
    if (value.value() != rounded) {
        addError(result, "invalid_integer", "Expected integer field: " + field);
        return std::nullopt;
    }
    return static_cast<int>(rounded);
}

[[nodiscard]] bool optionalBoolean(const std::map<std::string, JsonValue>& object,
                                   const std::string& field,
                                   PlanValidationResult& result) {
    const auto* value = findField(object, field);
    if (value == nullptr) {
        return false;
    }
    if (value->type != JsonValue::Type::Boolean) {
        addError(result, "invalid_boolean", "Expected boolean field: " + field);
        return false;
    }
    return value->booleanValue;
}

[[nodiscard]] std::optional<bool> optionalBooleanValue(const std::map<std::string, JsonValue>& object,
                                                       const std::string& field,
                                                       PlanValidationResult& result) {
    const auto* value = findField(object, field);
    if (value == nullptr) {
        return std::nullopt;
    }
    if (value->type != JsonValue::Type::Boolean) {
        addError(result, "invalid_boolean", "Expected boolean field: " + field);
        return std::nullopt;
    }
    return value->booleanValue;
}

[[nodiscard]] std::vector<std::string> optionalStringArray(const std::map<std::string, JsonValue>& object,
                                                           const std::string& field,
                                                           PlanValidationResult& result) {
    std::vector<std::string> values;
    const auto* array = optionalArray(object, field, result);
    if (array == nullptr) {
        return values;
    }
    for (const auto& item : *array) {
        if (item.type != JsonValue::Type::String) {
            addError(result, "invalid_string_array", "Expected string item in array field: " + field);
            continue;
        }
        values.push_back(item.stringValue);
    }
    return values;
}

[[nodiscard]] std::optional<TransitionTechnique> parseTechnique(const std::string& value) {
    if (value == "intro_outro_blend") {
        return TransitionTechnique::IntroOutroBlend;
    }
    if (value == "build_to_drop_swap") {
        return TransitionTechnique::BuildToDropSwap;
    }
    if (value == "drop_end_reverb_exit") {
        return TransitionTechnique::DropEndReverbExit;
    }
    if (value == "wash_out") {
        return TransitionTechnique::WashOut;
    }
    if (value == "loop_tighten") {
        return TransitionTechnique::LoopTighten;
    }
    if (value == "vocal_over_instrumental") {
        return TransitionTechnique::VocalOverInstrumental;
    }
    if (value == "echo_out") {
        return TransitionTechnique::EchoOut;
    }
    if (value == "hard_cut") {
        return TransitionTechnique::HardCut;
    }
    return std::nullopt;
}

[[nodiscard]] std::optional<DeckCommandType> parseCommandType(const std::string& value) {
    if (value == "load") {
        return DeckCommandType::Load;
    }
    if (value == "play") {
        return DeckCommandType::Play;
    }
    if (value == "stop") {
        return DeckCommandType::Stop;
    }
    if (value == "seek") {
        return DeckCommandType::Seek;
    }
    if (value == "setLoop") {
        return DeckCommandType::SetLoop;
    }
    if (value == "clearLoop") {
        return DeckCommandType::ClearLoop;
    }
    if (value == "automate") {
        return DeckCommandType::Automate;
    }
    return std::nullopt;
}

[[nodiscard]] std::optional<AutomationControl> parseControl(const std::string& value) {
    if (value == "volume") {
        return AutomationControl::Volume;
    }
    if (value == "eqLow") {
        return AutomationControl::EqLow;
    }
    if (value == "eqMid") {
        return AutomationControl::EqMid;
    }
    if (value == "eqHigh") {
        return AutomationControl::EqHigh;
    }
    if (value == "filter") {
        return AutomationControl::Filter;
    }
    if (value == "reverbWet") {
        return AutomationControl::ReverbWet;
    }
    if (value == "reverbTailGain") {
        return AutomationControl::ReverbTailGain;
    }
    if (value == "reverbDecaySeconds") {
        return AutomationControl::ReverbDecaySeconds;
    }
    if (value == "echoWet") {
        return AutomationControl::EchoWet;
    }
    if (value == "tempo") {
        return AutomationControl::Tempo;
    }
    if (value == "crossfader") {
        return AutomationControl::Crossfader;
    }
    return std::nullopt;
}

[[nodiscard]] KeyframeInterpolation parseInterpolation(const std::string& value) {
    if (value == "hold") {
        return KeyframeInterpolation::Hold;
    }
    if (value == "smoothstep") {
        return KeyframeInterpolation::Smoothstep;
    }
    if (value == "exponential") {
        return KeyframeInterpolation::Exponential;
    }
    return KeyframeInterpolation::Linear;
}

[[nodiscard]] std::string parameterValueToString(const JsonValue& value) {
    switch (value.type) {
        case JsonValue::Type::Boolean:
            return value.booleanValue ? "true" : "false";
        case JsonValue::Type::Number: {
            std::ostringstream output;
            output << value.numberValue;
            return output.str();
        }
        case JsonValue::Type::String:
            return value.stringValue;
        case JsonValue::Type::Null:
            return "null";
        case JsonValue::Type::Array:
        case JsonValue::Type::Object:
            return {};
    }
    return {};
}

[[nodiscard]] std::optional<TempoPlan> parseTempoPlan(const std::map<std::string, JsonValue>& object,
                                                       const std::string& field,
                                                       PlanValidationResult& result) {
    const auto* tempoObject = optionalObject(object, field, result);
    if (tempoObject == nullptr) {
        return std::nullopt;
    }

    TempoPlan tempoPlan;
    tempoPlan.sourceBpm = optionalNumber(*tempoObject, "sourceBpm", result);
    tempoPlan.targetBpm = optionalNumber(*tempoObject, "targetBpm", result);
    tempoPlan.tempoRatio = optionalNumber(*tempoObject, "tempoRatio", result);
    tempoPlan.preservePitch = optionalBooleanValue(*tempoObject, "preservePitch", result);
    tempoPlan.backend = optionalString(*tempoObject, "backend", result);
    tempoPlan.backendVersion = optionalString(*tempoObject, "backendVersion", result);
    tempoPlan.quality = optionalString(*tempoObject, "quality", result);
    tempoPlan.renderedSourceUri = optionalString(*tempoObject, "renderedSourceUri", result);
    tempoPlan.renderedContentHash = optionalString(*tempoObject, "renderedContentHash", result);
    tempoPlan.targetBpmBias = optionalNumber(*tempoObject, "targetBpmBias", result, true);
    tempoPlan.validatedBpm = optionalNumber(*tempoObject, "validatedBpm", result);
    tempoPlan.validationStatus = optionalString(*tempoObject, "validationStatus", result);
    tempoPlan.requiresRenderedBpmValidation =
        optionalBooleanValue(*tempoObject, "requiresRenderedBpmValidation", result);
    tempoPlan.warnings = optionalStringArray(*tempoObject, "warnings", result);
    return tempoPlan;
}

[[nodiscard]] TrackAssetReference parseAsset(const JsonValue& value, PlanValidationResult& result) {
    TrackAssetReference asset;
    if (value.type != JsonValue::Type::Object) {
        addError(result, "invalid_asset", "MixPlan asset entries must be objects");
        return asset;
    }
    const auto& object = value.objectValue;
    if (auto trackId = requiredString(object, "trackId", result)) {
        asset.trackId = domain::TrackId{trackId.value()};
    }
    if (auto sourceUri = requiredString(object, "sourceUri", result)) {
        asset.sourceUri = sourceUri.value();
    }
    asset.formatHint = optionalString(object, "formatHint", result);
    asset.contentHash = optionalString(object, "contentHash", result);
    asset.durationSeconds = optionalNumber(object, "durationSeconds", result);
    asset.sourceBpm = optionalNumber(object, "sourceBpm", result);
    asset.normalizedBpm = optionalNumber(object, "normalizedBpm", result);
    return asset;
}

[[nodiscard]] TrackPlacement parsePlacement(const JsonValue& value, PlanValidationResult& result) {
    TrackPlacement placement;
    if (value.type != JsonValue::Type::Object) {
        addError(result, "invalid_placement", "MixPlan track placement entries must be objects");
        return placement;
    }
    const auto& object = value.objectValue;
    if (auto placementId = requiredString(object, "placementId", result)) {
        placement.placementId = placementId.value();
    }
    if (auto trackId = requiredString(object, "trackId", result)) {
        placement.trackId = domain::TrackId{trackId.value()};
    }
    if (auto deck = requiredPositiveInteger(object, "deck", result)) {
        placement.deck = deck.value();
    }
    if (auto sourceStart = requiredNumber(object, "sourceStartSeconds", result)) {
        placement.sourceStartSeconds = sourceStart.value();
    }
    placement.sourceEndSeconds = optionalNumber(object, "sourceEndSeconds", result);
    if (auto timelineStart = requiredNumber(object, "timelineStartSeconds", result)) {
        placement.timelineStartSeconds = timelineStart.value();
    }
    placement.timelineEndSeconds = optionalNumber(object, "timelineEndSeconds", result);
    placement.role = optionalString(object, "role", result);
    placement.tempoPlan = parseTempoPlan(object, "tempoPlan", result);
    return placement;
}

[[nodiscard]] TransitionAnchor parseAnchor(const JsonValue& value, PlanValidationResult& result) {
    TransitionAnchor anchor;
    if (value.type != JsonValue::Type::Object) {
        addError(result, "invalid_anchor", "MixPlan transition anchor entries must be objects");
        return anchor;
    }
    const auto& object = value.objectValue;
    if (auto trackId = optionalString(object, "trackId", result); !trackId.empty()) {
        anchor.trackId = domain::TrackId{std::move(trackId)};
    }
    anchor.sectionId = optionalString(object, "sectionId", result);
    anchor.cueId = optionalString(object, "cueId", result);
    anchor.sourceSeconds = optionalNumber(object, "sourceSeconds", result);
    anchor.beatIndex = optionalNonNegativeInteger(object, "beatIndex", result);
    anchor.measureIndex = optionalNonNegativeInteger(object, "measureIndex", result);
    return anchor;
}

[[nodiscard]] TransitionEdge parseTransition(const JsonValue& value, PlanValidationResult& result) {
    TransitionEdge transition;
    if (value.type != JsonValue::Type::Object) {
        addError(result, "invalid_transition", "MixPlan transition entries must be objects");
        return transition;
    }
    const auto& object = value.objectValue;
    if (auto transitionId = requiredString(object, "transitionId", result)) {
        transition.transitionId = transitionId.value();
    }
    if (auto fromPlacementId = requiredString(object, "fromPlacementId", result)) {
        transition.fromPlacementId = fromPlacementId.value();
    }
    if (auto toPlacementId = requiredString(object, "toPlacementId", result)) {
        transition.toPlacementId = toPlacementId.value();
    }
    if (auto techniqueName = requiredString(object, "technique", result)) {
        if (auto technique = parseTechnique(techniqueName.value())) {
            transition.technique = technique.value();
        } else {
            addError(result, "unknown_transition_technique", "Unknown transition technique: " + techniqueName.value());
        }
    }
    transition.templateId = optionalString(object, "templateId", result);
    if (auto start = requiredNumber(object, "timelineStartSeconds", result)) {
        transition.timelineStartSeconds = start.value();
    }
    if (auto end = requiredNumber(object, "timelineEndSeconds", result)) {
        transition.timelineEndSeconds = end.value();
    }
    if (auto score = requiredNumber(object, "score", result)) {
        transition.score = score.value();
    }
    transition.reasons = optionalStringArray(object, "reasons", result);
    transition.riskFlags = optionalStringArray(object, "riskFlags", result);
    transition.measureCountToTarget = optionalNumber(object, "measureCountToTarget", result);
    transition.alignedDropTimelineSeconds = optionalNumber(object, "alignedDropTimelineSeconds", result);
    transition.handoffTimelineSeconds = optionalNumber(object, "handoffTimelineSeconds", result);
    transition.tempoPlan = parseTempoPlan(object, "tempoPlan", result);

    const auto* anchors = findField(object, "sourceAnchors");
    if (anchors != nullptr) {
        if (anchors->type != JsonValue::Type::Object) {
            addError(result, "invalid_source_anchors", "sourceAnchors must be an object");
        } else {
            for (const auto& [name, anchorValue] : anchors->objectValue) {
                transition.sourceAnchors.emplace(name, parseAnchor(anchorValue, result));
            }
        }
    }
    return transition;
}

[[nodiscard]] Keyframe parseKeyframe(const JsonValue& value, PlanValidationResult& result) {
    Keyframe keyframe;
    if (value.type != JsonValue::Type::Object) {
        addError(result, "invalid_keyframe", "MixPlan automation keyframe entries must be objects");
        return keyframe;
    }
    const auto& object = value.objectValue;
    if (auto at = requiredNumber(object, "at", result)) {
        keyframe.at = at.value();
    }
    if (auto frameValue = requiredNumber(object, "value", result, true)) {
        keyframe.value = frameValue.value();
    }
    keyframe.interpolation = parseInterpolation(optionalString(object, "interpolation", result));
    return keyframe;
}

[[nodiscard]] std::vector<Keyframe> parseKeyframes(const std::map<std::string, JsonValue>& object,
                                                   PlanValidationResult& result) {
    std::vector<Keyframe> keyframes;
    const auto* array = requiredArray(object, "keyframes", result);
    if (array == nullptr) {
        return keyframes;
    }
    if (array->empty()) {
        addError(result, "empty_keyframes", "Automation commands require at least one keyframe");
        return keyframes;
    }
    keyframes.reserve(array->size());
    for (const auto& item : *array) {
        keyframes.push_back(parseKeyframe(item, result));
    }
    return keyframes;
}

[[nodiscard]] DeckCommand parseCommand(const JsonValue& value, PlanValidationResult& result) {
    DeckCommand command;
    if (value.type != JsonValue::Type::Object) {
        addError(result, "invalid_command", "MixPlan command entries must be objects");
        return command;
    }
    const auto& object = value.objectValue;

    if (auto typeName = requiredString(object, "type", result)) {
        if (auto type = parseCommandType(typeName.value())) {
            command.type = type.value();
        } else {
            addError(result, "unknown_command_type", "Unknown command type: " + typeName.value());
        }
    }
    switch (command.type) {
        case DeckCommandType::Load:
            if (auto at = requiredNumber(object, "at", result)) {
                command.at = at.value();
            }
            command.deck = requiredPositiveInteger(object, "deck", result);
            if (auto trackId = requiredString(object, "trackId", result)) {
                command.trackId = domain::TrackId{trackId.value()};
            }
            command.stem = optionalString(object, "stem", result);
            command.cueSeconds = requiredNumber(object, "cueSeconds", result);
            break;
        case DeckCommandType::Play:
        case DeckCommandType::Stop:
        case DeckCommandType::ClearLoop:
            if (auto at = requiredNumber(object, "at", result)) {
                command.at = at.value();
            }
            command.deck = requiredPositiveInteger(object, "deck", result);
            break;
        case DeckCommandType::Seek:
            if (auto at = requiredNumber(object, "at", result)) {
                command.at = at.value();
            }
            command.deck = requiredPositiveInteger(object, "deck", result);
            command.toSeconds = requiredNumber(object, "toSeconds", result);
            break;
        case DeckCommandType::SetLoop:
            if (auto at = requiredNumber(object, "at", result)) {
                command.at = at.value();
            }
            command.deck = requiredPositiveInteger(object, "deck", result);
            command.startSeconds = requiredNumber(object, "startSeconds", result);
            command.lengthBeats = requiredNumber(object, "lengthBeats", result);
            if (command.lengthBeats.has_value() && command.lengthBeats.value() <= 0.0) {
                addError(result, "invalid_loop_length", "Loop command lengthBeats must be greater than 0");
            }
            break;
        case DeckCommandType::Automate: {
            if (auto deck = optionalNonNegativeInteger(object, "deck", result)) {
                if (deck.value() < 1) {
                    addError(result, "invalid_deck", "Automation deck must be positive when provided");
                } else {
                    command.deck = deck.value();
                }
            }
            if (auto controlName = requiredString(object, "control", result)) {
                if (auto control = parseControl(controlName.value())) {
                    command.control = control.value();
                } else {
                    addError(result, "unknown_automation_control", "Unknown automation control: " + controlName.value());
                }
            }
            command.postFader = optionalBoolean(object, "postFader", result);
            command.keyframes = parseKeyframes(object, result);
            if (auto at = optionalNumber(object, "at", result)) {
                command.at = at.value();
            } else if (!command.keyframes.empty()) {
                command.at = command.keyframes.front().at;
            }

            const auto* effectParameters = findField(object, "effectParameters");
            if (effectParameters != nullptr) {
                if (effectParameters->type != JsonValue::Type::Object) {
                    addError(result, "invalid_effect_parameters", "effectParameters must be an object");
                } else {
                    for (const auto& [name, parameterValue] : effectParameters->objectValue) {
                        if (parameterValue.type == JsonValue::Type::Object || parameterValue.type == JsonValue::Type::Array) {
                            addError(result, "invalid_effect_parameter", "effectParameters values must be scalar: " + name);
                            continue;
                        }
                        command.effectParameters.emplace(name, parameterValueToString(parameterValue));
                    }
                }
            }
            break;
        }
    }

    return command;
}

[[nodiscard]] PlanAnnotation parseAnnotation(const JsonValue& value, PlanValidationResult& result) {
    PlanAnnotation annotation;
    if (value.type != JsonValue::Type::Object) {
        addError(result, "invalid_annotation", "MixPlan annotation entries must be objects");
        return annotation;
    }
    const auto& object = value.objectValue;
    if (auto at = requiredNumber(object, "at", result)) {
        annotation.at = at.value();
    }
    annotation.placementId = optionalString(object, "placementId", result);
    annotation.transitionId = optionalString(object, "transitionId", result);
    if (auto message = requiredString(object, "message", result)) {
        annotation.message = message.value();
    }
    return annotation;
}

template <typename T>
void requireUnique(const std::vector<T>& values,
                   const std::string& code,
                   const std::string& label,
                   PlanValidationResult& result,
                   const auto& idOf) {
    std::set<std::string> seen;
    for (const auto& value : values) {
        const auto id = idOf(value);
        if (id.empty()) {
            continue;
        }
        if (!seen.insert(id).second) {
            addError(result, code, "Duplicate " + label + ": " + id);
        }
    }
}

void validatePositiveBpm(const std::optional<double> value,
                         const std::string& code,
                         const std::string& label,
                         PlanValidationResult& result) {
    if (value.has_value() && value.value() <= 0.0) {
        addError(result, code, label + " must be greater than 0");
    }
}

void validateTempoPlan(const std::optional<TempoPlan>& tempoPlan,
                       const std::string& ownerLabel,
                       PlanValidationResult& result) {
    if (!tempoPlan.has_value()) {
        return;
    }

    const auto& tempo = tempoPlan.value();
    validatePositiveBpm(tempo.sourceBpm, "invalid_tempo_plan", ownerLabel + " sourceBpm", result);
    validatePositiveBpm(tempo.targetBpm, "invalid_tempo_plan", ownerLabel + " targetBpm", result);
    validatePositiveBpm(tempo.validatedBpm, "invalid_tempo_plan", ownerLabel + " validatedBpm", result);

    if (tempo.tempoRatio.has_value() && tempo.tempoRatio.value() <= 0.0) {
        addError(result, "invalid_tempo_plan", ownerLabel + " tempoRatio must be greater than 0");
    }

    if (tempo.sourceBpm.has_value() && tempo.targetBpm.has_value() && tempo.tempoRatio.has_value()) {
        const auto expectedRatio = tempo.targetBpm.value() / tempo.sourceBpm.value();
        if (std::fabs(expectedRatio - tempo.tempoRatio.value()) > 0.001) {
            addWarning(result, "tempo_ratio_mismatch",
                       ownerLabel + " tempoRatio does not match targetBpm/sourceBpm");
        }
    }

    const auto changesTempo = tempo.sourceBpm.has_value() && tempo.targetBpm.has_value()
                           && std::fabs(tempo.sourceBpm.value() - tempo.targetBpm.value()) > 0.001;
    if (changesTempo && tempo.preservePitch.has_value() && tempo.preservePitch.value() && tempo.backend.empty()) {
        addWarning(result, "missing_tempo_backend",
                   ownerLabel + " preserve-pitch tempo change should identify a stretch backend");
    }

    if (tempo.renderedSourceUri.empty() && tempo.requiresRenderedBpmValidation.has_value()
        && tempo.requiresRenderedBpmValidation.value()) {
        addWarning(result, "tempo_render_validation_pending",
                   ownerLabel + " requests rendered BPM validation but has no renderedSourceUri yet");
    }
}

void validatePlan(MixPlan& plan, PlanValidationResult& result) {
    if (plan.schemaVersion != "1.0.0") {
        addError(result, "unsupported_schema_version", "MixPlan schemaVersion must be 1.0.0");
    }
    if (plan.tracks.empty()) {
        addError(result, "empty_tracks", "MixPlan requires at least one track placement");
    }
    if (plan.transitions.empty()) {
        addError(result, "empty_transitions", "MixPlan requires at least one transition");
    }
    if (plan.commands.empty()) {
        addError(result, "empty_commands", "MixPlan requires at least one command");
    }

    requireUnique(plan.assets, "duplicate_asset_track", "asset trackId", result, [](const TrackAssetReference& asset) {
        return asset.trackId.value;
    });
    requireUnique(plan.tracks, "duplicate_placement", "placementId", result, [](const TrackPlacement& placement) {
        return placement.placementId;
    });
    requireUnique(plan.transitions, "duplicate_transition", "transitionId", result, [](const TransitionEdge& transition) {
        return transition.transitionId;
    });

    std::set<std::string> knownTrackIds;
    for (const auto& asset : plan.assets) {
        validatePositiveBpm(asset.sourceBpm, "invalid_asset_bpm", "Asset sourceBpm", result);
        validatePositiveBpm(asset.normalizedBpm, "invalid_asset_bpm", "Asset normalizedBpm", result);
        if (!asset.trackId.empty()) {
            knownTrackIds.insert(asset.trackId.value);
        }
    }

    std::set<std::string> placementIds;
    for (const auto& placement : plan.tracks) {
        if (placement.sourceEndSeconds.has_value() && placement.sourceEndSeconds.value() < placement.sourceStartSeconds) {
            addError(result, "invalid_placement_time", "Placement sourceEndSeconds precedes sourceStartSeconds: "
                                                     + placement.placementId);
        }
        if (placement.timelineEndSeconds.has_value()
            && placement.timelineEndSeconds.value() < placement.timelineStartSeconds) {
            addError(result, "invalid_placement_time", "Placement timelineEndSeconds precedes timelineStartSeconds: "
                                                     + placement.placementId);
        }
        if (!placement.trackId.empty()) {
            knownTrackIds.insert(placement.trackId.value);
        }
        if (!placement.placementId.empty()) {
            placementIds.insert(placement.placementId);
        }
        validateTempoPlan(placement.tempoPlan, "Placement " + placement.placementId, result);
    }

    for (const auto& transition : plan.transitions) {
        if (!placementIds.contains(transition.fromPlacementId)) {
            addError(result, "unknown_from_placement",
                     "Transition references unknown fromPlacementId: " + transition.fromPlacementId);
        }
        if (!placementIds.contains(transition.toPlacementId)) {
            addError(result, "unknown_to_placement",
                     "Transition references unknown toPlacementId: " + transition.toPlacementId);
        }
        if (transition.timelineEndSeconds < transition.timelineStartSeconds) {
            addError(result, "invalid_transition_time",
                     "Transition timelineEndSeconds precedes timelineStartSeconds: " + transition.transitionId);
        }
        if (transition.score < 0.0 || transition.score > 1.0) {
            addError(result, "invalid_transition_score", "Transition score must be between 0 and 1: "
                                                       + transition.transitionId);
        }
        validateTempoPlan(transition.tempoPlan, "Transition " + transition.transitionId, result);

        if (transition.templateId == "second_build_drop_switch_v1") {
            if (!transition.measureCountToTarget.has_value() || transition.measureCountToTarget.value() <= 0.0) {
                addError(result, "missing_measure_count",
                         "Second-build drop switch requires positive measureCountToTarget");
            }
            if (!transition.alignedDropTimelineSeconds.has_value()) {
                addError(result, "missing_aligned_drop",
                         "Second-build drop switch requires alignedDropTimelineSeconds");
            }
            if (!transition.handoffTimelineSeconds.has_value()) {
                addError(result, "missing_handoff", "Second-build drop switch requires handoffTimelineSeconds");
            }
            if (transition.alignedDropTimelineSeconds.has_value() && transition.handoffTimelineSeconds.has_value()
                && transition.handoffTimelineSeconds.value() > transition.alignedDropTimelineSeconds.value()) {
                addError(result, "invalid_handoff", "Second-build handoff must not occur after aligned drop");
            }
        }

        if (transition.technique == TransitionTechnique::DropEndReverbExit
            || transition.technique == TransitionTechnique::WashOut
            || transition.templateId == "drop_end_reverb_exit_v1"
            || transition.templateId == "drop_end_wash_out_v1") {
            if (!transition.measureCountToTarget.has_value() || transition.measureCountToTarget.value() <= 0.0) {
                addError(result, "missing_measure_count",
                         "Drop-end wash-out requires positive measureCountToTarget");
            }
            if (!transition.handoffTimelineSeconds.has_value()) {
                addError(result, "missing_handoff", "Drop-end wash-out requires handoffTimelineSeconds");
            }
            if (transition.handoffTimelineSeconds.has_value()
                && (transition.handoffTimelineSeconds.value() < transition.timelineStartSeconds
                    || transition.handoffTimelineSeconds.value() > transition.timelineEndSeconds)) {
                addError(result, "invalid_handoff", "Drop-end wash-out handoff must be inside transition range");
            }
        }

        for (const auto& [name, anchor] : transition.sourceAnchors) {
            if (!anchor.trackId.empty() && !knownTrackIds.contains(anchor.trackId.value)) {
                addWarning(result, "unknown_anchor_track",
                           "Transition anchor references unknown trackId: " + name + " -> " + anchor.trackId.value);
            }
        }
    }

    auto previousCommandAt = -1.0;
    for (const auto& command : plan.commands) {
        if (command.at < previousCommandAt) {
            addError(result, "commands_not_sorted", "MixPlan commands must be sorted by non-decreasing timeline time");
        }
        previousCommandAt = command.at;

        if (command.type == DeckCommandType::Load && !knownTrackIds.contains(command.trackId.value)) {
            addError(result, "unknown_command_track", "Load command references unknown trackId: " + command.trackId.value);
        }

        if (command.type == DeckCommandType::Automate) {
            auto previousKeyframeAt = -1.0;
            for (const auto& keyframe : command.keyframes) {
                if (keyframe.at < previousKeyframeAt) {
                    addError(result, "keyframes_not_sorted",
                             "Automation keyframes must be sorted by non-decreasing timeline time");
                }
                previousKeyframeAt = keyframe.at;
            }
        }
    }

    for (const auto& annotation : plan.annotations) {
        if (!annotation.placementId.empty() && !placementIds.contains(annotation.placementId)) {
            addWarning(result, "unknown_annotation_placement",
                       "Annotation references unknown placementId: " + annotation.placementId);
        }
    }
}

[[nodiscard]] MixPlan parseRootObject(const JsonValue& value, PlanValidationResult& result) {
    MixPlan plan;
    if (value.type != JsonValue::Type::Object) {
        addError(result, "invalid_root", "MixPlan JSON root must be an object");
        return plan;
    }

    const auto& object = value.objectValue;
    if (auto schemaVersion = requiredString(object, "schemaVersion", result)) {
        plan.schemaVersion = schemaVersion.value();
    }
    if (auto planId = requiredString(object, "planId", result)) {
        plan.planId = domain::PlanId{planId.value()};
    }
    if (auto createdAtUtc = requiredString(object, "createdAtUtc", result)) {
        plan.createdAtUtc = createdAtUtc.value();
    }

    if (const auto* strategy = requiredObject(object, "strategy", result)) {
        if (auto strategyId = requiredString(*strategy, "strategyId", result)) {
            plan.strategy.strategyId = strategyId.value();
        }
        if (auto strategyVersion = requiredString(*strategy, "strategyVersion", result)) {
            plan.strategy.strategyVersion = strategyVersion.value();
        }
        plan.strategy.randomSeed = optionalString(*strategy, "randomSeed", result);
    }

    if (const auto* assets = optionalArray(object, "assets", result)) {
        plan.assets.reserve(assets->size());
        for (const auto& item : *assets) {
            plan.assets.push_back(parseAsset(item, result));
        }
    }
    if (const auto* tracks = requiredArray(object, "tracks", result)) {
        plan.tracks.reserve(tracks->size());
        for (const auto& item : *tracks) {
            plan.tracks.push_back(parsePlacement(item, result));
        }
    }
    if (const auto* transitions = requiredArray(object, "transitions", result)) {
        plan.transitions.reserve(transitions->size());
        for (const auto& item : *transitions) {
            plan.transitions.push_back(parseTransition(item, result));
        }
    }
    if (const auto* commands = requiredArray(object, "commands", result)) {
        plan.commands.reserve(commands->size());
        for (const auto& item : *commands) {
            plan.commands.push_back(parseCommand(item, result));
        }
    }
    if (const auto* annotations = optionalArray(object, "annotations", result)) {
        plan.annotations.reserve(annotations->size());
        for (const auto& item : *annotations) {
            plan.annotations.push_back(parseAnnotation(item, result));
        }
    }

    validatePlan(plan, result);
    return plan;
}

}  // namespace

MixPlanParseResult parseMixPlan(std::string_view json) {
    MixPlanParseResult parseResult;
    if (isBlank(json)) {
        addError(parseResult.validation, "empty_plan", "PlaybackEngine requires a non-empty MixPlan JSON document.");
        return parseResult;
    }

    JsonParser parser{json};
    auto value = parser.parse();
    if (!value.has_value()) {
        addError(parseResult.validation, "malformed_json", parser.error());
        return parseResult;
    }

    auto plan = parseRootObject(value.value(), parseResult.validation);
    parseResult.validation.ok = parseResult.validation.errors.empty();
    if (parseResult.validation.ok) {
        parseResult.plan = std::move(plan);
    }
    return parseResult;
}

std::string toString(const TransitionTechnique technique) {
    switch (technique) {
        case TransitionTechnique::IntroOutroBlend:
            return "intro_outro_blend";
        case TransitionTechnique::BuildToDropSwap:
            return "build_to_drop_swap";
        case TransitionTechnique::DropEndReverbExit:
            return "drop_end_reverb_exit";
        case TransitionTechnique::WashOut:
            return "wash_out";
        case TransitionTechnique::LoopTighten:
            return "loop_tighten";
        case TransitionTechnique::VocalOverInstrumental:
            return "vocal_over_instrumental";
        case TransitionTechnique::EchoOut:
            return "echo_out";
        case TransitionTechnique::HardCut:
            return "hard_cut";
    }
    return "hard_cut";
}

std::string toString(const DeckCommandType type) {
    switch (type) {
        case DeckCommandType::Load:
            return "load";
        case DeckCommandType::Play:
            return "play";
        case DeckCommandType::Stop:
            return "stop";
        case DeckCommandType::Seek:
            return "seek";
        case DeckCommandType::SetLoop:
            return "setLoop";
        case DeckCommandType::ClearLoop:
            return "clearLoop";
        case DeckCommandType::Automate:
            return "automate";
    }
    return "play";
}

std::string toString(const AutomationControl control) {
    switch (control) {
        case AutomationControl::Volume:
            return "volume";
        case AutomationControl::EqLow:
            return "eqLow";
        case AutomationControl::EqMid:
            return "eqMid";
        case AutomationControl::EqHigh:
            return "eqHigh";
        case AutomationControl::Filter:
            return "filter";
        case AutomationControl::ReverbWet:
            return "reverbWet";
        case AutomationControl::ReverbTailGain:
            return "reverbTailGain";
        case AutomationControl::ReverbDecaySeconds:
            return "reverbDecaySeconds";
        case AutomationControl::EchoWet:
            return "echoWet";
        case AutomationControl::Tempo:
            return "tempo";
        case AutomationControl::Crossfader:
            return "crossfader";
    }
    return "volume";
}

}  // namespace autodj::playback
