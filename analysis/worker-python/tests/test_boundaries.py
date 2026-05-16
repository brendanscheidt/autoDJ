import ast
from pathlib import Path
import re
import subprocess

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
FORBIDDEN_DEPENDENCIES = {
    "demucs",
    "essentia",
    "librosa",
    "numpy",
    "scipy",
    "soundfile",
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


def test_worker_package_does_not_add_heavy_analysis_dependencies() -> None:
    pyproject = PYPROJECT.read_text(encoding="utf-8").lower()
    violations = [
        dependency
        for dependency in sorted(FORBIDDEN_DEPENDENCIES)
        if re.search(rf"(?<![a-z0-9_.-]){re.escape(dependency)}(?![a-z0-9_.-])", pyproject)
    ]

    assert violations == []


def test_git_index_has_no_local_media_or_generated_cache_artifacts() -> None:
    paths = _git_candidate_paths()
    violations = [
        path
        for path in paths
        if path.startswith(DISALLOWED_GIT_PATH_PREFIXES)
        or path.endswith(DISALLOWED_GIT_SUFFIXES)
        or "/.autodj-cache/" in path
        or "/generated-stems/" in path
        or "/generated-waveforms/" in path
        or "/stems/" in path
        or "/waveforms/" in path
    ]

    assert violations == []


def _imported_roots(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name.split(".", 1)[0] for alias in node.names}
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return {node.module.split(".", 1)[0]}
    return set()


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
