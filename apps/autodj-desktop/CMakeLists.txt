include(FetchContent)

FetchContent_Declare(
    juce
    GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
    GIT_TAG 8.0.10
    GIT_SHALLOW TRUE
)

FetchContent_MakeAvailable(juce)

juce_add_gui_app(autodj_desktop
    PRODUCT_NAME "AutoDJ"
    COMPANY_NAME "AutoDJ"
    VERSION ${PROJECT_VERSION}
)

target_sources(autodj_desktop
    PRIVATE
        src/Main.cpp
)

target_include_directories(autodj_desktop
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_compile_definitions(autodj_desktop
    PRIVATE
        JUCE_WEB_BROWSER=0
        JUCE_USE_CURL=0
)

target_link_libraries(autodj_desktop
    PRIVATE
        autodj_dj
        autodj_playback
        autodj_repository
        juce::juce_gui_extra
)

add_executable(autodj_desktop_placeholder_tests
    tests/workbench_text_tests.cpp
)

target_include_directories(autodj_desktop_placeholder_tests
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_compile_features(autodj_desktop_placeholder_tests PRIVATE cxx_std_20)

add_test(NAME autodj_desktop_placeholder_tests COMMAND autodj_desktop_placeholder_tests)

