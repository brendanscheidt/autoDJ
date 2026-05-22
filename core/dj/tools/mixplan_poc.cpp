#include "autodj/dj/dj.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace {

struct CliOptions final {
    std::filesystem::path outDir;
    std::filesystem::path outgoingArtifact;
    std::vector<std::filesystem::path> incomingArtifacts;
    autodj::dj::DubstepPocPlanOptions planOptions;
    bool json{false};
};

void printUsage(std::ostream& output) {
    output << "usage: autodj_mixplan_poc --out <dir> [--plan-id <id>] [--created-at <utc>] [--random-seed <seed>] "
              "[--json] <outgoing-analyzed-track.json> <incoming-analyzed-track.json>...\n";
}

[[nodiscard]] bool isOption(const std::string_view value) {
    return value.size() > 1 && value[0] == '-';
}

[[nodiscard]] std::string jsonString(const std::string& value) {
    std::ostringstream output;
    output << '"';
    for (const auto character : value) {
        switch (character) {
            case '"':
                output << "\\\"";
                break;
            case '\\':
                output << "\\\\";
                break;
            case '\n':
                output << "\\n";
                break;
            case '\r':
                output << "\\r";
                break;
            case '\t':
                output << "\\t";
                break;
            default:
                output << character;
                break;
        }
    }
    output << '"';
    return output.str();
}

[[nodiscard]] CliOptions parseArgs(const int argc, char* argv[]) {
    CliOptions options;
    std::vector<std::filesystem::path> positionals;

    for (auto index = 1; index < argc; ++index) {
        const std::string arg = argv[index];
        if (arg == "--help" || arg == "-h") {
            printUsage(std::cout);
            std::exit(0);
        }
        if (arg == "--json") {
            options.json = true;
            continue;
        }
        if (arg == "--out" || arg == "--plan-id" || arg == "--created-at" || arg == "--random-seed") {
            if (index + 1 >= argc || isOption(argv[index + 1])) {
                throw std::invalid_argument(arg + " requires a value");
            }
            const std::string value = argv[++index];
            if (arg == "--out") {
                options.outDir = value;
            } else if (arg == "--plan-id") {
                options.planOptions.planId = autodj::domain::PlanId{value};
            } else if (arg == "--created-at") {
                options.planOptions.createdAtUtc = value;
            } else {
                options.planOptions.randomSeed = value;
            }
            continue;
        }
        if (isOption(arg)) {
            throw std::invalid_argument("Unknown option: " + arg);
        }
        positionals.emplace_back(arg);
    }

    if (options.outDir.empty()) {
        throw std::invalid_argument("--out is required");
    }
    if (positionals.size() < 2) {
        throw std::invalid_argument("one outgoing artifact and at least one incoming artifact are required");
    }
    options.outgoingArtifact = positionals.front();
    options.incomingArtifacts.assign(positionals.begin() + 1, positionals.end());
    return options;
}

[[nodiscard]] autodj::dj::TrackAnalysisSummary readArtifactOrThrow(const std::filesystem::path& path) {
    auto result = autodj::dj::readTrackAnalysisSummary(path);
    if (!result.ok()) {
        std::ostringstream message;
        message << "Could not read analyzed-track artifact " << path << ":";
        for (const auto& error : result.errors) {
            message << " " << error.code << " (" << error.message << ")";
        }
        throw std::runtime_error(message.str());
    }
    return std::move(result.summary.value());
}

void writeTextFile(const std::filesystem::path& path, const std::string& content) {
    std::ofstream file{path, std::ios::binary};
    if (!file) {
        throw std::runtime_error("Could not open output file: " + path.string());
    }
    file << content;
}

[[nodiscard]] std::string summaryJson(const autodj::dj::DubstepPocPlanResult& result,
                                      const std::filesystem::path& outDir) {
    std::ostringstream output;
    output << "{\n";
    output << "  \"ok\": " << (result.ok() ? "true" : "false") << ",\n";
    output << "  \"outDir\": " << jsonString(outDir.generic_string()) << ",\n";
    output << "  \"mixPlanPath\": " << jsonString((outDir / "mix-plan.json").generic_string()) << ",\n";
    output << "  \"selectedTemplateId\": " << jsonString(result.selectedTemplateId) << ",\n";
    output << "  \"selectedIncomingTrackId\": "
           << jsonString(result.selectedIncomingTrackId.has_value() ? result.selectedIncomingTrackId->value : "")
           << ",\n";
    output << "  \"nextOutgoingTrackId\": "
           << jsonString(result.nextOutgoingTrackId.has_value() ? result.nextOutgoingTrackId->value : "") << ",\n";
    output << "  \"nextOutgoingDeck\": " << result.nextOutgoingDeck << ",\n";
    output << "  \"candidateRejections\": [\n";
    for (std::size_t index = 0; index < result.candidateRejections.size(); ++index) {
        const auto& rejection = result.candidateRejections[index];
        output << "    {\"code\": " << jsonString(rejection.code) << ", \"message\": "
               << jsonString(rejection.message) << ", \"trackId\": " << jsonString(rejection.trackId.value) << "}";
        if (index + 1 < result.candidateRejections.size()) {
            output << ",";
        }
        output << "\n";
    }
    output << "  ],\n";
    output << "  \"errors\": [\n";
    for (std::size_t index = 0; index < result.errors.size(); ++index) {
        const auto& error = result.errors[index];
        output << "    {\"code\": " << jsonString(error.code) << ", \"message\": " << jsonString(error.message)
               << ", \"trackId\": " << jsonString(error.trackId.value) << "}";
        if (index + 1 < result.errors.size()) {
            output << ",";
        }
        output << "\n";
    }
    output << "  ]\n";
    output << "}\n";
    return output.str();
}

[[nodiscard]] std::string summaryMarkdown(const autodj::dj::DubstepPocPlanResult& result,
                                          const std::filesystem::path& outDir,
                                          const autodj::dj::TrackAnalysisSummary& outgoing) {
    std::ostringstream output;
    output << "# MixPlan POC Transition Summary\n\n";
    output << "- OK: " << (result.ok() ? "true" : "false") << "\n";
    output << "- Output directory: `" << outDir.generic_string() << "`\n";
    output << "- MixPlan: `" << (outDir / "mix-plan.json").generic_string() << "`\n";
    output << "- Outgoing track: `" << outgoing.trackId.value << "`\n";
    output << "- Selected incoming track: `"
           << (result.selectedIncomingTrackId.has_value() ? result.selectedIncomingTrackId->value : "") << "`\n";
    output << "- Selected template: `" << result.selectedTemplateId << "`\n";
    output << "- Next outgoing track: `"
           << (result.nextOutgoingTrackId.has_value() ? result.nextOutgoingTrackId->value : "") << "`\n";
    output << "- Next outgoing deck: `" << result.nextOutgoingDeck << "`\n\n";

    if (!result.debugNotes.empty()) {
        output << "## Debug Notes\n\n";
        for (const auto& note : result.debugNotes) {
            output << "- " << note << "\n";
        }
        output << "\n";
    }
    if (!result.candidateRejections.empty()) {
        output << "## Candidate Rejections\n\n";
        for (const auto& rejection : result.candidateRejections) {
            output << "- `" << rejection.trackId.value << "`: `" << rejection.code << "` - " << rejection.message
                   << "\n";
        }
        output << "\n";
    }
    if (!result.errors.empty()) {
        output << "## Errors\n\n";
        for (const auto& error : result.errors) {
            output << "- `" << error.code << "` - " << error.message << "\n";
        }
    }
    return output.str();
}

}  // namespace

int main(const int argc, char* argv[]) {
    try {
        const auto options = parseArgs(argc, argv);
        auto outgoing = readArtifactOrThrow(options.outgoingArtifact);
        std::vector<autodj::dj::TrackAnalysisSummary> incomingCandidates;
        incomingCandidates.reserve(options.incomingArtifacts.size());
        for (const auto& artifact : options.incomingArtifacts) {
            incomingCandidates.push_back(readArtifactOrThrow(artifact));
        }

        const autodj::dj::DubstepDJStrategy strategy;
        const auto result = strategy.generatePocPlan(outgoing, incomingCandidates, options.planOptions);

        std::filesystem::create_directories(options.outDir);
        if (result.plan.has_value()) {
            writeTextFile(options.outDir / "mix-plan.json", autodj::dj::serializeMixPlanJson(result.plan.value()));
        }
        writeTextFile(options.outDir / "planner-summary.json", summaryJson(result, options.outDir));
        writeTextFile(options.outDir / "transition-debug-summary.md", summaryMarkdown(result, options.outDir, outgoing));

        const auto json = summaryJson(result, options.outDir);
        if (options.json) {
            std::cout << json;
        } else {
            std::cout << "MixPlan POC summary written: " << (options.outDir / "planner-summary.json") << "\n";
            if (result.plan.has_value()) {
                std::cout << "MixPlan written: " << (options.outDir / "mix-plan.json") << "\n";
            }
        }
        return result.ok() ? 0 : 1;
    } catch (const std::exception& exc) {
        std::cerr << "autodj_mixplan_poc: " << exc.what() << "\n";
        printUsage(std::cerr);
        return 2;
    }
}
