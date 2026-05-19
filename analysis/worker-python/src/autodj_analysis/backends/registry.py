"""Registry helpers for selecting candidate analysis backends by name."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Literal, TypeVar

from .base import BeatGridBackend, SectionBackend, TempoBackend


BackendKind = Literal["tempo", "beat_grid", "section"]
TBackend = TypeVar("TBackend")


@dataclass(frozen=True)
class BackendRegistryError(ValueError):
    """Structured backend registry error."""

    code: str
    message: str
    backend_kind: BackendKind
    backend_name: str

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "backendKind": self.backend_kind,
            "backendName": self.backend_name,
        }


class _BackendFactories(Generic[TBackend]):
    def __init__(self, kind: BackendKind) -> None:
        self._kind = kind
        self._factories: dict[str, Callable[[], TBackend]] = {}

    def register(self, name: str, factory: Callable[[], TBackend]) -> None:
        if not name:
            raise ValueError("backend name must not be empty")
        if name in self._factories:
            raise BackendRegistryError(
                code="backend_already_registered",
                message=f"{self._kind} backend is already registered: {name}",
                backend_kind=self._kind,
                backend_name=name,
            )
        self._factories[name] = factory

    def create(self, name: str) -> TBackend:
        try:
            factory = self._factories[name]
        except KeyError:
            raise BackendRegistryError(
                code="backend_not_registered",
                message=f"{self._kind} backend is not registered: {name}",
                backend_kind=self._kind,
                backend_name=name,
            ) from None
        return factory()

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


class BackendRegistry:
    """Holds backend factories so orchestration can select by configured name."""

    def __init__(self) -> None:
        self._tempo = _BackendFactories[TempoBackend]("tempo")
        self._beat_grid = _BackendFactories[BeatGridBackend]("beat_grid")
        self._section = _BackendFactories[SectionBackend]("section")

    def register_tempo(self, name: str, factory: Callable[[], TempoBackend]) -> None:
        self._tempo.register(name, factory)

    def register_beat_grid(self, name: str, factory: Callable[[], BeatGridBackend]) -> None:
        self._beat_grid.register(name, factory)

    def register_section(self, name: str, factory: Callable[[], SectionBackend]) -> None:
        self._section.register(name, factory)

    def create_tempo(self, name: str) -> TempoBackend:
        return self._tempo.create(name)

    def create_beat_grid(self, name: str) -> BeatGridBackend:
        return self._beat_grid.create(name)

    def create_section(self, name: str) -> SectionBackend:
        return self._section.create(name)

    def tempo_names(self) -> tuple[str, ...]:
        return self._tempo.names()

    def beat_grid_names(self) -> tuple[str, ...]:
        return self._beat_grid.names()

    def section_names(self) -> tuple[str, ...]:
        return self._section.names()
