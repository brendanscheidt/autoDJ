#include "autodj/repository/repository.hpp"

#include <cassert>
#include <filesystem>
#include <stdexcept>
#include <type_traits>

namespace {

void local_repository_is_constructible_with_root_and_id() {
    const std::filesystem::path root{"C:/example/music"};
    const autodj::repository::LocalAudioRepository repository{root, "local-test"};

    assert(repository.repositoryId() == "local-test");
    assert(repository.rootPath() == root);
}

void local_repository_implements_audio_repository_contract() {
    static_assert(std::is_base_of_v<autodj::repository::IAudioRepository,
                                    autodj::repository::LocalAudioRepository>);

    autodj::repository::LocalAudioRepository local{"C:/example/music", "local-contract"};
    autodj::repository::IAudioRepository& repository = local;

    assert(repository.repositoryId() == "local-contract");
}

void placeholder_scan_reports_no_changes_or_errors() {
    autodj::repository::LocalAudioRepository repository{"C:/example/music", "local-scan"};

    const auto result = repository.scan();

    assert(result.repositoryId == "local-scan");
    assert(result.tracksAdded == 0);
    assert(result.tracksUpdated == 0);
    assert(result.tracksRemoved == 0);
    assert(result.ok());
    assert(!result.changed());
}

void placeholder_track_listing_is_empty() {
    const autodj::repository::LocalAudioRepository repository{"C:/example/music", "local-empty"};

    const auto tracks = repository.listTracks();

    assert(tracks.empty());
}

void repository_tracks_use_domain_track_ids() {
    const autodj::repository::RepositoryTrack track{
        .trackId = autodj::domain::TrackId{"track-local-001"},
        .sourceUri = "file:///example/music/track.wav",
    };

    assert(track.trackId.value == "track-local-001");
    assert(track.sourceUri == "file:///example/music/track.wav");
}

void local_repository_rejects_empty_repository_id() {
    bool threw = false;

    try {
        const autodj::repository::LocalAudioRepository repository{"C:/example/music", ""};
        (void)repository;
    } catch (const std::invalid_argument&) {
        threw = true;
    }

    assert(threw);
}

}  // namespace

int main() {
    local_repository_is_constructible_with_root_and_id();
    local_repository_implements_audio_repository_contract();
    placeholder_scan_reports_no_changes_or_errors();
    placeholder_track_listing_is_empty();
    repository_tracks_use_domain_track_ids();
    local_repository_rejects_empty_repository_id();

    return 0;
}

