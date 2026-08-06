"""Backend registry — the one place printers are discovered from.

Registration is an explicit decorator plus an explicit import line in
``backends/__init__.py``, deliberately not ``pkgutil`` auto-discovery: PyInstaller
walks the static import graph from ``main.py`` and would silently drop any
dynamically-imported backend from the frozen build. Two visible lines beat a
printer that works from source and vanishes in the shipped .exe.
"""

from __future__ import annotations

from typing import Any, Iterator

from .base import LabelPrinterBackend

# The backend id used whenever a persisted selection can't be honoured. Kept
# here rather than in the UI so the fallback rule has one owner.
FALLBACK_BACKEND_ID = "system"


class DuplicateBackendIdError(ValueError):
    """Raised when two backends claim the same id.

    Loud on purpose. Backend ids are persisted in operator settings, so a
    copy-pasted id would silently shadow a working printer and quietly redirect
    whatever the operator had selected. The test suite exercises this, so a
    duplicate is caught in CI rather than in a frozen build.
    """


class Registry:
    """An ordered collection of backend classes.

    Holds classes, never instances: instantiating a backend can construct a
    ``QPrinter``, which fast-fails if no ``QApplication`` exists yet, and the
    registry is populated at import time.

    Instantiable rather than purely global so tests can register a fake backend
    without mutating (or having to clean up) the process-wide registry.
    """

    def __init__(self) -> None:
        self._backends: dict[str, type[LabelPrinterBackend]] = {}

    def register(self, cls: type[LabelPrinterBackend]) -> type[LabelPrinterBackend]:
        backend_id = getattr(cls, "id", None)
        if not backend_id or not isinstance(backend_id, str):
            raise ValueError(f"{cls.__name__} must define a non-empty string `id`")
        if not getattr(cls, "display_name", None):
            raise ValueError(f"{cls.__name__} must define a non-empty `display_name`")
        if backend_id in self._backends:
            existing = self._backends[backend_id].__name__
            raise DuplicateBackendIdError(
                f"backend id {backend_id!r} is already registered by {existing}; "
                f"{cls.__name__} cannot claim it. Backend ids are persisted in "
                f"operator settings and must be unique — pick a different id."
            )
        self._backends[backend_id] = cls
        return cls

    def get(self, backend_id: str) -> type[LabelPrinterBackend] | None:
        return self._backends.get(backend_id)

    def classes(self) -> tuple[type[LabelPrinterBackend], ...]:
        """Registered backends in display order.

        Sorted by the declared ``sort_order`` then display name, so the operator's
        dropdown never reshuffles because someone moved an import line.
        """
        return tuple(
            sorted(
                self._backends.values(),
                key=lambda c: (getattr(c, "sort_order", 100), c.display_name),
            )
        )

    def ids(self) -> tuple[str, ...]:
        return tuple(c.id for c in self.classes())

    def __contains__(self, backend_id: object) -> bool:
        return backend_id in self._backends

    def __len__(self) -> int:
        return len(self._backends)

    def __iter__(self) -> Iterator[type[LabelPrinterBackend]]:
        return iter(self.classes())


# The registry the application uses. Backends register into it at import time via
# the decorator below; `app.services.printing` imports the backends package so
# that importing anything from this package is enough to populate it.
_DEFAULT = Registry()


def default_registry() -> Registry:
    return _DEFAULT


def register_backend(cls: type[LabelPrinterBackend]) -> type[LabelPrinterBackend]:
    """Class decorator that adds a backend to the default registry."""
    return _DEFAULT.register(cls)


def validate_registry(registry: Registry | None = None) -> list[str]:
    """Return a list of contract violations; empty means healthy.

    Exercised by the test suite rather than at startup — a backend that fails
    this is a programming error to catch in CI, not something an operator can fix.
    """
    reg = registry or _DEFAULT
    problems: list[str] = []
    for cls in reg.classes():
        name = cls.__name__
        for attr in ("id", "display_name", "capabilities", "sort_order"):
            if not hasattr(cls, attr):
                problems.append(f"{name} is missing ClassVar `{attr}`")
        for method in (
            "availability",
            "refresh_availability",
            "configure",
            "print_label",
            "options",
            "apply_options",
            "actions",
        ):
            if not callable(getattr(cls, method, None)):
                problems.append(f"{name} does not implement `{method}()`")
    if FALLBACK_BACKEND_ID not in reg:
        problems.append(
            f"no {FALLBACK_BACKEND_ID!r} backend registered — "
            "there would be nothing to fall back to"
        )
    return problems


def describe(registry: Registry | None = None) -> list[dict[str, Any]]:
    """Registry contents as plain data — used by docs and tests."""
    reg = registry or _DEFAULT
    return [
        {
            "id": c.id,
            "display_name": c.display_name,
            "sort_order": getattr(c, "sort_order", 100),
            "configurable": c.capabilities.configurable,
        }
        for c in reg.classes()
    ]
