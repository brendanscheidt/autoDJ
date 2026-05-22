if(NOT DEFINED PROJECT_ROOT)
    message(FATAL_ERROR "PROJECT_ROOT is required")
endif()

set(repository_root "${PROJECT_ROOT}/core/repository")

file(GLOB_RECURSE repository_code_files
    LIST_DIRECTORIES false
    "${repository_root}/include/*"
    "${repository_root}/src/*"
)
list(APPEND repository_code_files "${repository_root}/CMakeLists.txt")

set(forbidden_code_patterns
    "#[ \t]*include[ \t]*[<\"][^>\"]*autodj/(playback|dj)/"
    "#[ \t]*include[ \t]*[<\"][^>\"]*(JuceHeader|juce_|Python\\.h|autodj_analysis)"
    "autodj::(playback|dj)::"
    "juce::"
    "(Py_Initialize|PyRun_|PyImport_|PyObject)"
    "(std::system|popen|CreateProcess|ShellExecute)"
    "(^|[^A-Za-z0-9_])(ffmpeg|ffprobe|essentia|librosa|demucs)([^A-Za-z0-9_]|$)"
    "(^|[^A-Za-z0-9_])(AudioFormatReader|AudioBuffer)([^A-Za-z0-9_]|$)"
    "(autodj_playback|autodj_dj|autodj_desktop|JUCE|Python3)"
)

set(boundary_failures "")
foreach(path IN LISTS repository_code_files)
    file(READ "${path}" contents)
    foreach(pattern IN LISTS forbidden_code_patterns)
        if(contents MATCHES "${pattern}")
            list(APPEND boundary_failures "${path} matched forbidden boundary pattern: ${pattern}")
        endif()
    endforeach()
endforeach()

execute_process(
    COMMAND git -C "${PROJECT_ROOT}" ls-files -c -o --exclude-standard
    OUTPUT_VARIABLE project_files_text
    RESULT_VARIABLE git_ls_files_result
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(NOT git_ls_files_result EQUAL 0)
    message(FATAL_ERROR "Could not list repository files with git ls-files")
endif()
string(REPLACE "\n" ";" project_relative_files "${project_files_text}")

set(artifact_failures "")
foreach(relative_path IN LISTS project_relative_files)
    if(relative_path STREQUAL "")
        continue()
    endif()
    set(path "${PROJECT_ROOT}/${relative_path}")
    file(TO_CMAKE_PATH "${path}" normalized_path)
    if(normalized_path MATCHES "/(build|\\.git|\\.venv|\\.venv-analysis|__pycache__)/")
        continue()
    endif()

    if(normalized_path MATCHES "\\.(wav|mp3|flac|aiff|aif|ogg|m4a)$")
        list(APPEND artifact_failures "${path} is an audio file in the repository tree")
    endif()

    if(normalized_path MATCHES "/\\.autodj-cache(/|$)"
       OR normalized_path MATCHES "/repository-manifest\\.json$"
       OR normalized_path MATCHES "/analyzed-track\\.json$"
       OR normalized_path MATCHES "/waveform\\.json$"
       OR normalized_path MATCHES "/stems(/|$)")
        list(APPEND artifact_failures "${path} looks like a generated cache artifact")
    endif()
endforeach()

set(all_failures ${boundary_failures} ${artifact_failures})
if(all_failures)
    list(JOIN all_failures "\n" failure_message)
    message(FATAL_ERROR "Repository boundary verification failed:\n${failure_message}")
endif()

message(STATUS "Repository boundary verification passed")
