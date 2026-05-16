add_test(
    NAME autodj_contract_examples
    COMMAND
        ${CMAKE_COMMAND}
        "-DCONTRACTS_DIR=${CMAKE_CURRENT_SOURCE_DIR}"
        -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/validate_contract_examples.cmake"
)
