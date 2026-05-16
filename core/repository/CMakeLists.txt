add_library(autodj_repository STATIC
    src/local_audio_repository.cpp
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

