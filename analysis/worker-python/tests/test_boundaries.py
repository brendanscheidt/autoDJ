import ast
from pathlib import Path
import re
import subprocess
import tomllib

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER_ROOT = REPO_ROOT / "analysis" / "worker-python"
SOURCE_ROOT = WORKER_ROOT / "src" / "autodj_analysis"
PYPROJECT = WORKER_ROOT / "pyproject.toml"

FORBIDDEN_IMPORT_ROOTS = {
    "apps",
    "autodj_desktop",
    "autodj_dj",
    "autodj_playback",
    "autodj_repository",
    "core",
    "dj",
    "juce",
    "playback",
}
EXPECTED_ANALYSIS_DEPENDENCIES = {
    "audioread",
    "librosa",
    "numpy",
    "scipy",
    "soundfile",
}
EXPECTED_WSL_ANALYSIS_DEPENDENCIES = EXPECTED_ANALYSIS_DEPENDENCIES | {"essentia"}
EXPECTED_CANDIDATE_DEPENDENCIES = {
    "audioflux",
    "mir_eval",
    "pyaudioanalysis",
}
APPROVED_OPTIONAL_DEPENDENCIES = (
    EXPECTED_ANALYSIS_DEPENDENCIES
    | EXPECTED_WSL_ANALYSIS_DEPENDENCIES
    | EXPECTED_CANDIDATE_DEPENDENCIES
)
FORBIDDEN_DIRECT_DEPENDENCIES = {
    "demucs",
}
DISALLOWED_GIT_PATH_PREFIXES = (
    ".autodj-cache/",
    "generated-stems/",
    "generated-waveforms/",
    "stems/",
    "waveforms/",
)
DISALLOWED_GIT_SUFFIXES = (
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".stem.wav",
    ".wav",
    ".waveform.json",
)


def test_worker_source_does_not_import_ui_playback_dj_or_cpp_repository_modules() -> None:
    violations: list[str] = []

    for source_file in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            imported_roots = _imported_roots(node)
            for root in imported_roots:
                if root in FORBIDDEN_IMPORT_ROOTS:
                    violations.append(f"{source_file.relative_to(REPO_ROOT)} imports {root!r}")

    assert violations == []


def test_worker_package_keeps_analysis_dependencies_in_optional_extras() -> None:
    pyproject = _pyproject_data()
    direct_dependencies = {
        _dependency_name(dependency)
        for dependency in pyproject["project"].get("dependencies", [])
    }

    assert direct_dependencies.isdisjoint(APPROVED_OPTIONAL_DEPENDENCIES)


def test_worker_package_declares_approved_analysis_extras() -> None:
    extras = _pyproject_data()["project"]["optional-dependencies"]
    analysis = {_dependency_name(dependency) for dependency in extras["analysis"]}
    analysis_wsl = {_dependency_name(dependency) for dependency in extras["analysis-wsl"]}
    candidates = {_dependency_name(dependency) for dependency in extras["analysis-candidates"]}

    assert analysis == EXPECTED_ANALYSIS_DEPENDENCIES
    assert analysis_wsl == EXPECTED_WSL_ANALYSIS_DEPENDENCIES
    assert candidates == EXPECTED_CANDIDATE_DEPENDENCIES
    assert (analysis | analysis_wsl | candidates).issubset(APPROVED_OPTIONAL_DEPENDENCIES)


def test_worker_package_does_not_add_disallowed_heavy_dependencies() -> None:
    pyproject = PYPROJECT.read_text(encoding="utf-8").lower()
    violations = [
        dependency
        for dependency in sorted(FORBIDDEN_DIRECT_DEPENDENCIES)
        if re.search(rf"(?<![a-z0-9_.-]){re.escape(dependency)}(?![a-z0-9_.-])", pyproject)
    ]

    assert violations == []


def test_git_index_has_no_local_media_or_generated_cache_artifacts() -> None:
    paths = _git_candidate_paths()
    violations = [path for path in paths if _is_disallowed_git_artifact_path(path)]

    assert violations == []


@pytest.mark.parametrize(
    "path",
    [
        ".autodj-cache/tracks/track-a/analyzed-track.json",
        "fixtures/.autodj-cache/tracks/track-a/waveform.json",
        "generated-stems/track-a/vocals.wav",
        "debug/generated-waveforms/track-a.waveform.json",
        "stems/track-a/vocals.wav",
        "manual/waveforms/track-a.waveform.json",
        "music/local-song.mp3",
        "analysis-output/track-a.stem.wav",
        "analysis-output/track-a.waveform.json",
    ],
)
def test_disallowed_git_artifact_policy_rejects_generated_cache_and_media_paths(path: str) -> None:
    assert _is_disallowed_git_artifact_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "analysis/worker-python/tests/test_boundaries.py",
        "core/contracts/schemas/analyzed-track.schema.json",
        "fixtures/metadata/example-analyzed-track.json",
        ".codex/specs/004-real-audio-analysis-baseline/tasks.md",
    ],
)
def test_disallowed_git_artifact_policy_allows_source_and_metadata_paths(path: str) -> None:
    assert not _is_disallowed_git_artifact_path(path)


def _imported_roots(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name.split(".", 1)[0] for alias in node.names}
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return {node.module.split(".", 1)[0]}
    return set()


def _pyproject_data() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _dependency_name(dependency: str) -> str:
    return re.split(r"\s*(?:[<>=!~]=?|;|\[)", dependency, maxsplit=1)[0].lower()


def _is_disallowed_git_artifact_path(path: str) -> bool:
    normalized_path = path.replace("\\", "/")
    return (
        normalized_path.startswith(DISALLOWED_GIT_PATH_PREFIXES)
        or normalized_path.endswith(DISALLOWED_GIT_SUFFIXES)
        or "/.autodj-cache/" in normalized_path
        or "/generated-stems/" in normalized_path
        or "/generated-waveforms/" in normalized_path
        or "/stems/" in normalized_path
        or "/waveforms/" in normalized_path
    )


def _git_candidate_paths() -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        pytest.skip("git executable is unavailable")

    assert completed.returncode == 0, completed.stderr
    return [
        path.replace("\\", "/")
        for path in completed.stdout.split("\0")
        if path
    ]
