#pragma once

#include "autodj/domain/types.hpp"

#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace autodj::dj {

struct AnalysisArtifactIssue final {
    std::string code;
    std::string message;
};

struct AnalyzedBeat final {
    int index{0};
    double timeSeconds{0.0};
    std::optional<int> beatInBar;
    std::optional<double> confidence;
};

struct AnalyzedSection final {
    std::string id;
    std::string type;
    double startSeconds{0.0};
    double endSeconds{0.0};
    std::optional<int> startBeatIndex;
    std::optional<int> endBeatIndex;
    std::optional<double> confidence;
};

struct AnalyzedCuePoint final {
    std::string id;
    std::string type;
    double timeSeconds{0.0};
    std::optional<int> beatIndex;
    std::string sectionId;
    std::optional<double> confidence;
    std::vector<std::string> tags;
};

struct TrackAnalysisSummary final {
    static constexpr int beatsPerMeasure = 4;

    domain::TrackId trackId;
    std::string sourceUri;
    std::optional<double> durationSeconds;
    std::optional<double> rawBpm;
    double normalizedBpm{0.0};
    double tempoConfidence{0.0};
    double beatGridConfidence{0.0};
    double overallConfidence{0.0};
    std::vector<AnalyzedBeat> beats;
    std::vector<AnalyzedSection> builds;
    std::vector<AnalyzedSection> drops;
    std::vector<AnalyzedCuePoint> cuePoints;
    std::vector<std::string> qualityWarnings;
    std::vector<std::string> riskFlags;
};

struct TrackAnalysisSummaryReadResult final {
    std::optional<TrackAnalysisSummary> summary;
    std::vector<AnalysisArtifactIssue> errors;
    std::vector<AnalysisArtifactIssue> warnings;

    [[nodiscard]] bool ok() const noexcept { return summary.has_value() && errors.empty(); }
};

[[nodiscard]] TrackAnalysisSummaryReadResult parseTrackAnalysisSummary(std::string_view json,
                                                                       std::string sourceUri = {});

[[nodiscard]] TrackAnalysisSummaryReadResult readTrackAnalysisSummary(const std::filesystem::path& artifactPath);

}  // namespace autodj::dj
