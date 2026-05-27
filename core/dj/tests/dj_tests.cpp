#include "autodj/dj/dj.hpp"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <filesystem>
#include <optional>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

namespace {

[[nodiscard]] std::filesystem::path contracts_dir() {
    return std::filesystem::path{AUTODJ_CONTRACTS_DIR};
}

[[nodiscard]] bool nearly_equal(const double lhs, const double rhs) {
    return std::fabs(lhs - rhs) < 0.000001;
}

[[nodiscard]] bool contains(const std::vector<std::string>& values, const std::string& expected) {
    return std::find(values.begin(), values.end(), expected) != values.end();
}

[[nodiscard]] bool contains_issue(const std::vector<autodj::dj::DropSwitchTemplateIssue>& issues,
                                  const std::string& expected) {
    return std::find_if(issues.begin(), issues.end(), [&](const auto& issue) {
               return issue.code == expected;
           }) != issues.end();
}

[[nodiscard]] bool contains_issue(const std::vector<autodj::dj::DropEndReverbExitIssue>& issues,
                                  const std::string& expected) {
    return std::find_if(issues.begin(), issues.end(), [&](const auto& issue) {
               return issue.code == expected;
           }) != issues.end();
}

[[nodiscard]] bool contains_issue(const std::vector<autodj::dj::DubstepPocPlanIssue>& issues,
                                  const std::string& expected) {
    return std::find_if(issues.begin(), issues.end(), [&](const auto& issue) {
               return issue.code == expected;
           }) != issues.end();
}

[[nodiscard]] autodj::dj::AnalyzedSection make_section(std::string id,
                                                       std::string type,
                                                       const double startSeconds,
                                                       const double endSeconds,
                                                       const int startBeatIndex,
                                                       const std::optional<double> confidence = 0.9) {
    return autodj::dj::AnalyzedSection{
        .id = std::move(id),
        .type = std::move(type),
        .startSeconds = startSeconds,
        .endSeconds = endSeconds,
        .startBeatIndex = startBeatIndex,
        .endBeatIndex = startBeatIndex + 16,
        .confidence = confidence,
    };
}

[[nodiscard]] std::vector<autodj::dj::AnalyzedBeat> make_beats(const double bpm, const int count) {
    std::vector<autodj::dj::AnalyzedBeat> beats;
    beats.reserve(static_cast<std::size_t>(count));
    const double beatSeconds = 60.0 / bpm;
    for (int index = 0; index < count; ++index) {
        beats.push_back(autodj::dj::AnalyzedBeat{
            .index = index,
            .timeSeconds = static_cast<double>(index) * beatSeconds,
            .beatInBar = index % autodj::dj::TrackAnalysisSummary::beatsPerMeasure + 1,
            .confidence = 1.0,
        });
    }
    return beats;
}

void set_key(autodj::dj::TrackAnalysisSummary& summary,
             std::string camelot,
             const double confidence = 0.9,
             std::string backendName = "selected-madmom-keyfinder") {
    summary.key = autodj::dj::AnalyzedKey{
        .tonic = "E",
        .mode = "minor",
        .camelot = std::move(camelot),
        .confidence = confidence,
        .backendName = std::move(backendName),
        .modelName = "Selected Madmom/KeyFinder Ensemble",
    };
}

[[nodiscard]] autodj::dj::TrackAnalysisSummary make_outgoing_drop_switch_track(const double bpm = 150.0) {
    autodj::dj::TrackAnalysisSummary summary;
    summary.trackId = autodj::domain::TrackId{"track-a"};
    summary.sourceUri = "fixture://track-a";
    summary.durationSeconds = 160.0;
    summary.rawBpm = bpm;
    summary.normalizedBpm = bpm;
    summary.tempoConfidence = 0.95;
    summary.beatGridConfidence = 0.96;
    summary.overallConfidence = 0.9;
    set_key(summary, "9A");
    summary.beats = make_beats(bpm, 401);
    summary.builds = {
        make_section("a-build-1", "build", 0.0, 32.0, 0),
        make_section("a-build-2", "build", 64.0, 96.0, 160),
    };
    summary.drops = {
        make_section("a-drop-1", "drop", 32.0, 64.0, 80),
        make_section("a-drop-2", "drop", 96.0, 128.0, 240),
    };
    return summary;
}

[[nodiscard]] autodj::dj::TrackAnalysisSummary make_incoming_drop_switch_track(const double bpm = 150.0) {
    autodj::dj::TrackAnalysisSummary summary;
    summary.trackId = autodj::domain::TrackId{"track-b"};
    summary.sourceUri = "fixture://track-b";
    summary.durationSeconds = 180.0;
    summary.rawBpm = bpm;
    summary.normalizedBpm = bpm;
    summary.tempoConfidence = 0.94;
    summary.beatGridConfidence = 0.95;
    summary.overallConfidence = 0.89;
    set_key(summary, "9A");
    summary.beats = make_beats(bpm, 451);
    summary.builds = {
        make_section("b-build-1", "build", 48.0, 80.0, 120),
    };
    summary.drops = {
        make_section("b-drop-1", "drop", 80.0, 112.0, 200),
    };
    return summary;
}

[[nodiscard]] autodj::dj::TrackAnalysisSummary make_outgoing_reverb_exit_track(const double bpm = 150.0) {
    autodj::dj::TrackAnalysisSummary summary;
    summary.trackId = autodj::domain::TrackId{"track-reverb-a"};
    summary.sourceUri = "fixture://track-reverb-a";
    summary.durationSeconds = 120.0;
    summary.rawBpm = bpm;
    summary.normalizedBpm = bpm;
    summary.tempoConfidence = 0.95;
    summary.beatGridConfidence = 0.96;
    summary.overallConfidence = 0.9;
    set_key(summary, "9A");
    summary.beats = {
        {.index = 0, .timeSeconds = 0.0, .beatInBar = 1, .confidence = 1.0},
        {.index = 80, .timeSeconds = 32.0, .beatInBar = 1, .confidence = 1.0},
        {.index = 160, .timeSeconds = 64.0, .beatInBar = 1, .confidence = 1.0},
    };
    summary.builds = {
        make_section("reverb-a-build-1", "build", 0.0, 32.0, 0),
    };
    summary.drops = {
        make_section("reverb-a-drop-1", "drop", 32.0, 64.0, 80),
    };
    summary.drops[0].endBeatIndex = 160;
    return summary;
}

[[nodiscard]] autodj::dj::TrackAnalysisSummary make_incoming_reverb_exit_track(const double bpm = 150.0) {
    autodj::dj::TrackAnalysisSummary summary;
    summary.trackId = autodj::domain::TrackId{"track-reverb-b"};
    summary.sourceUri = "fixture://track-reverb-b";
    summary.durationSeconds = 180.0;
    summary.rawBpm = bpm;
    summary.normalizedBpm = bpm;
    summary.tempoConfidence = 0.94;
    summary.beatGridConfidence = 0.95;
    summary.overallConfidence = 0.89;
    set_key(summary, "9A");
    summary.beats = {
        {.index = 0, .timeSeconds = 0.4, .beatInBar = 1, .confidence = 1.0},
        {.index = 4, .timeSeconds = 2.0, .beatInBar = 1, .confidence = 1.0},
    };
    summary.builds = {
        make_section("reverb-b-build-1", "build", 16.4, 48.4, 40),
    };
    summary.drops = {
        make_section("reverb-b-drop-1", "drop", 48.4, 80.4, 120),
    };
    return summary;
}

[[nodiscard]] const autodj::playback::DeckCommand* find_command(
    const std::vector<autodj::playback::DeckCommand>& commands,
    const autodj::playback::DeckCommandType type,
    const std::optional<int> deck = std::nullopt,
    const std::optional<autodj::playback::AutomationControl> control = std::nullopt) {
    for (const auto& command : commands) {
        if (command.type != type) {
            continue;
        }
        if (deck.has_value() && (!command.deck.has_value() || command.deck.value() != deck.value())) {
            continue;
        }
        if (control.has_value() && (!command.control.has_value() || command.control.value() != control.value())) {
            continue;
        }
        return &command;
    }
    return nullptr;
}

void dubstep_strategy_implements_strategy_contract() {
    static_assert(std::is_base_of_v<autodj::dj::IDJStrategy, autodj::dj::DubstepDJStrategy>);

    const autodj::dj::DubstepDJStrategy concrete;
    const autodj::dj::IDJStrategy& strategy = concrete;

    assert(strategy.strategyId() == "dubstep-dj");
}

void dubstep_strategy_reports_dubstep_support() {
    const autodj::dj::DubstepDJStrategy strategy;

    const auto genres = strategy.supportedGenres();
    const auto found = std::find(genres.begin(), genres.end(), "dubstep");

    assert(found != genres.end());
    assert(genres.size() == 1);
}

void placeholder_plan_is_mix_plan_shaped() {
    const autodj::dj::DubstepDJStrategy strategy;

    const std::string plan = strategy.generatePlanPlaceholder();

    assert(plan.find("\"schemaVersion\": \"autodj.mix-plan.v1\"") != std::string::npos);
    assert(plan.find("\"planId\": \"plan-placeholder-dubstep\"") != std::string::npos);
    assert(plan.find("\"strategyId\": \"dubstep-dj\"") != std::string::npos);
    assert(plan.find("\"tracks\": []") != std::string::npos);
    assert(plan.find("\"transitions\": []") != std::string::npos);
    assert(plan.find("\"commands\": []") != std::string::npos);
}

void placeholder_plan_does_not_reference_audio_files() {
    const autodj::dj::DubstepDJStrategy strategy;

    const std::string plan = strategy.generatePlanPlaceholder();

    assert(plan.find("file://") == std::string::npos);
    assert(plan.find(".wav") == std::string::npos);
    assert(plan.find(".mp3") == std::string::npos);
}

void analysis_summary_reads_contract_fixture() {
    const auto artifactPath = contracts_dir() / "examples" / "analyzed-track.stub.json";

    const auto result = autodj::dj::readTrackAnalysisSummary(artifactPath);

    assert(result.ok());
    const auto& summary = result.summary.value();
    assert(summary.trackId.value == "track-stub-a");
    assert(summary.sourceUri == "fixture://autodj/local-dubstep-stubs/track-stub-a");
    assert(nearly_equal(summary.normalizedBpm, 140.0));
    assert(summary.rawBpm.has_value());
    assert(nearly_equal(summary.rawBpm.value(), 140.0));
    assert(nearly_equal(summary.tempoConfidence, 1.0));
    assert(summary.key.camelot == "4A");
    assert(summary.key.tonic == "F");
    assert(summary.key.mode == "minor");
    assert(nearly_equal(summary.key.confidence, 0.8));
    assert(nearly_equal(summary.beatGridConfidence, 1.0));
    assert(nearly_equal(summary.overallConfidence, 0.86));
    assert(autodj::dj::TrackAnalysisSummary::beatsPerMeasure == 4);
    assert(summary.beats.size() == 4);
    assert(summary.builds.size() == 1);
    assert(summary.drops.size() == 1);
    assert(summary.cuePoints.size() == 3);
    assert(summary.qualityWarnings.size() == 1);
    assert(summary.riskFlags.empty());
}

void analysis_summary_reads_key_metadata_and_risk_flags() {
    const std::string knownKeyJson = R"json({
      "schemaVersion": "1.0.0",
      "trackId": "key-fixture",
      "source": { "sourceUri": "fixture://key-fixture" },
      "tempo": { "bpm": 150.0, "normalizedBpm": 150.0, "confidence": 0.92 },
      "key": {
        "tonic": "E",
        "mode": "minor",
        "camelot": "9A",
        "confidence": 0.91,
        "provenance": {
          "backendName": "selected-madmom-keyfinder",
          "modelName": "Selected Madmom/KeyFinder Ensemble"
        },
        "candidates": []
      },
      "beatGrid": {
        "confidence": 0.91,
        "beats": [{ "index": 0, "timeSeconds": 0.0, "beatInBar": 1 }]
      },
      "sections": [],
      "cuePoints": [],
      "quality": { "overallConfidence": 0.89, "warnings": [] }
    })json";

    const auto known = autodj::dj::parseTrackAnalysisSummary(knownKeyJson);

    assert(known.ok());
    assert(known.summary->key.camelot == "9A");
    assert(known.summary->key.backendName == "selected-madmom-keyfinder");
    assert(!contains(known.summary->riskFlags, "missing_key"));
    assert(!contains(known.summary->riskFlags, "low_key_confidence"));

    const std::string lowConfidenceJson = R"json({
      "schemaVersion": "1.0.0",
      "trackId": "low-key-fixture",
      "source": { "sourceUri": "fixture://low-key-fixture" },
      "tempo": { "bpm": 150.0, "normalizedBpm": 150.0, "confidence": 0.92 },
      "key": { "tonic": "E", "mode": "minor", "camelot": "9A", "confidence": 0.4, "candidates": [] },
      "beatGrid": {
        "confidence": 0.91,
        "beats": [{ "index": 0, "timeSeconds": 0.0, "beatInBar": 1 }]
      },
      "sections": [],
      "cuePoints": [],
      "quality": { "overallConfidence": 0.89, "warnings": [] }
    })json";

    const auto lowConfidence = autodj::dj::parseTrackAnalysisSummary(lowConfidenceJson);

    assert(lowConfidence.ok());
    assert(contains(lowConfidence.summary->riskFlags, "low_key_confidence"));

    const std::string missingKeyJson = R"json({
      "schemaVersion": "1.0.0",
      "trackId": "missing-key-fixture",
      "source": { "sourceUri": "fixture://missing-key-fixture" },
      "tempo": { "bpm": 150.0, "normalizedBpm": 150.0, "confidence": 0.92 },
      "beatGrid": {
        "confidence": 0.91,
        "beats": [{ "index": 0, "timeSeconds": 0.0, "beatInBar": 1 }]
      },
      "sections": [],
      "cuePoints": [],
      "quality": { "overallConfidence": 0.89, "warnings": [] }
    })json";

    const auto missing = autodj::dj::parseTrackAnalysisSummary(missingKeyJson);

    assert(missing.ok());
    assert(contains(missing.summary->riskFlags, "missing_key"));
    assert(!missing.warnings.empty());
    assert(missing.warnings.front().code == "missing_key_analysis");
}

void analysis_summary_orders_sections_and_cues() {
    const std::string json = R"json({
      "schemaVersion": "1.0.0",
      "trackId": "ordering-fixture",
      "source": { "sourceUri": "fixture://ordering" },
      "tempo": { "bpm": 150.0, "normalizedBpm": 150.0, "confidence": 0.92 },
      "beatGrid": {
        "confidence": 0.91,
        "beats": [
          { "index": 4, "timeSeconds": 1.6 },
          { "index": 0, "timeSeconds": 0.0, "beatInBar": 1 }
        ]
      },
      "sections": [
        { "id": "drop-2", "type": "drop", "startSeconds": 96.0, "endSeconds": 128.0, "confidence": 0.8 },
        { "id": "build-2", "type": "build", "startSeconds": 64.0, "endSeconds": 96.0, "confidence": 0.8 },
        { "id": "drop-1", "type": "drop", "startSeconds": 32.0, "endSeconds": 64.0, "confidence": 0.88 },
        { "id": "build-1", "type": "build", "startSeconds": 0.0, "endSeconds": 32.0, "confidence": 0.9 },
        { "id": "verse-1", "type": "verse", "startSeconds": 128.0, "endSeconds": 160.0, "confidence": 0.7 }
      ],
      "cuePoints": [
        { "id": "drop-cue", "type": "drop", "timeSeconds": 32.0, "confidence": 0.88 },
        { "id": "mix-in", "type": "mix_in", "timeSeconds": 0.0, "beatIndex": 0, "confidence": 0.9, "tags": ["phrase_start"] }
      ],
      "quality": { "overallConfidence": 0.89, "warnings": [] }
    })json";

    const auto result = autodj::dj::parseTrackAnalysisSummary(json);

    assert(result.ok());
    const auto& summary = result.summary.value();
    assert(summary.builds.size() == 2);
    assert(summary.builds[0].id == "build-1");
    assert(summary.builds[1].id == "build-2");
    assert(summary.drops.size() == 2);
    assert(summary.drops[0].id == "drop-1");
    assert(summary.drops[1].id == "drop-2");
    assert(summary.cuePoints.size() == 2);
    assert(summary.cuePoints[0].id == "mix-in");
    assert(summary.cuePoints[0].tags.size() == 1);
    assert(summary.beats.size() == 2);
    assert(summary.beats[0].index == 0);
    assert(summary.beats[1].index == 4);
}

void analysis_summary_rejects_invalid_artifacts() {
    const auto invalidJson = autodj::dj::parseTrackAnalysisSummary("{not-json");
    assert(!invalidJson.ok());
    assert(!invalidJson.errors.empty());
    assert(invalidJson.errors.front().code == "invalid_json");

    const std::string missingBeatGrid = R"json({
      "schemaVersion": "1.0.0",
      "trackId": "missing-beats",
      "source": { "sourceUri": "fixture://missing-beats" },
      "tempo": { "normalizedBpm": 140.0, "confidence": 1.0 },
      "beatGrid": { "confidence": 1.0, "beats": [] },
      "sections": [],
      "cuePoints": [],
      "quality": { "overallConfidence": 1.0, "warnings": [] }
    })json";

    const auto missingBeats = autodj::dj::parseTrackAnalysisSummary(missingBeatGrid);
    assert(!missingBeats.ok());
    assert(!missingBeats.errors.empty());
    assert(missingBeats.errors.front().code == "invalid_artifact");
}

void drop_switch_template_generates_aligned_plan_fragment() {
    const auto result = autodj::dj::buildSecondBuildDropSwitchTemplate(make_outgoing_drop_switch_track(),
                                                                       make_incoming_drop_switch_track());

    assert(result.ok());
    assert(result.fragment.has_value());
    const auto& fragment = result.fragment.value();

    assert(fragment.placements.size() == 2);
    assert(fragment.placements[0].trackId.value == "track-a");
    assert(fragment.placements[0].deck == 1);
    assert(fragment.placements[0].role == "primary");
    assert(nearly_equal(fragment.placements[0].timelineStartSeconds, 0.0));
    assert(nearly_equal(fragment.placements[0].sourceEndSeconds.value(), 94.4));
    assert(nearly_equal(fragment.placements[0].timelineEndSeconds.value(), 94.4));
    assert(fragment.placements[1].trackId.value == "track-b");
    assert(fragment.placements[1].deck == 2);
    assert(fragment.placements[1].role == "incoming");
    assert(nearly_equal(fragment.placements[1].sourceStartSeconds, 48.0));
    assert(nearly_equal(fragment.placements[1].timelineStartSeconds, 64.0));

    assert(fragment.transition.technique == autodj::playback::TransitionTechnique::BuildToDropSwap);
    assert(fragment.transition.templateId == "second_build_drop_switch_v1");
    assert(nearly_equal(fragment.transition.timelineStartSeconds, 64.0));
    assert(nearly_equal(fragment.transition.timelineEndSeconds, 96.0));
    assert(nearly_equal(fragment.transition.measureCountToTarget.value(), 20.0));
    assert(nearly_equal(fragment.transition.alignedDropTimelineSeconds.value(), 96.0));
    assert(nearly_equal(fragment.transition.handoffTimelineSeconds.value(), 94.4));
    assert(fragment.transition.sourceAnchors.contains("fromBuildStart"));
    assert(fragment.transition.sourceAnchors.contains("fromDropStart"));
    assert(fragment.transition.sourceAnchors.contains("toDropStart"));
    assert(fragment.transition.sourceAnchors.at("fromDropStart").beatIndex.value() == 240);
    assert(fragment.transition.sourceAnchors.at("toDropStart").measureIndex.value() == 50);
    assert(fragment.transition.riskFlags.empty());

    const auto* incomingLoad = find_command(fragment.commands, autodj::playback::DeckCommandType::Load, 2);
    assert(incomingLoad != nullptr);
    assert(nearly_equal(incomingLoad->at, 60.0));
    assert(nearly_equal(incomingLoad->cueSeconds.value(), 48.0));

    const auto* incomingPlay = find_command(fragment.commands, autodj::playback::DeckCommandType::Play, 2);
    assert(incomingPlay != nullptr);
    assert(nearly_equal(incomingPlay->at, 64.0));

    const auto* outgoingVolume = find_command(fragment.commands,
                                              autodj::playback::DeckCommandType::Automate,
                                              1,
                                              autodj::playback::AutomationControl::Volume);
    assert(outgoingVolume != nullptr);
    assert(outgoingVolume->keyframes.size() == 2);
    assert(nearly_equal(outgoingVolume->keyframes[0].at, 64.0));
    assert(nearly_equal(outgoingVolume->keyframes[0].value, 1.0));
    assert(nearly_equal(outgoingVolume->keyframes[1].at, 94.4));
    assert(nearly_equal(outgoingVolume->keyframes[1].value, 0.0));

    const auto* incomingVolume = find_command(fragment.commands,
                                              autodj::playback::DeckCommandType::Automate,
                                              2,
                                              autodj::playback::AutomationControl::Volume);
    assert(incomingVolume != nullptr);
    assert(nearly_equal(incomingVolume->keyframes[0].at, 64.0));
    assert(nearly_equal(incomingVolume->keyframes[1].at, 80.0));

    const auto* outgoingLow = find_command(fragment.commands,
                                           autodj::playback::DeckCommandType::Automate,
                                           1,
                                           autodj::playback::AutomationControl::EqLow);
    assert(outgoingLow != nullptr);
    assert(outgoingLow->keyframes.size() == 1);
    assert(nearly_equal(outgoingLow->keyframes[0].at, 80.0));
    assert(nearly_equal(outgoingLow->keyframes[0].value, 0.0));

    const auto* incomingLow = find_command(fragment.commands,
                                           autodj::playback::DeckCommandType::Automate,
                                           2,
                                           autodj::playback::AutomationControl::EqLow);
    assert(incomingLow != nullptr);
    assert(incomingLow->keyframes.size() == 2);
    assert(nearly_equal(incomingLow->keyframes[0].at, 64.0));
    assert(nearly_equal(incomingLow->keyframes[0].value, 0.0));
    assert(nearly_equal(incomingLow->keyframes[1].at, 80.0));
    assert(nearly_equal(incomingLow->keyframes[1].value, 1.0));

    const auto* crossfader = find_command(fragment.commands,
                                          autodj::playback::DeckCommandType::Automate,
                                          std::nullopt,
                                          autodj::playback::AutomationControl::Crossfader);
    assert(crossfader == nullptr);

    const auto* outgoingStop = find_command(fragment.commands, autodj::playback::DeckCommandType::Stop, 1);
    assert(outgoingStop != nullptr);
    assert(nearly_equal(outgoingStop->at, 94.4));
    assert(fragment.annotations.size() == 4);
}

void drop_switch_template_rejects_when_incoming_lacks_enough_predrop_beats() {
    auto outgoing = make_outgoing_drop_switch_track();
    outgoing.builds[1] = make_section("a-build-2", "build", 64.0, 128.0, 160);
    outgoing.drops[1] = make_section("a-drop-2", "drop", 128.0, 160.0, 320);

    auto incoming = make_incoming_drop_switch_track();
    incoming.builds[0] = make_section("b-build-1", "build", 0.0, 32.0, 0);
    incoming.drops[0] = make_section("b-drop-1", "drop", 32.0, 64.0, 80);

    const auto result = autodj::dj::buildSecondBuildDropSwitchTemplate(outgoing, incoming);

    assert(!result.ok());
    assert(contains_issue(result.rejectionReasons, "missing_incoming_predrop_beat"));
}

void drop_switch_template_rejects_missing_sections() {
    auto outgoing = make_outgoing_drop_switch_track();
    outgoing.builds.pop_back();

    const auto outgoingResult =
        autodj::dj::buildSecondBuildDropSwitchTemplate(outgoing, make_incoming_drop_switch_track());
    assert(!outgoingResult.ok());
    assert(contains_issue(outgoingResult.rejectionReasons, "missing_outgoing_second_build_drop"));

    auto incoming = make_incoming_drop_switch_track();
    incoming.drops.clear();
    const auto incomingResult =
        autodj::dj::buildSecondBuildDropSwitchTemplate(make_outgoing_drop_switch_track(), incoming);
    assert(!incomingResult.ok());
    assert(contains_issue(incomingResult.rejectionReasons, "missing_incoming_first_drop"));
}

void drop_switch_template_rejects_low_confidence_sections() {
    auto outgoing = make_outgoing_drop_switch_track();
    outgoing.builds[1].confidence = 0.4;

    const auto result =
        autodj::dj::buildSecondBuildDropSwitchTemplate(outgoing, make_incoming_drop_switch_track());

    assert(!result.ok());
    assert(contains_issue(result.rejectionReasons, "low_section_confidence"));
}

void drop_switch_template_rejects_exact_bpm_mismatch() {
    const auto result = autodj::dj::buildSecondBuildDropSwitchTemplate(make_outgoing_drop_switch_track(),
                                                                       make_incoming_drop_switch_track(150.5));

    assert(!result.ok());
    assert(contains_issue(result.rejectionReasons, "bpm_mismatch_for_drop_switch"));
}

void drop_switch_template_rejects_too_short_handoff() {
    auto outgoing = make_outgoing_drop_switch_track();
    outgoing.builds[1] = make_section("a-build-2", "build", 94.4, 96.0, 236);

    const auto result =
        autodj::dj::buildSecondBuildDropSwitchTemplate(outgoing, make_incoming_drop_switch_track());

    assert(!result.ok());
    assert(contains_issue(result.rejectionReasons, "build_too_short_for_handoff"));
}

void drop_end_reverb_exit_generates_full_ramp_fragment() {
    const auto result = autodj::dj::buildDropEndReverbExitTemplate(make_outgoing_reverb_exit_track(),
                                                                   make_incoming_reverb_exit_track());

    assert(result.ok());
    assert(result.fragment.has_value());
    const auto& fragment = result.fragment.value();

    constexpr double sweepDurationSeconds = 7.68;
    constexpr double sweepPeakOffsetSeconds = 3.8400907029478457;
    constexpr double sweepTimelineStartSeconds = 64.0 - sweepPeakOffsetSeconds;
    constexpr double sweepTimelineEndSeconds = sweepTimelineStartSeconds + sweepDurationSeconds;

    assert(fragment.assets.size() == 1);
    assert(fragment.assets[0].trackId.value == "washout-sweep-fx");
    assert(fragment.assets[0].sourceUri == "generated://autodj/fx/washout-sweep-v1.wav");
    assert(nearly_equal(fragment.assets[0].durationSeconds.value(), sweepDurationSeconds));

    assert(fragment.placements.size() == 3);
    assert(fragment.placements[0].trackId.value == "track-reverb-a");
    assert(fragment.placements[0].deck == 1);
    assert(nearly_equal(fragment.placements[0].sourceEndSeconds.value(), 64.0));
    assert(nearly_equal(fragment.placements[0].timelineEndSeconds.value(), 88.0));
    assert(fragment.placements[1].trackId.value == "track-reverb-b");
    assert(fragment.placements[1].deck == 2);
    assert(nearly_equal(fragment.placements[1].sourceStartSeconds, 0.4));
    assert(nearly_equal(fragment.placements[1].timelineStartSeconds, 64.0));
    assert(fragment.placements[2].trackId.value == "washout-sweep-fx");
    assert(fragment.placements[2].deck == 3);
    assert(nearly_equal(fragment.placements[2].sourceStartSeconds, 0.0));
    assert(nearly_equal(fragment.placements[2].sourceEndSeconds.value(), sweepDurationSeconds));
    assert(nearly_equal(fragment.placements[2].timelineStartSeconds, sweepTimelineStartSeconds));
    assert(nearly_equal(fragment.placements[2].timelineEndSeconds.value(), sweepTimelineEndSeconds));
    assert(fragment.placements[2].role == "fx");

    assert(fragment.transition.technique == autodj::playback::TransitionTechnique::WashOut);
    assert(fragment.transition.templateId == "drop_end_wash_out_v1");
    assert(nearly_equal(fragment.transition.timelineStartSeconds, 62.4));
    assert(nearly_equal(fragment.transition.timelineEndSeconds, 88.0));
    assert(nearly_equal(fragment.transition.measureCountToTarget.value(), 1.0));
    assert(nearly_equal(fragment.transition.handoffTimelineSeconds.value(), 64.0));
    assert(fragment.transition.sourceAnchors.contains("fromDropEnd"));
    assert(fragment.transition.sourceAnchors.contains("toFirstBeat"));
    assert(nearly_equal(fragment.transition.sourceAnchors.at("fromDropEnd").sourceSeconds.value(), 64.0));
    assert(nearly_equal(fragment.transition.sourceAnchors.at("toFirstBeat").sourceSeconds.value(), 0.4));
    assert(fragment.transition.riskFlags.empty());

    const auto* incomingLoad = find_command(fragment.commands, autodj::playback::DeckCommandType::Load, 2);
    assert(incomingLoad != nullptr);
    assert(nearly_equal(incomingLoad->at, 60.0));
    assert(nearly_equal(incomingLoad->cueSeconds.value(), 0.4));

    const auto* incomingPlay = find_command(fragment.commands, autodj::playback::DeckCommandType::Play, 2);
    assert(incomingPlay != nullptr);
    assert(nearly_equal(incomingPlay->at, 64.0));

    const auto* sweepLoad = find_command(fragment.commands, autodj::playback::DeckCommandType::Load, 3);
    assert(sweepLoad != nullptr);
    assert(nearly_equal(sweepLoad->at, sweepTimelineStartSeconds));
    assert(sweepLoad->trackId.value == "washout-sweep-fx");
    assert(nearly_equal(sweepLoad->cueSeconds.value(), 0.0));

    const auto* sweepPlay = find_command(fragment.commands, autodj::playback::DeckCommandType::Play, 3);
    assert(sweepPlay != nullptr);
    assert(nearly_equal(sweepPlay->at, sweepTimelineStartSeconds));

    const auto* sweepVolume = find_command(fragment.commands,
                                           autodj::playback::DeckCommandType::Automate,
                                           3,
                                           autodj::playback::AutomationControl::Volume);
    assert(sweepVolume != nullptr);
    assert(sweepVolume->keyframes.size() == 1);
    assert(nearly_equal(sweepVolume->keyframes[0].at, sweepTimelineStartSeconds));
    assert(nearly_equal(sweepVolume->keyframes[0].value, 2.50));

    const auto* outgoingLow = find_command(fragment.commands,
                                           autodj::playback::DeckCommandType::Automate,
                                           1,
                                           autodj::playback::AutomationControl::EqLow);
    assert(outgoingLow != nullptr);
    assert(outgoingLow->keyframes.size() == 2);
    assert(nearly_equal(outgoingLow->keyframes[0].at, 62.4));
    assert(nearly_equal(outgoingLow->keyframes[0].value, 1.0));
    assert(nearly_equal(outgoingLow->keyframes[1].at, 64.0));
    assert(nearly_equal(outgoingLow->keyframes[1].value, 0.0));

    const auto* outgoingHigh = find_command(fragment.commands,
                                            autodj::playback::DeckCommandType::Automate,
                                            1,
                                            autodj::playback::AutomationControl::EqHigh);
    assert(outgoingHigh != nullptr);
    assert(outgoingHigh->keyframes.size() == 2);
    assert(nearly_equal(outgoingHigh->keyframes[0].at, 62.4));
    assert(nearly_equal(outgoingHigh->keyframes[0].value, 1.0));
    assert(nearly_equal(outgoingHigh->keyframes[1].at, 64.0));
    assert(nearly_equal(outgoingHigh->keyframes[1].value, 0.62));

    const auto* outgoingReverb = find_command(fragment.commands,
                                              autodj::playback::DeckCommandType::Automate,
                                              1,
                                              autodj::playback::AutomationControl::ReverbWet);
    assert(outgoingReverb != nullptr);
    assert(outgoingReverb->postFader);
    assert(outgoingReverb->keyframes.size() == 3);
    assert(nearly_equal(outgoingReverb->keyframes[0].at, 62.4));
    assert(nearly_equal(outgoingReverb->keyframes[0].value, 0.0));
    assert(nearly_equal(outgoingReverb->keyframes[1].at, 64.0));
    assert(nearly_equal(outgoingReverb->keyframes[1].value, 1.0));
    assert(nearly_equal(outgoingReverb->keyframes[2].at, 64.0));
    assert(nearly_equal(outgoingReverb->keyframes[2].value, 0.0));

    const auto* outgoingVolume = find_command(fragment.commands,
                                              autodj::playback::DeckCommandType::Automate,
                                              1,
                                              autodj::playback::AutomationControl::Volume);
    assert(outgoingVolume != nullptr);
    assert(outgoingVolume->keyframes.size() == 1);
    assert(nearly_equal(outgoingVolume->keyframes[0].at, 64.0));
    assert(nearly_equal(outgoingVolume->keyframes[0].value, 0.0));

    const auto* outgoingTail = find_command(fragment.commands,
                                            autodj::playback::DeckCommandType::Automate,
                                            1,
                                            autodj::playback::AutomationControl::ReverbTailGain);
    assert(outgoingTail != nullptr);
    assert(outgoingTail->postFader);
    assert(outgoingTail->keyframes.size() == 2);
    assert(nearly_equal(outgoingTail->keyframes[0].at, 64.0));
    assert(nearly_equal(outgoingTail->keyframes[0].value, 1.0));
    assert(nearly_equal(outgoingTail->keyframes[1].at, 88.0));
    assert(nearly_equal(outgoingTail->keyframes[1].value, 0.0));

    const auto* incomingLow = find_command(fragment.commands,
                                           autodj::playback::DeckCommandType::Automate,
                                           2,
                                           autodj::playback::AutomationControl::EqLow);
    assert(incomingLow == nullptr);

    const auto* outgoingStop = find_command(fragment.commands, autodj::playback::DeckCommandType::Stop, 1);
    assert(outgoingStop != nullptr);
    assert(nearly_equal(outgoingStop->at, 88.0));

    const auto* sweepStop = find_command(fragment.commands, autodj::playback::DeckCommandType::Stop, 3);
    assert(sweepStop != nullptr);
    assert(nearly_equal(sweepStop->at, sweepTimelineEndSeconds));

    assert(fragment.annotations.size() == 3);
}

void drop_end_reverb_exit_clamps_short_drop_ramp() {
    auto outgoing = make_outgoing_reverb_exit_track();
    outgoing.builds[0] = make_section("short-build", "build", 0.0, 15.0, 0);
    outgoing.drops[0] = make_section("short-drop", "drop", 15.0, 16.0, 37);
    outgoing.drops[0].endBeatIndex = 40;

    const auto result = autodj::dj::buildDropEndReverbExitTemplate(outgoing, make_incoming_reverb_exit_track());

    assert(result.ok());
    assert(contains(result.fragment->transition.riskFlags, "wash_out_ramp_clamped"));
    assert(nearly_equal(result.fragment->transition.timelineStartSeconds, 15.0));
    assert(nearly_equal(result.fragment->transition.handoffTimelineSeconds.value(), 16.0));
    assert(nearly_equal(result.fragment->transition.timelineEndSeconds, 40.0));
    assert(nearly_equal(result.fragment->transition.measureCountToTarget.value(), 0.625));
}

void drop_end_reverb_exit_rejects_missing_drop_end() {
    auto outgoing = make_outgoing_reverb_exit_track();
    outgoing.drops.clear();

    const auto result = autodj::dj::buildDropEndReverbExitTemplate(outgoing, make_incoming_reverb_exit_track());

    assert(!result.ok());
    assert(contains_issue(result.rejectionReasons, "missing_outgoing_drop_end"));
}

void drop_end_reverb_exit_uses_exact_start_and_end_timestamps() {
    autodj::dj::DropEndReverbExitOptions options;
    options.outgoingTimelineStartSeconds = 5.0;
    options.outgoingSourceStartSeconds = 8.0;

    const auto result = autodj::dj::buildDropEndReverbExitTemplate(make_outgoing_reverb_exit_track(),
                                                                   make_incoming_reverb_exit_track(),
                                                                   options);

    assert(result.ok());
    const auto& fragment = result.fragment.value();
    assert(nearly_equal(fragment.placements[0].sourceStartSeconds, 8.0));
    assert(nearly_equal(fragment.placements[0].timelineStartSeconds, 5.0));
    assert(nearly_equal(fragment.placements[0].sourceEndSeconds.value(), 64.0));
    assert(nearly_equal(fragment.placements[0].timelineEndSeconds.value(), 85.0));
    assert(nearly_equal(fragment.transition.timelineStartSeconds, 59.4));
    assert(nearly_equal(fragment.transition.handoffTimelineSeconds.value(), 61.0));
    assert(nearly_equal(fragment.transition.timelineEndSeconds, 85.0));

    const auto* incomingLoad = find_command(fragment.commands, autodj::playback::DeckCommandType::Load, 2);
    assert(incomingLoad != nullptr);
    assert(nearly_equal(incomingLoad->at, 57.0));

    const auto* incomingPlay = find_command(fragment.commands, autodj::playback::DeckCommandType::Play, 2);
    assert(incomingPlay != nullptr);
    assert(nearly_equal(incomingPlay->at, 61.0));
}

void dubstep_strategy_planner_scans_for_exact_bpm_drop_switch_candidate() {
    const autodj::dj::DubstepDJStrategy strategy;
    auto mismatch = make_incoming_drop_switch_track(150.5);
    mismatch.trackId = autodj::domain::TrackId{"candidate-mismatch"};
    auto exact = make_incoming_drop_switch_track(150.0);
    exact.trackId = autodj::domain::TrackId{"candidate-exact"};

    autodj::dj::DubstepPocPlanOptions options;
    options.planId = autodj::domain::PlanId{"plan-drop-switch-scan-test"};
    const auto result = strategy.generatePocPlan(make_outgoing_drop_switch_track(), {mismatch, exact}, options);

    assert(result.ok());
    assert(result.errors.empty());
    assert(result.selectedTemplateId == "second_build_drop_switch_v1");
    assert(result.selectedIncomingTrackId.has_value());
    assert(result.selectedIncomingTrackId->value == "candidate-exact");
    assert(result.nextOutgoingTrackId.has_value());
    assert(result.nextOutgoingTrackId->value == "candidate-exact");
    assert(result.nextOutgoingDeck == 2);

    const auto& plan = result.plan.value();
    assert(plan.planId.value == "plan-drop-switch-scan-test");
    assert(plan.strategy.strategyId == "dubstep-dj");
    assert(plan.strategy.strategyVersion == "0.3.0");
    assert(plan.assets.size() == 2);
    assert(plan.tracks.size() == 2);
    assert(plan.transitions.size() == 1);
    assert(plan.transitions[0].technique == autodj::playback::TransitionTechnique::BuildToDropSwap);
    assert(plan.transitions[0].templateId == "second_build_drop_switch_v1");
    assert(plan.tracks[1].trackId.value == "candidate-exact");

    const auto json = autodj::dj::serializeMixPlanJson(plan);
    const auto parsed = autodj::playback::parseMixPlan(json);
    assert(parsed.validation.ok);
    assert(parsed.plan.has_value());
    assert(parsed.plan->transitions[0].technique == autodj::playback::TransitionTechnique::BuildToDropSwap);
}

void dubstep_strategy_planner_generates_one_sided_tempo_stretched_drop_switch() {
    const autodj::dj::DubstepDJStrategy strategy;
    auto incoming = make_incoming_drop_switch_track(155.0);
    incoming.trackId = autodj::domain::TrackId{"candidate-stretched"};

    const auto result = strategy.generatePocPlan(make_outgoing_drop_switch_track(150.0), {incoming});

    assert(result.ok());
    assert(result.selectedTemplateId == "second_build_drop_switch_v1");
    assert(result.selectedIncomingTrackId.has_value());
    assert(result.selectedIncomingTrackId->value == "candidate-stretched");
    const auto& plan = result.plan.value();
    assert(plan.tracks.size() == 2);
    const auto& incomingPlacement = plan.tracks[1];
    assert(incomingPlacement.tempoPlan.has_value());
    assert(nearly_equal(incomingPlacement.tempoPlan->sourceBpm.value(), 155.0));
    assert(nearly_equal(incomingPlacement.tempoPlan->targetBpm.value(), 150.0));
    assert(nearly_equal(incomingPlacement.tempoPlan->tempoRatio.value(), 150.0 / 155.0));
    assert(incomingPlacement.tempoPlan->backend == "soundstretch");
    assert(plan.transitions[0].tempoPlan.has_value());
    assert(contains(plan.transitions[0].riskFlags, "incoming_tempo_stretch_requires_validation"));

    const auto* tempo = find_command(plan.commands,
                                     autodj::playback::DeckCommandType::Automate,
                                     2,
                                     autodj::playback::AutomationControl::Tempo);
    assert(tempo != nullptr);
    assert(nearly_equal(tempo->keyframes.front().value, 150.0 / 155.0));

    const auto json = autodj::dj::serializeMixPlanJson(plan);
    const auto parsed = autodj::playback::parseMixPlan(json);
    assert(parsed.validation.ok);
    assert(parsed.plan.has_value());
    assert(parsed.plan->tracks[1].tempoPlan.has_value());
}

void dubstep_strategy_planner_can_disable_tempo_stretched_drop_switches() {
    const autodj::dj::DubstepDJStrategy strategy;
    auto incoming = make_incoming_drop_switch_track(155.0);
    incoming.trackId = autodj::domain::TrackId{"candidate-stretch-disabled"};
    autodj::dj::DubstepPocPlanOptions options;
    options.allowTempoStretch = false;

    const auto result = strategy.generatePocPlan(make_outgoing_drop_switch_track(150.0), {incoming}, options);

    assert(result.ok());
    assert(contains_issue(result.candidateRejections, "bpm_mismatch_for_drop_switch"));
    assert(result.selectedTemplateId == "drop_end_wash_out_v1");
    assert(!result.plan->transitions[0].tempoPlan.has_value());
}

void dubstep_strategy_planner_falls_back_to_wash_out_without_exact_bpm_candidate() {
    const autodj::dj::DubstepDJStrategy strategy;
    auto incoming = make_incoming_reverb_exit_track(170.0);
    incoming.trackId = autodj::domain::TrackId{"fallback-candidate"};

    const auto result = strategy.generatePocPlan(make_outgoing_drop_switch_track(), {incoming});

    assert(result.ok());
    assert(contains_issue(result.candidateRejections, "tempo_adjustment_over_gate"));
    assert(result.selectedTemplateId == "drop_end_wash_out_v1");
    assert(result.selectedIncomingTrackId.has_value());
    assert(result.selectedIncomingTrackId->value == "fallback-candidate");
    assert(result.nextOutgoingTrackId.has_value());
    assert(result.nextOutgoingTrackId->value == "fallback-candidate");
    assert(result.nextOutgoingDeck == 2);
    assert(result.plan->transitions.size() == 1);
    assert(result.plan->transitions[0].technique == autodj::playback::TransitionTechnique::WashOut);

    const auto json = autodj::dj::serializeMixPlanJson(result.plan.value());
    const auto parsed = autodj::playback::parseMixPlan(json);
    assert(parsed.validation.ok);
    assert(parsed.plan.has_value());
    assert(parsed.plan->transitions[0].templateId == "drop_end_wash_out_v1");
}

void dubstep_strategy_rejects_confident_key_clash_for_drop_switch() {
    const autodj::dj::DubstepDJStrategy strategy;
    auto outgoing = make_outgoing_drop_switch_track();
    auto incoming = make_incoming_drop_switch_track();
    set_key(outgoing, "9A", 0.92);
    set_key(incoming, "3A", 0.9);

    const auto result = strategy.generatePocPlan(outgoing, {incoming});

    assert(result.ok());
    const auto& transition = result.plan->transitions[0];
    assert(transition.templateId == "drop_end_wash_out_v1");
    assert(contains_issue(result.candidateRejections, "camelot_key_clash_for_drop_switch"));
    assert(contains(transition.riskFlags, "camelot_key_clash_warning"));
}

void dubstep_strategy_prefers_compatible_drop_switch_over_key_clash() {
    const autodj::dj::DubstepDJStrategy strategy;
    auto outgoing = make_outgoing_drop_switch_track();
    set_key(outgoing, "9A", 0.92);
    auto clash = make_incoming_drop_switch_track();
    clash.trackId = autodj::domain::TrackId{"candidate-clash"};
    set_key(clash, "3A", 0.9);
    auto compatible = make_incoming_drop_switch_track();
    compatible.trackId = autodj::domain::TrackId{"candidate-compatible"};
    set_key(compatible, "10A", 0.9);

    const auto result = strategy.generatePocPlan(outgoing, {clash, compatible});

    assert(result.ok());
    assert(result.selectedIncomingTrackId.has_value());
    assert(result.selectedIncomingTrackId->value == "candidate-compatible");
    const auto& transition = result.plan->transitions[0];
    assert(!contains(transition.riskFlags, "camelot_key_clash_downranked"));
    assert(std::find_if(transition.reasons.begin(), transition.reasons.end(), [](const auto& reason) {
               return reason.find("Camelot compatibility: adjacent") != std::string::npos;
           }) != transition.reasons.end());
}

void dubstep_strategy_warns_but_does_not_block_wash_out_key_clash() {
    const autodj::dj::DubstepDJStrategy strategy;
    auto outgoing = make_outgoing_reverb_exit_track();
    auto incoming = make_incoming_reverb_exit_track(151.0);
    incoming.trackId = autodj::domain::TrackId{"reverb-clash-candidate"};
    set_key(outgoing, "9A", 0.92);
    set_key(incoming, "3A", 0.9);

    const auto result = strategy.generatePocPlan(outgoing, {incoming});

    assert(result.ok());
    const auto& transition = result.plan->transitions[0];
    assert(transition.templateId == "drop_end_wash_out_v1");
    assert(contains(transition.riskFlags, "camelot_key_clash_warning"));
    assert(transition.score > 0.6);
}

void dubstep_strategy_low_confidence_key_does_not_hard_reject_drop_switch() {
    const autodj::dj::DubstepDJStrategy strategy;
    auto outgoing = make_outgoing_drop_switch_track();
    auto incoming = make_incoming_drop_switch_track();
    set_key(outgoing, "9A", 0.4);
    set_key(incoming, "3A", 0.4);

    const auto result = strategy.generatePocPlan(outgoing, {incoming});

    assert(result.ok());
    assert(result.selectedTemplateId == "second_build_drop_switch_v1");
    const auto& transition = result.plan->transitions[0];
    assert(contains(transition.riskFlags, "key_compatibility_unknown"));
    assert(!contains_issue(result.candidateRejections, "low_key_confidence"));
}

void dubstep_strategy_planner_rejects_when_no_template_is_valid() {
    const autodj::dj::DubstepDJStrategy strategy;
    auto outgoing = make_outgoing_reverb_exit_track();
    outgoing.drops.clear();
    auto incoming = make_incoming_reverb_exit_track();
    incoming.beats.clear();

    const auto result = strategy.generatePocPlan(outgoing, {incoming});

    assert(!result.ok());
    assert(!result.plan.has_value());
    assert(contains_issue(result.errors, "no_valid_transition_template"));
    assert(contains_issue(result.candidateRejections, "missing_outgoing_second_build_drop"));
    assert(contains_issue(result.candidateRejections, "missing_outgoing_drop_end"));
}

}  // namespace

int main() {
    dubstep_strategy_implements_strategy_contract();
    dubstep_strategy_reports_dubstep_support();
    placeholder_plan_is_mix_plan_shaped();
    placeholder_plan_does_not_reference_audio_files();
    analysis_summary_reads_contract_fixture();
    analysis_summary_reads_key_metadata_and_risk_flags();
    analysis_summary_orders_sections_and_cues();
    analysis_summary_rejects_invalid_artifacts();
    drop_switch_template_generates_aligned_plan_fragment();
    drop_switch_template_rejects_when_incoming_lacks_enough_predrop_beats();
    drop_switch_template_rejects_missing_sections();
    drop_switch_template_rejects_low_confidence_sections();
    drop_switch_template_rejects_exact_bpm_mismatch();
    drop_switch_template_rejects_too_short_handoff();
    drop_end_reverb_exit_generates_full_ramp_fragment();
    drop_end_reverb_exit_clamps_short_drop_ramp();
    drop_end_reverb_exit_rejects_missing_drop_end();
    drop_end_reverb_exit_uses_exact_start_and_end_timestamps();
    dubstep_strategy_planner_scans_for_exact_bpm_drop_switch_candidate();
    dubstep_strategy_planner_generates_one_sided_tempo_stretched_drop_switch();
    dubstep_strategy_planner_can_disable_tempo_stretched_drop_switches();
    dubstep_strategy_planner_falls_back_to_wash_out_without_exact_bpm_candidate();
    dubstep_strategy_rejects_confident_key_clash_for_drop_switch();
    dubstep_strategy_prefers_compatible_drop_switch_over_key_clash();
    dubstep_strategy_warns_but_does_not_block_wash_out_key_clash();
    dubstep_strategy_low_confidence_key_does_not_hard_reject_drop_switch();
    dubstep_strategy_planner_rejects_when_no_template_is_valid();

    return 0;
}
