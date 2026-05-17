"""Optional dependency helpers for analysis backends."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from types import ModuleType


@dataclass(frozen=True)
class DependencyError:
    code: str
    dependency: str
    module_name: str
    message: str
    install_extra: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "code": self.code,
            "dependency": self.dependency,
            "moduleName": self.module_name,
            "message": self.message,
        }
        if self.install_extra is not None:
            payload["installExtra"] = self.install_extra
        return payload


class OptionalDependencyUnavailable(RuntimeError):
    """Raised when an optional analysis dependency cannot be imported."""

    def __init__(self, error: DependencyError) -> None:
        super().__init__(error.message)
        self.error = error

    def to_dict(self) -> dict[str, str]:
        return self.error.to_dict()


def require_optional_dependency(
    dependency: str,
    *,
    module_name: str | None = None,
    install_extra: str | None = None,
) -> ModuleType:
    """Import an optional dependency or raise a structured worker error."""

    import_name = module_name or dependency
    root_module = import_name.split(".", 1)[0]

    try:
        return importlib.import_module(import_name)
    except ModuleNotFoundError as exc:
        if exc.name in {root_module, import_name}:
            raise OptionalDependencyUnavailable(
                DependencyError(
                    code="analysis_dependency_missing",
                    dependency=dependency,
                    module_name=import_name,
                    install_extra=install_extra,
                    message=_missing_dependency_message(dependency, import_name, install_extra),
                )
            ) from None
        raise OptionalDependencyUnavailable(
            DependencyError(
                code="analysis_dependency_import_error",
                dependency=dependency,
                module_name=import_name,
                install_extra=install_extra,
                message=(
                    f"Optional analysis dependency '{dependency}' was found, "
                    f"but importing '{import_name}' failed because a nested "
                    f"module is missing: {exc.name}."
                ),
            )
        ) from None
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            DependencyError(
                code="analysis_dependency_import_error",
                dependency=dependency,
                module_name=import_name,
                install_extra=install_extra,
                message=(
                    f"Optional analysis dependency '{dependency}' was found, "
                    f"but importing '{import_name}' failed: {exc}."
                ),
            )
        ) from None


def _missing_dependency_message(
    dependency: str,
    module_name: str,
    install_extra: str | None,
) -> str:
    if install_extra:
        return (
            f"Optional analysis dependency '{dependency}' is required but is not "
            f"installed. Install the worker with the '{install_extra}' extra "
            f"and retry. Missing module: '{module_name}'."
        )
    return (
        f"Optional analysis dependency '{dependency}' is required but is not "
        f"installed. Missing module: '{module_name}'."
    )
