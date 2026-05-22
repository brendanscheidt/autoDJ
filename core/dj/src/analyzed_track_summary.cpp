#include "autodj/dj/analyzed_track_summary.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <exception>
#include <fstream>
#include <map>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>

namespace autodj::dj {
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
                        fail("Only ASCII unicode escapes are supported in analyzed-track artifacts");
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

[[nodiscard]] AnalysisArtifactIssue makeIssue(std::string code, std::string message) {
    return AnalysisArtifactIssue{
        .code = std::move(code),
        .message = std::move(message),
    };
}

[[nodiscard]] TrackAnalysisSummaryReadResult errorResult(std::string code, std::string message) {
    TrackAnalysisSummaryReadResult result;
    result.errors.push_back(makeIssue(std::move(code), std::move(message)));
    return result;
}

[[nodiscard]] const JsonValue* field(const std::map<std::string, JsonValue>& object,
                                     const std::string& fieldName,
                                     const JsonValue::Type expectedType) {
    const auto iterator = object.find(fieldName);
    if (iterator == object.end() || iterator->second.type != expectedType) {
        return nullptr;
    }
    return &iterator->second;
}

[[nodiscard]] std::optional<std::string> requiredString(const std::map<std::string, JsonValue>& object,
                                                        const std::string& fieldName,
                                                        std::string& errorMessage) {
    const auto* value = field(object, fieldName, JsonValue::Type::String);
    if (value == nullptr || value->stringValue.empty()) {
        errorMessage = "Missing required string field: " + fieldName;
        return std::nullopt;
    }
    return value->stringValue;
}

[[nodiscard]] std::string optionalString(const std::map<std::string, JsonValue>& object,
                                         const std::string& fieldName) {
    const auto* value = field(object, fieldName, JsonValue::Type::String);
    if (value == nullptr) {
        return {};
    }
    return value->stringValue;
}

[[nodiscard]] bool isFiniteNonNegative(const double value) {
    return std::isfinite(value) && value >= 0.0;
}

[[nodiscard]] bool isConfidence(const double value) {
    return std::isfinite(value) && value >= 0.0 && value <= 1.0;
}

[[nodiscard]] std::optional<double> requiredPositiveNumber(const std::map<std::string, JsonValue>& object,
                                                           const std::string& fieldName,
                                                           std::string& errorMessage) {
    const auto* value = field(object, fieldName, JsonValue::Type::Number);
    if (value == nullptr || !std::isfinite(value->numberValue) || value->numberValue <= 0.0) {
        errorMessage = "Missing required positive number field: " + fieldName;
        return std::nullopt;
    }
    return value->numberValue;
}

[[nodiscard]] std::optional<double> requiredNonNegativeNumber(const std::map<std::string, JsonValue>& object,
                                                              const std::string& fieldName,
                                                              std::string& errorMessage) {
    const auto* value = field(object, fieldName, JsonValue::Type::Number);
    if (value == nullptr || !isFiniteNonNegative(value->numberValue)) {
        errorMessage = "Missing required non-negative number field: " + fieldName;
        return std::nullopt;
    }
    return value->numberValue;
}

[[nodiscard]] std::optional<double> optionalNonNegativeNumber(const std::map<std::string, JsonValue>& object,
                                                              const std::string& fieldName,
                                                              std::string& errorMessage) {
    const auto iterator = object.find(fieldName);
    if (iterator == object.end()) {
        return std::nullopt;
    }
    if (iterator->second.type != JsonValue::Type::Number || !isFiniteNonNegative(iterator->second.numberValue)) {
        errorMessage = "Invalid non-negative number field: " + fieldName;
        return std::nullopt;
    }
    return iterator->second.numberValue;
}

[[nodiscard]] std::optional<double> optionalConfidence(const std::map<std::string, JsonValue>& object,
                                                       const std::string& fieldName,
                                                       std::string& errorMessage) {
    const auto iterator = object.find(fieldName);
    if (iterator == object.end()) {
        return std::nullopt;
    }
    if (iterator->second.type != JsonValue::Type::Number || !isConfidence(iterator->second.numberValue)) {
        errorMessage = "Invalid confidence field: " + fieldName;
        return std::nullopt;
    }
    return iterator->second.numberValue;
}

[[nodiscard]] std::optional<int> optionalNonNegativeInteger(const std::map<std::string, JsonValue>& object,
                                                            const std::string& fieldName,
                                                            std::string& errorMessage) {
    const auto iterator = object.find(fieldName);
    if (iterator == object.end()) {
        return std::nullopt;
    }
    if (iterator->second.type != JsonValue::Type::Number || iterator->second.numberValue < 0.0
        || std::floor(iterator->second.numberValue) != iterator->second.numberValue) {
        errorMessage = "Invalid non-negative integer field: " + fieldName;
        return std::nullopt;
    }
    return static_cast<int>(iterator->second.numberValue);
}

[[nodiscard]] std::optional<int> optionalPositiveInteger(const std::map<std::string, JsonValue>& object,
                                                         const std::string& fieldName,
                                                         std::string& errorMessage) {
    const auto iterator = object.find(fieldName);
    if (iterator == object.end()) {
        return std::nullopt;
    }
    if (iterator->second.type != JsonValue::Type::Number || iterator->second.numberValue < 1.0
        || std::floor(iterator->second.numberValue) != iterator->second.numberValue) {
        errorMessage = "Invalid positive integer field: " + fieldName;
        return std::nullopt;
    }
    return static_cast<int>(iterator->second.numberValue);
}

[[nodiscard]] std::optional<AnalyzedBeat> parseBeat(const JsonValue& value, std::string& errorMessage) {
    if (value.type != JsonValue::Type::Object) {
        errorMessage = "Beat marker must be an object";
        return std::nullopt;
    }

    auto index = optionalNonNegativeInteger(value.objectValue, "index", errorMessage);
    if (!index.has_value()) {
        return std::nullopt;
    }
    auto timeSeconds = requiredNonNegativeNumber(value.objectValue, "timeSeconds", errorMessage);
    if (!timeSeconds.has_value()) {
        return std::nullopt;
    }
    auto beatInBar = optionalPositiveInteger(value.objectValue, "beatInBar", errorMessage);
    if (!beatInBar.has_value() && !errorMessage.empty()) {
        return std::nullopt;
    }
    auto confidence = optionalConfidence(value.objectValue, "confidence", errorMessage);
    if (!confidence.has_value() && !errorMessage.empty()) {
        return std::nullopt;
    }

    return AnalyzedBeat{
        .index = index.value(),
        .timeSeconds = timeSeconds.value(),
        .beatInBar = beatInBar,
        .confidence = confidence,
    };
}

[[nodiscard]] std::optional<AnalyzedSection> parseSection(const JsonValue& value, std::string& errorMessage) {
    if (value.type != JsonValue::Type::Object) {
        errorMessage = "Track section must be an object";
        return std::nullopt;
    }

    auto id = requiredString(value.objectValue, "id", errorMessage);
    if (!id.has_value()) {
        return std::nullopt;
    }
    auto type = requiredString(value.objectValue, "type", errorMessage);
    if (!type.has_value()) {
        return std::nullopt;
    }
    auto startSeconds = requiredNonNegativeNumber(value.objectValue, "startSeconds", errorMessage);
    if (!startSeconds.has_value()) {
        return std::nullopt;
    }
    auto endSeconds = requiredNonNegativeNumber(value.objectValue, "endSeconds", errorMessage);
    if (!endSeconds.has_value()) {
        return std::nullopt;
    }
    if (endSeconds.value() <= startSeconds.value()) {
        errorMessage = "Track section endSeconds must be after startSeconds";
        return std::nullopt;
    }
    auto startBeatIndex = optionalNonNegativeInteger(value.objectValue, "startBeatIndex", errorMessage);
    if (!startBeatIndex.has_value() && !errorMessage.empty()) {
        return std::nullopt;
    }
    auto endBeatIndex = optionalNonNegativeInteger(value.objectValue, "endBeatIndex", errorMessage);
    if (!endBeatIndex.has_value() && !errorMessage.empty()) {
        return std::nullopt;
    }
    auto confidence = optionalConfidence(value.objectValue, "confidence", errorMessage);
    if (!confidence.has_value() && !errorMessage.empty()) {
        return std::nullopt;
    }

    return AnalyzedSection{
        .id = std::move(id.value()),
        .type = std::move(type.value()),
        .startSeconds = startSeconds.value(),
        .endSeconds = endSeconds.value(),
        .startBeatIndex = startBeatIndex,
        .endBeatIndex = endBeatIndex,
        .confidence = confidence,
    };
}

[[nodiscard]] std::optional<AnalyzedCuePoint> parseCuePoint(const JsonValue& value, std::string& errorMessage) {
    if (value.type != JsonValue::Type::Object) {
        errorMessage = "Cue point must be an object";
        return std::nullopt;
    }

    auto id = requiredString(value.objectValue, "id", errorMessage);
    if (!id.has_value()) {
        return std::nullopt;
    }
    auto type = requiredString(value.objectValue, "type", errorMessage);
    if (!type.has_value()) {
        return std::nullopt;
    }
    auto timeSeconds = requiredNonNegativeNumber(value.objectValue, "timeSeconds", errorMessage);
    if (!timeSeconds.has_value()) {
        return std::nullopt;
    }
    auto beatIndex = optionalNonNegativeInteger(value.objectValue, "beatIndex", errorMessage);
    if (!beatIndex.has_value() && !errorMessage.empty()) {
        return std::nullopt;
    }
    auto confidence = optionalConfidence(value.objectValue, "confidence", errorMessage);
    if (!confidence.has_value() && !errorMessage.empty()) {
        return std::nullopt;
    }

    std::vector<std::string> tags;
    if (const auto* tagsValue = field(value.objectValue, "tags", JsonValue::Type::Array); tagsValue != nullptr) {
        for (const auto& tag : tagsValue->arrayValue) {
            if (tag.type != JsonValue::Type::String) {
                errorMessage = "Cue point tags must be strings";
                return std::nullopt;
            }
            tags.push_back(tag.stringValue);
        }
    }

    return AnalyzedCuePoint{
        .id = std::move(id.value()),
        .type = std::move(type.value()),
        .timeSeconds = timeSeconds.value(),
        .beatIndex = beatIndex,
        .sectionId = optionalString(value.objectValue, "sectionId"),
        .confidence = confidence,
        .tags = std::move(tags),
    };
}

void addReaderWarning(TrackAnalysisSummaryReadResult& result,
                      TrackAnalysisSummary& summary,
                      std::string code,
                      std::string message) {
    result.warnings.push_back(makeIssue(code, message));
    summary.qualityWarnings.push_back(message);
}

void addRiskFlag(TrackAnalysisSummary& summary, std::string flag) {
    if (std::find(summary.riskFlags.begin(), summary.riskFlags.end(), flag) == summary.riskFlags.end()) {
        summary.riskFlags.push_back(std::move(flag));
    }
}

void addConfidenceRiskFlags(TrackAnalysisSummary& summary) {
    constexpr double complexTransitionThreshold = 0.85;
    constexpr double simpleTransitionThreshold = 0.65;

    if (summary.tempoConfidence > 0.0 && summary.tempoConfidence < simpleTransitionThreshold) {
        addRiskFlag(summary, "low_tempo_confidence");
    } else if (summary.tempoConfidence > 0.0 && summary.tempoConfidence < complexTransitionThreshold) {
        addRiskFlag(summary, "medium_tempo_confidence");
    }

    if (summary.beatGridConfidence > 0.0 && summary.beatGridConfidence < simpleTransitionThreshold) {
        addRiskFlag(summary, "low_beat_grid_confidence");
    } else if (summary.beatGridConfidence > 0.0 && summary.beatGridConfidence < complexTransitionThreshold) {
        addRiskFlag(summary, "medium_beat_grid_confidence");
    }

    if (summary.overallConfidence > 0.0 && summary.overallConfidence < simpleTransitionThreshold) {
        addRiskFlag(summary, "low_overall_analysis_confidence");
    } else if (summary.overallConfidence > 0.0 && summary.overallConfidence < complexTransitionThreshold) {
        addRiskFlag(summary, "medium_overall_analysis_confidence");
    }

    if (summary.builds.empty()) {
        addRiskFlag(summary, "missing_build_sections");
    }
    if (summary.drops.empty()) {
        addRiskFlag(summary, "missing_drop_sections");
    }
}

}  // namespace

TrackAnalysisSummaryReadResult parseTrackAnalysisSummary(std::string_view json, std::string sourceUri) {
    JsonParser parser{json};
    auto root = parser.parse();
    if (!root.has_value()) {
        return errorResult("invalid_json", parser.error());
    }
    if (root->type != JsonValue::Type::Object) {
        return errorResult("invalid_artifact", "AnalyzedTrack artifact root must be an object");
    }

    TrackAnalysisSummaryReadResult result;
    TrackAnalysisSummary summary;
    std::string errorMessage;

    auto trackId = requiredString(root->objectValue, "trackId", errorMessage);
    if (!trackId.has_value()) {
        return errorResult("invalid_artifact", errorMessage);
    }
    summary.trackId = domain::TrackId{std::move(trackId.value())};
    summary.sourceUri = std::move(sourceUri);

    if (const auto* source = field(root->objectValue, "source", JsonValue::Type::Object); source != nullptr) {
        const auto artifactSourceUri = optionalString(source->objectValue, "sourceUri");
        if (!artifactSourceUri.empty()) {
            summary.sourceUri = artifactSourceUri;
        }
    }
    if (summary.sourceUri.empty()) {
        addReaderWarning(result, summary, "missing_source_uri", "AnalyzedTrack artifact did not include source.sourceUri");
    }

    auto durationSeconds = optionalNonNegativeNumber(root->objectValue, "durationSeconds", errorMessage);
    if (!durationSeconds.has_value() && !errorMessage.empty()) {
        return errorResult("invalid_artifact", errorMessage);
    }
    summary.durationSeconds = durationSeconds;

    const auto* tempo = field(root->objectValue, "tempo", JsonValue::Type::Object);
    if (tempo == nullptr) {
        return errorResult("invalid_artifact", "Missing required object field: tempo");
    }
    auto normalizedBpm = requiredPositiveNumber(tempo->objectValue, "normalizedBpm", errorMessage);
    if (!normalizedBpm.has_value()) {
        return errorResult("invalid_artifact", errorMessage);
    }
    summary.normalizedBpm = normalizedBpm.value();

    auto rawBpm = optionalNonNegativeNumber(tempo->objectValue, "bpm", errorMessage);
    if (!rawBpm.has_value() && !errorMessage.empty()) {
        return errorResult("invalid_artifact", errorMessage);
    }
    summary.rawBpm = rawBpm;

    auto tempoConfidence = optionalConfidence(tempo->objectValue, "confidence", errorMessage);
    if (!tempoConfidence.has_value() && !errorMessage.empty()) {
        return errorResult("invalid_artifact", errorMessage);
    }
    if (tempoConfidence.has_value()) {
        summary.tempoConfidence = tempoConfidence.value();
    } else {
        addReaderWarning(result, summary, "missing_tempo_confidence", "Tempo confidence is missing");
    }

    const auto* beatGrid = field(root->objectValue, "beatGrid", JsonValue::Type::Object);
    if (beatGrid == nullptr) {
        return errorResult("invalid_artifact", "Missing required object field: beatGrid");
    }
    auto beatGridConfidence = optionalConfidence(beatGrid->objectValue, "confidence", errorMessage);
    if (!beatGridConfidence.has_value() && !errorMessage.empty()) {
        return errorResult("invalid_artifact", errorMessage);
    }
    if (beatGridConfidence.has_value()) {
        summary.beatGridConfidence = beatGridConfidence.value();
    } else {
        addReaderWarning(result, summary, "missing_beat_grid_confidence", "Beat grid confidence is missing");
    }

    const auto* beats = field(beatGrid->objectValue, "beats", JsonValue::Type::Array);
    if (beats == nullptr) {
        return errorResult("invalid_artifact", "Missing required array field: beatGrid.beats");
    }
    for (const auto& beat : beats->arrayValue) {
        auto parsedBeat = parseBeat(beat, errorMessage);
        if (!parsedBeat.has_value()) {
            return errorResult("invalid_artifact", errorMessage);
        }
        summary.beats.push_back(std::move(parsedBeat.value()));
    }
    if (summary.beats.empty()) {
        return errorResult("invalid_artifact", "beatGrid.beats must include at least one beat");
    }
    std::sort(summary.beats.begin(), summary.beats.end(), [](const AnalyzedBeat& lhs, const AnalyzedBeat& rhs) {
        if (lhs.timeSeconds == rhs.timeSeconds) {
            return lhs.index < rhs.index;
        }
        return lhs.timeSeconds < rhs.timeSeconds;
    });

    const auto* sections = field(root->objectValue, "sections", JsonValue::Type::Array);
    if (sections == nullptr) {
        return errorResult("invalid_artifact", "Missing required array field: sections");
    }
    for (const auto& section : sections->arrayValue) {
        auto parsedSection = parseSection(section, errorMessage);
        if (!parsedSection.has_value()) {
            return errorResult("invalid_artifact", errorMessage);
        }
        if (parsedSection->type == "build") {
            summary.builds.push_back(std::move(parsedSection.value()));
        } else if (parsedSection->type == "drop") {
            summary.drops.push_back(std::move(parsedSection.value()));
        }
    }
    const auto sectionStartLess = [](const AnalyzedSection& lhs, const AnalyzedSection& rhs) {
        if (lhs.startSeconds == rhs.startSeconds) {
            return lhs.id < rhs.id;
        }
        return lhs.startSeconds < rhs.startSeconds;
    };
    std::sort(summary.builds.begin(), summary.builds.end(), sectionStartLess);
    std::sort(summary.drops.begin(), summary.drops.end(), sectionStartLess);

    const auto* cuePoints = field(root->objectValue, "cuePoints", JsonValue::Type::Array);
    if (cuePoints == nullptr) {
        return errorResult("invalid_artifact", "Missing required array field: cuePoints");
    }
    for (const auto& cuePoint : cuePoints->arrayValue) {
        auto parsedCuePoint = parseCuePoint(cuePoint, errorMessage);
        if (!parsedCuePoint.has_value()) {
            return errorResult("invalid_artifact", errorMessage);
        }
        summary.cuePoints.push_back(std::move(parsedCuePoint.value()));
    }
    std::sort(summary.cuePoints.begin(), summary.cuePoints.end(), [](const AnalyzedCuePoint& lhs,
                                                                     const AnalyzedCuePoint& rhs) {
        if (lhs.timeSeconds == rhs.timeSeconds) {
            return lhs.id < rhs.id;
        }
        return lhs.timeSeconds < rhs.timeSeconds;
    });

    if (const auto* quality = field(root->objectValue, "quality", JsonValue::Type::Object); quality != nullptr) {
        auto overallConfidence = optionalConfidence(quality->objectValue, "overallConfidence", errorMessage);
        if (!overallConfidence.has_value() && !errorMessage.empty()) {
            return errorResult("invalid_artifact", errorMessage);
        }
        if (overallConfidence.has_value()) {
            summary.overallConfidence = overallConfidence.value();
        } else {
            addReaderWarning(result, summary, "missing_overall_confidence", "Overall analysis confidence is missing");
        }

        if (const auto* warnings = field(quality->objectValue, "warnings", JsonValue::Type::Array); warnings != nullptr) {
            for (const auto& warning : warnings->arrayValue) {
                if (warning.type != JsonValue::Type::String) {
                    return errorResult("invalid_artifact", "quality.warnings entries must be strings");
                }
                summary.qualityWarnings.push_back(warning.stringValue);
            }
        }
    } else {
        addReaderWarning(result, summary, "missing_quality", "AnalyzedTrack artifact did not include quality metadata");
    }

    addConfidenceRiskFlags(summary);
    result.summary = std::move(summary);
    return result;
}

TrackAnalysisSummaryReadResult readTrackAnalysisSummary(const std::filesystem::path& artifactPath) {
    std::ifstream file{artifactPath};
    if (!file) {
        return errorResult("read_failed", "Could not open analyzed-track artifact: " + artifactPath.string());
    }

    std::ostringstream buffer;
    buffer << file.rdbuf();
    if (!file.good() && !file.eof()) {
        return errorResult("read_failed", "Could not read analyzed-track artifact: " + artifactPath.string());
    }

    return parseTrackAnalysisSummary(buffer.str(), artifactPath.string());
}

}  // namespace autodj::dj
