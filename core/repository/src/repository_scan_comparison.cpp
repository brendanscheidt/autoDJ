#include "autodj/repository/repository_scan_comparison.hpp"

#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace autodj::repository {

RepositoryScanResult compareScanResultToManifest(RepositoryScanResult currentScan,
                                                 const RepositoryManifest& previousManifest) {
    std::unordered_map<std::string, std::string> previousHashesByTrackId;
    previousHashesByTrackId.reserve(previousManifest.tracks.size());
    for (const auto& track : previousManifest.tracks) {
        previousHashesByTrackId[track.trackId.value] = track.contentHash;
    }

    std::unordered_set<std::string> currentTrackIds;
    currentTrackIds.reserve(currentScan.tracks.size());

    std::size_t tracksAdded = 0;
    std::size_t tracksUpdated = 0;

    for (const auto& track : currentScan.tracks) {
        currentTrackIds.insert(track.trackId.value);
        const auto previous = previousHashesByTrackId.find(track.trackId.value);
        if (previous == previousHashesByTrackId.end()) {
            ++tracksAdded;
            continue;
        }
        if (previous->second != track.contentHash) {
            ++tracksUpdated;
        }
    }

    std::size_t tracksRemoved = 0;
    for (const auto& track : previousManifest.tracks) {
        if (!currentTrackIds.contains(track.trackId.value)) {
            ++tracksRemoved;
        }
    }

    currentScan.tracksAdded = tracksAdded;
    currentScan.tracksUpdated = tracksUpdated;
    currentScan.tracksRemoved = tracksRemoved;
    return currentScan;
}

}  // namespace autodj::repository
