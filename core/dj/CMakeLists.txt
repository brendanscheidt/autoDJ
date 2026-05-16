add_library(autodj_dj STATIC
    src/dubstep_dj_strategy.cpp
)

target_include_directories(autodj_dj
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_compile_features(autodj_dj PUBLIC cxx_std_20)

target_link_libraries(autodj_dj
    PUBLIC
        autodj_domain
)

add_executable(autodj_dj_tests
    tests/dj_tests.cpp
)

target_link_libraries(autodj_dj_tests
    PRIVATE
        autodj_dj
)

add_test(NAME autodj_dj_tests COMMAND autodj_dj_tests)

