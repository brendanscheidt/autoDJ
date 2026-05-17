from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
import importlib.util
import os
from pathlib import Path
import sys

import pytest

from autodj_analysis.dependencies import OptionalDependencyUnavailable, require_optional_dependency


ANALYSIS_DEPENDENCIES = (
    ("numpy", "numpy", "analysis"),
    ("scipy", "scipy", "analysis"),
    ("librosa", "librosa", "analysis"),
    ("soundfile", "soundfile", "analysis"),
    ("audioread", "audioread", "analysis"),
)
WSL_ANALYSIS_DEPENDENCIES = (
    ("essentia", "essentia", "analysis-wsl"),
)
CANDIDATE_DEPENDENCIES = (
    ("audioflux", "audioflux", "analysis-candidates"),
    ("mir_eval", "mir_eval", "analysis-candidates"),
    ("pyAudioAnalysis", "pyAudioAnalysis", "analysis-candidates"),
)


@pytest.mark.analysis
@pytest.mark.parametrize(("dependency", "module_name", "install_extra"), ANALYSIS_DEPENDENCIES)
def test_analysis_extra_dependency_imports(
    dependency: str,
    module_name: str,
    install_extra: str,
) -> None:
    module = _import_optional_dependency(
        dependency,
        module_name,
        install_extra,
        required=_requires_wsl_analysis_stack(),
    )

    assert module.__name__.split(".", 1)[0].lower() == module_name.lower()
    assert _distribution_version(dependency)


@pytest.mark.analysis_wsl
@pytest.mark.parametrize(("dependency", "module_name", "install_extra"), WSL_ANALYSIS_DEPENDENCIES)
def test_wsl_analysis_dependency_imports(
    dependency: str,
    module_name: str,
    install_extra: str,
) -> None:
    module = _import_optional_dependency(
        dependency,
        module_name,
        install_extra,
        required=_requires_wsl_analysis_stack(),
    )

    assert module.__name__.split(".", 1)[0] == module_name
    assert getattr(module, "__version__", None)


@pytest.mark.analysis_candidate
@pytest.mark.parametrize(("dependency", "module_name", "install_extra"), CANDIDATE_DEPENDENCIES)
def test_candidate_dependency_imports_when_installed(
    dependency: str,
    module_name: str,
    install_extra: str,
) -> None:
    module = _import_optional_dependency(
        dependency,
        module_name,
        install_extra,
        required=False,
    )

    assert module.__name__.split(".", 1)[0] == module_name
    assert _distribution_version(dependency)


def _import_optional_dependency(
    dependency: str,
    module_name: str,
    install_extra: str,
    *,
    required: bool,
):
    if importlib.util.find_spec(module_name) is None:
        message = (
            f"{dependency} is not installed; install the worker with "
            f"`[{install_extra}]` to run this smoke test."
        )
        if required:
            pytest.fail(message)
        pytest.skip(message)

    try:
        return require_optional_dependency(
            dependency,
            module_name=module_name,
            install_extra=install_extra,
        )
    except OptionalDependencyUnavailable as exc:
        pytest.fail(str(exc.to_dict()))


def _requires_wsl_analysis_stack() -> bool:
    return os.environ.get("AUTODJ_REQUIRE_ANALYSIS_WSL") == "1" or _is_wsl_analysis_venv()


def _is_wsl_analysis_venv() -> bool:
    virtual_env = os.environ.get("VIRTUAL_ENV")
    active_name = Path(virtual_env).name if virtual_env else Path(sys.prefix).name
    return sys.platform.startswith("linux") and active_name == ".venv-analysis"


def _distribution_version(distribution_name: str) -> str:
    try:
        return version(distribution_name)
    except PackageNotFoundError:
        pytest.fail(f"Distribution metadata for {distribution_name!r} was not found")
