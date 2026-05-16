#include "autodj/repository/repository_manifest_reader.hpp"

#include <cctype>
#include <cmath>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace autodj::repository {
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
    explicit JsonParser(std::string_view input) : input_(input) {}

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

    [[nodiscard]] bool consume(char expected) {
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
                        fail("Only ASCII unicode escapes are supported in repository manifests");
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

RepositoryError makeReadError(std::string code, std::string message, const std::string& sourceUri = {}) {
    RepositoryError error{
        .code = std::move(code),
        .message = std::move(message),
    };
    if (!sourceUri.empty()) {
        error.sourceUri = sourceUri;
    }
    return error;
}

RepositoryManifestReadResult errorResult(std::string code,
                                         std::string message,
                                         const std::string& sourceUri,
                                         const std::filesystem::path& manifestPath = {}) {
    return RepositoryManifestReadResult{
        .manifestPath = manifestPath,
        .manifest = std::nullopt,
        .error = makeReadError(std::move(code), std::move(message), sourceUri),
    };
}

[[nodiscard]] const JsonValue* objectField(const JsonValue::Type expectedType,
                                           const std::map<std::string, JsonValue>& object,
                                           const std::string& field) {
    const auto iterator = object.find(field);
    if (iterator == object.end() || iterator->second.type != expectedType) {
        return nullptr;
    }
    return &iterator->second;
}

[[nodiscard]] std::optional<std::string> requiredString(const std::map<std::string, JsonValue>& object,
                                                        const std::string& field,
                                                        std::string& errorMessage) {
    const auto* value = objectField(JsonValue::Type::String, object, field);
    if (value == nullptr || value->stringValue.empty()) {
        errorMessage = "Missing required string field: " + field;
        return std::nullopt;
    }
    return value->stringValue;
}

[[nodiscard]] std::string optionalString(const std::map<std::string, JsonValue>& object, const std::string& field) {
    const auto* value = objectField(JsonValue::Type::String, object, field);
    if (value == nullptr) {
        return {};
    }
    return value->stringValue;
}

[[nodiscard]] std::optional<double> optionalNumber(const std::map<std::string, JsonValue>& object,
                                                   const std::string& field,
                                                   std::string& errorMessage) {
    const auto iterator = object.find(field);
    if (iterator == object.end()) {
        return std::nullopt;
    }
    if (iterator->second.type != JsonValue::Type::Number || iterator->second.numberValue < 0.0) {
        errorMessage = "Invalid non-negative number field: " + field;
        return std::nullopt;
    }
    return iterator->second.numberValue;
}

[[nodiscard]] std::optional<int> optionalPositiveInteger(const std::map<std::string, JsonValue>& object,
                                                         const std::string& field,
                                                         std::string& errorMessage) {
    const auto iterator = object.find(field);
    if (iterator == object.end()) {
        return std::nullopt;
    }
    if (iterator->second.type != JsonValue::Type::Number || iterator->second.numberValue < 1.0
        || std::floor(iterator->second.numberValue) != iterator->second.numberValue) {
        errorMessage = "Invalid positive integer field: " + field;
        return std::nullopt;
    }
    return static_cast<int>(iterator->second.numberValue);
}

[[nodiscard]] std::optional<std::size_t> requiredCount(const std::map<std::string, JsonValue>& object,
                                                       const std::string& field,
                                                       std::string& errorMessage) {
    const auto* value = objectField(JsonValue::Type::Number, object, field);
    if (value == nullptr || value->numberValue < 0.0 || std::floor(value->numberValue) != value->numberValue) {
        errorMessage = "Missing required non-negative integer field: " + field;
        return std::nullopt;
    }
    return static_cast<std::size_t>(value->numberValue);
}

[[nodiscard]] std::optional<RepositorySource> parseSource(const JsonValue& value, std::string& errorMessage) {
    if (value.type != JsonValue::Type::Object) {
        errorMessage = "Missing required object field: source";
        return std::nullopt;
    }

    auto repositoryType = requiredString(value.objectValue, "repositoryType", errorMessage);
    if (!repositoryType.has_value()) {
        return std::nullopt;
    }
    auto rootUri = requiredString(value.objectValue, "rootUri", errorMessage);
    if (!rootUri.has_value()) {
        return std::nullopt;
    }

    return RepositorySource{
        .repositoryType = std::move(repositoryType.value()),
        .rootUri = std::move(rootUri.value()),
    };
}

[[nodiscard]] std::optional<TrackAsset> parseTrack(const JsonValue& value, std::string& errorMessage) {
    if (value.type != JsonValue::Type::Object) {
        errorMessage = "Track entry is not an object";
        return std::nullopt;
    }

    auto trackId = requiredString(value.objectValue, "trackId", errorMessage);
    if (!trackId.has_value()) {
        return std::nullopt;
    }
    auto repositoryId = requiredString(value.objectValue, "repositoryId", errorMessage);
    if (!repositoryId.has_value()) {
        return std::nullopt;
    }
    auto sourceUri = requiredString(value.objectValue, "sourceUri", errorMessage);
    if (!sourceUri.has_value()) {
        return std::nullopt;
    }

    auto durationSeconds = optionalNumber(value.objectValue, "durationSeconds", errorMessage);
    if (!errorMessage.empty()) {
        return std::nullopt;
    }
    auto sampleRate = optionalPositiveInteger(value.objectValue, "sampleRate", errorMessage);
    if (!errorMessage.empty()) {
        return std::nullopt;
    }
    auto channels = optionalPositiveInteger(value.objectValue, "channels", errorMessage);
    if (!errorMessage.empty()) {
        return std::nullopt;
    }

    TrackAsset track{
        .trackId = domain::TrackId{std::move(trackId.value())},
        .repositoryId = std::move(repositoryId.value()),
        .sourcePath = {},
        .sourceUri = std::move(sourceUri.value()),
        .contentHash = optionalString(value.objectValue, "contentHash"),
        .formatHint = optionalString(value.objectValue, "formatHint"),
        .durationSeconds = durationSeconds,
        .sampleRate = sampleRate,
        .channels = channels,
    };
    if (track.formatHint.empty()) {
        track.formatHint = "unknown";
    }

    const auto title = optionalString(value.objectValue, "title");
    if (!title.empty()) {
        track.title = title;
    }
    const auto artist = optionalString(value.objectValue, "artist");
    if (!artist.empty()) {
        track.artist = artist;
    }
    const auto album = optionalString(value.objectValue, "album");
    if (!album.empty()) {
        track.album = album;
    }

    return track;
}

[[nodiscard]] std::optional<RepositoryError> parseRepositoryError(const JsonValue& value, std::string& errorMessage) {
    if (value.type != JsonValue::Type::Object) {
        errorMessage = "Repository error entry is not an object";
        return std::nullopt;
    }

    auto code = requiredString(value.objectValue, "code", errorMessage);
    if (!code.has_value()) {
        return std::nullopt;
    }
    auto message = requiredString(value.objectValue, "message", errorMessage);
    if (!message.has_value()) {
        return std::nullopt;
    }

    RepositoryError error{
        .code = std::move(code.value()),
        .message = std::move(message.value()),
    };

    const auto sourceUri = optionalString(value.objectValue, "sourceUri");
    if (!sourceUri.empty()) {
        error.sourceUri = sourceUri;
    }
    const auto trackId = optionalString(value.objectValue, "trackId");
    if (!trackId.empty()) {
        error.trackId = domain::TrackId{trackId};
    }

    return error;
}

[[nodiscard]] std::optional<RepositoryScanSummary> parseScanSummary(const JsonValue& value, std::string& errorMessage) {
    if (value.type != JsonValue::Type::Object) {
        errorMessage = "Missing required object field: scan";
        return std::nullopt;
    }

    auto repositoryId = requiredString(value.objectValue, "repositoryId", errorMessage);
    if (!repositoryId.has_value()) {
        return std::nullopt;
    }
    auto tracksAdded = requiredCount(value.objectValue, "tracksAdded", errorMessage);
    if (!tracksAdded.has_value()) {
        return std::nullopt;
    }
    auto tracksUpdated = requiredCount(value.objectValue, "tracksUpdated", errorMessage);
    if (!tracksUpdated.has_value()) {
        return std::nullopt;
    }
    auto tracksRemoved = requiredCount(value.objectValue, "tracksRemoved", errorMessage);
    if (!tracksRemoved.has_value()) {
        return std::nullopt;
    }

    const auto* errors = objectField(JsonValue::Type::Array, value.objectValue, "errors");
    if (errors == nullptr) {
        errorMessage = "Missing required array field: errors";
        return std::nullopt;
    }

    std::vector<RepositoryError> parsedErrors;
    parsedErrors.reserve(errors->arrayValue.size());
    for (const auto& errorValue : errors->arrayValue) {
        auto parsedError = parseRepositoryError(errorValue, errorMessage);
        if (!parsedError.has_value()) {
            return std::nullopt;
        }
        parsedErrors.push_back(std::move(parsedError.value()));
    }

    return RepositoryScanSummary{
        .repositoryId = std::move(repositoryId.value()),
        .tracksAdded = tracksAdded.value(),
        .tracksUpdated = tracksUpdated.value(),
        .tracksRemoved = tracksRemoved.value(),
        .errors = std::move(parsedErrors),
    };
}

[[nodiscard]] std::optional<RepositoryManifest> manifestFromJsonValue(const JsonValue& value, std::string& errorMessage) {
    if (value.type != JsonValue::Type::Object) {
        errorMessage = "Repository manifest root must be an object";
        return std::nullopt;
    }

    auto schemaVersion = requiredString(value.objectValue, "schemaVersion", errorMessage);
    if (!schemaVersion.has_value()) {
        return std::nullopt;
    }
    if (schemaVersion.value() != "1.0.0") {
        errorMessage = "Unsupported repository manifest schema version: " + schemaVersion.value();
        return std::nullopt;
    }

    auto repositoryId = requiredString(value.objectValue, "repositoryId", errorMessage);
    if (!repositoryId.has_value()) {
        return std::nullopt;
    }
    auto producer = requiredString(value.objectValue, "producer", errorMessage);
    if (!producer.has_value()) {
        return std::nullopt;
    }
    auto producerVersion = requiredString(value.objectValue, "producerVersion", errorMessage);
    if (!producerVersion.has_value()) {
        return std::nullopt;
    }
    auto createdAtUtc = requiredString(value.objectValue, "createdAtUtc", errorMessage);
    if (!createdAtUtc.has_value()) {
        return std::nullopt;
    }

    const auto sourceIterator = value.objectValue.find("source");
    if (sourceIterator == value.objectValue.end()) {
        errorMessage = "Missing required object field: source";
        return std::nullopt;
    }
    auto source = parseSource(sourceIterator->second, errorMessage);
    if (!source.has_value()) {
        return std::nullopt;
    }

    const auto* tracks = objectField(JsonValue::Type::Array, value.objectValue, "tracks");
    if (tracks == nullptr) {
        errorMessage = "Missing required array field: tracks";
        return std::nullopt;
    }

    std::vector<TrackAsset> parsedTracks;
    parsedTracks.reserve(tracks->arrayValue.size());
    for (const auto& trackValue : tracks->arrayValue) {
        auto parsedTrack = parseTrack(trackValue, errorMessage);
        if (!parsedTrack.has_value()) {
            return std::nullopt;
        }
        parsedTracks.push_back(std::move(parsedTrack.value()));
    }

    const auto scanIterator = value.objectValue.find("scan");
    if (scanIterator == value.objectValue.end()) {
        errorMessage = "Missing required object field: scan";
        return std::nullopt;
    }
    auto scan = parseScanSummary(scanIterator->second, errorMessage);
    if (!scan.has_value()) {
        return std::nullopt;
    }

    return RepositoryManifest{
        .schemaVersion = std::move(schemaVersion.value()),
        .repositoryId = std::move(repositoryId.value()),
        .producer = std::move(producer.value()),
        .producerVersion = std::move(producerVersion.value()),
        .createdAtUtc = std::move(createdAtUtc.value()),
        .source = std::move(source.value()),
        .tracks = std::move(parsedTracks),
        .scan = std::move(scan.value()),
    };
}

}  // namespace

RepositoryManifestReadResult parseRepositoryManifest(std::string_view json, std::string sourceUri) {
    JsonParser parser{json};
    auto value = parser.parse();
    if (!value.has_value()) {
        return errorResult("manifest_parse_error", parser.error(), sourceUri);
    }

    std::string errorMessage;
    auto manifest = manifestFromJsonValue(value.value(), errorMessage);
    if (!manifest.has_value()) {
        const auto code = errorMessage.find("Unsupported repository manifest schema version") == 0
                              ? "manifest_schema_unsupported"
                              : "manifest_missing_field";
        return errorResult(code, errorMessage, sourceUri);
    }

    return RepositoryManifestReadResult{
        .manifestPath = {},
        .manifest = std::move(manifest.value()),
        .error = std::nullopt,
    };
}

RepositoryManifestReadResult readRepositoryManifest(const std::filesystem::path& manifestPath) {
    const auto normalizedPath = manifestPath.lexically_normal();
    const auto sourceUri = normalizedPath.generic_string();

    std::ifstream file{normalizedPath, std::ios::binary};
    if (!file) {
        return errorResult("manifest_read_error", "Could not open repository manifest for reading", sourceUri, normalizedPath);
    }

    std::ostringstream contents;
    contents << file.rdbuf();
    if (!file.good() && !file.eof()) {
        return errorResult("manifest_read_error", "Could not read repository manifest", sourceUri, normalizedPath);
    }

    auto result = parseRepositoryManifest(contents.str(), sourceUri);
    result.manifestPath = normalizedPath;
    return result;
}

RepositoryManifestReadResult readRepositoryManifest(const MetadataCachePaths& cachePaths) {
    return readRepositoryManifest(cachePaths.repositoryManifestPath());
}

}  // namespace autodj::repository
