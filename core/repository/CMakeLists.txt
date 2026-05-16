add_library(autodj_repository STATIC
    src/local_audio_repository.cpp
    src/metadata_cache_paths.cpp
    src/repository_manifest_reader.cpp
    src/repository_manifest_writer.cpp
    src/repository_scan_comparison.cpp
    src/repository_scan_workflow.cpp
    src/sha256.cpp
)

target_include_directories(autodj_repository
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_compile_features(autodj_repository PUBLIC cxx_std_20)

target_link_libraries(autodj_repository
    PUBLIC
        autodj_domain
)

add_executable(autodj_repository_tests
    tests/repository_tests.cpp
)

target_link_libraries(autodj_repository_tests
    PRIVATE
        autodj_repository
)

add_test(NAME autodj_repository_tests COMMAND autodj_repository_tests)

add_test(
    NAME autodj_repository_boundaries
    COMMAND ${CMAKE_COMMAND}
        -DPROJECT_ROOT=${PROJECT_SOURCE_DIR}
        -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/verify_repository_boundaries.cmake
)
