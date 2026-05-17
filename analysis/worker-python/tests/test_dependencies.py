import importlib

import pytest

from autodj_analysis.dependencies import OptionalDependencyUnavailable, require_optional_dependency


def test_require_optional_dependency_returns_imported_module() -> None:
    module = require_optional_dependency("json")

    assert module.__name__ == "json"


def test_require_optional_dependency_reports_missing_dependency_as_structured_error() -> None:
    with pytest.raises(OptionalDependencyUnavailable) as exc_info:
        require_optional_dependency(
            "missing-analysis-lib",
            module_name="autodj_missing_optional_dependency_xyz",
            install_extra="analysis",
        )

    error = exc_info.value.to_dict()
    assert error["code"] == "analysis_dependency_missing"
    assert error["dependency"] == "missing-analysis-lib"
    assert error["moduleName"] == "autodj_missing_optional_dependency_xyz"
    assert error["installExtra"] == "analysis"
    assert "Install the worker with the 'analysis' extra" in error["message"]


def test_require_optional_dependency_reports_import_errors_as_structured_errors(monkeypatch) -> None:
    def fail_import(name: str):
        assert name == "broken_backend"
        raise ImportError("shared object load failed")

    monkeypatch.setattr(importlib, "import_module", fail_import)

    with pytest.raises(OptionalDependencyUnavailable) as exc_info:
        require_optional_dependency(
            "broken-backend",
            module_name="broken_backend",
            install_extra="analysis-candidates",
        )

    error = exc_info.value.to_dict()
    assert error["code"] == "analysis_dependency_import_error"
    assert error["dependency"] == "broken-backend"
    assert error["moduleName"] == "broken_backend"
    assert error["installExtra"] == "analysis-candidates"
    assert "shared object load failed" in error["message"]
