add_library(autodj_domain STATIC
    src/domain.cpp
)

target_include_directories(autodj_domain
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_compile_features(autodj_domain PUBLIC cxx_std_20)

add_executable(autodj_domain_tests
    tests/domain_tests.cpp
)

target_link_libraries(autodj_domain_tests
    PRIVATE
        autodj_domain
)

add_test(NAME autodj_domain_tests COMMAND autodj_domain_tests)

