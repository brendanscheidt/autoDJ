add_library(autodj_playback STATIC
    src/playback_engine.cpp
)

target_include_directories(autodj_playback
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_compile_features(autodj_playback PUBLIC cxx_std_20)

target_link_libraries(autodj_playback
    PUBLIC
        autodj_domain
)

add_executable(autodj_playback_tests
    tests/playback_tests.cpp
)

target_link_libraries(autodj_playback_tests
    PRIVATE
        autodj_playback
)

add_test(NAME autodj_playback_tests COMMAND autodj_playback_tests)

