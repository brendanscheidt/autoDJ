#pragma once

#include "autodj/repository/audio_repository.hpp"

namespace autodj::repository {

[[nodiscard]] RepositoryScanResult compareScanResultToManifest(RepositoryScanResult currentScan,
                                                               const RepositoryManifest& previousManifest);

}  // namespace autodj::repository
