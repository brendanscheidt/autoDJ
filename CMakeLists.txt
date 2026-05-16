cmake_minimum_required(VERSION 3.24)

project(
    AutoDJ
    VERSION 0.1.0
    DESCRIPTION "Desktop-first AutoDJ foundation for local audio files"
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

enable_testing()

add_subdirectory(core/domain)
add_subdirectory(core/contracts)
add_subdirectory(core/repository)
add_subdirectory(core/playback)
add_subdirectory(core/dj)
add_subdirectory(apps/autodj-desktop)
