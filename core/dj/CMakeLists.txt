add_library(autodj_dj STATIC
    src/analyzed_track_summary.cpp
    src/drop_end_reverb_exit.cpp
    src/dubstep_dj_strategy.cpp
    src/second_build_drop_switch.cpp
)

target_include_directories(autodj_dj
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_compile_features(autodj_dj PUBLIC cxx_std_20)

target_link_libraries(autodj_dj
    PUBLIC
        autodj_domain
        autodj_playback
)

add_executable(autodj_dj_tests
    tests/dj_tests.cpp
)

target_link_libraries(autodj_dj_tests
    PRIVATE
        autodj_dj
)

target_compile_definitions(autodj_dj_tests
    PRIVATE
        AUTODJ_CONTRACTS_DIR="${CMAKE_SOURCE_DIR}/core/contracts"
)

add_test(NAME autodj_dj_tests COMMAND autodj_dj_tests)

add_executable(autodj_mixplan_poc
    tools/mixplan_poc.cpp
)

target_link_libraries(autodj_mixplan_poc
    PRIVATE
        autodj_dj
)
