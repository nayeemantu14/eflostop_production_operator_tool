"""Which printer backend is selected, and remembering it across restarts.

One selection for the whole application: all three device tabs print the same
labels on the same physical printer, so their selector combos are views over the
single :class:`PrinterSelection` instance and sync through its ``changed`` signal.

Storage is QSettings, not the YAML config. When frozen, the YAML resolves inside
PyInstaller's ``_internal/`` directory, which an operator cannot edit and which
the installer overwrites on every upgrade; QSettings is per-user, writable from
an installed location, and survives upgrades. The YAML stays the read-only
factory default that seeds a backend the first time it is used.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol

from PyQt6.QtCore import QCoreApplication, QObject, QSettings, pyqtSignal

from .base import Availability, LabelPrinterBackend
from .registry import FALLBACK_BACKEND_ID, Registry, default_registry

log = logging.getLogger(__name__)

# Explicit organisation/application rather than a bare QSettings(). A bare
# QSettings constructed before QApplication.setOrganizationName() runs is
# permanently stuck reporting an empty path and AccessError — it does not
# recover when the name is set later — and main.py imports the whole UI tree
# before it sets those names. Passing them explicitly makes storage independent
# of import order.
SETTINGS_ORG = "eFloStop"
SETTINGS_APP = "eFloStop II Production Tool"

SELECTED_BACKEND_KEY = "label_printer/backend"
BACKEND_OPTIONS_PREFIX = "label_printer/backends"


class SettingsStore(Protocol):
    """Minimal persistence port, so tests never touch the real registry."""

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


class QSettingsStore:
    """QSettings-backed store.

    Values are always strings: QSettings' native Windows-registry backend loses
    types across processes (a stored ``True`` reads back as the string
    ``'true'``, whose truthiness is the opposite of what you want for ``'false'``,
    and ``1.5`` reads back as ``'1.5'``). Everything structured therefore goes
    through JSON, which round-trips identically on the registry and INI backends.

    A fresh QSettings per call rather than a cached one, so a store built early
    can never pin itself to a stale path.
    """

    def _settings(self) -> QSettings:
        return QSettings(SETTINGS_ORG, SETTINGS_APP)

    def get(self, key: str) -> str | None:
        value = self._settings().value(key)
        return value if isinstance(value, str) and value else None

    def set(self, key: str, value: str) -> None:
        settings = self._settings()
        settings.setValue(key, value)
        settings.sync()


class DictStore:
    """In-memory store for tests and for when persistence is unavailable."""

    def __init__(self, initial: Mapping[str, str] | None = None) -> None:
        self.data: dict[str, str] = dict(initial or {})

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value


class PrinterSelection(QObject):
    """The app-wide selected printer backend.

    Backend instances are created once and cached for the process lifetime, and
    are never rebuilt: the system backend's QPrinter holds the page setup the
    operator chose in the Windows print dialog, and throwing it away would break
    the "remembered for the rest of the session" behaviour the operator manual
    documents. Option changes are pushed into the live instance instead.
    """

    changed = pyqtSignal(str)
    availability_changed = pyqtSignal(str)

    def __init__(
        self,
        registry: Registry | None = None,
        store: SettingsStore | None = None,
        defaults: Mapping[str, Mapping[str, Any]] | None = None,
        default_backend_id: str = FALLBACK_BACKEND_ID,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._registry = registry or default_registry()
        self._store = store if store is not None else QSettingsStore()
        self._defaults = {k: dict(v) for k, v in (defaults or {}).items()}
        self._instances: dict[str, LabelPrinterBackend] = {}
        self._current_id = self._resolve_id(
            self._store.get(SELECTED_BACKEND_KEY) or default_backend_id
        )

    # --- identity -----------------------------------------------------------

    def _resolve_id(self, backend_id: str | None) -> str:
        """Map a possibly-stale id onto one that actually exists.

        A saved selection can name a backend that was renamed or removed by a
        tool upgrade. Degrading to the system printer keeps the line running;
        crashing or printing to nothing does not.
        """
        if backend_id and backend_id in self._registry:
            return backend_id
        if backend_id:
            log.warning(
                "printer backend %r is not registered; falling back to %r",
                backend_id,
                FALLBACK_BACKEND_ID,
            )
        if FALLBACK_BACKEND_ID in self._registry:
            return FALLBACK_BACKEND_ID
        ids = self._registry.ids()
        return ids[0] if ids else ""

    def current_id(self) -> str:
        return self._current_id

    def set_current_id(self, backend_id: str) -> None:
        """Select a backend and persist the choice.

        Idempotent on purpose. Three combos share this object, so a user change
        in one fans out to the other two; without the early return each of those
        would re-enter the setter and write settings again.
        """
        resolved = self._resolve_id(backend_id)
        if resolved == self._current_id:
            return
        self._current_id = resolved
        self._store.set(SELECTED_BACKEND_KEY, resolved)
        self.changed.emit(resolved)

    # --- backend instances --------------------------------------------------

    def _options_key(self, backend_id: str) -> str:
        return f"{BACKEND_OPTIONS_PREFIX}/{backend_id}"

    def load_options(self, backend_id: str) -> dict[str, Any]:
        """Stored options for a backend, else the YAML factory defaults."""
        raw = self._store.get(self._options_key(backend_id))
        if raw:
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    return loaded
                log.warning(
                    "stored options for backend %r are not an object; ignoring",
                    backend_id,
                )
            except (ValueError, TypeError):
                log.warning(
                    "stored options for backend %r are not valid JSON; ignoring",
                    backend_id,
                )
        return dict(self._defaults.get(backend_id, {}))

    def save_options(self, backend_id: str, options: Mapping[str, Any]) -> None:
        """Persist a backend's options as one JSON blob.

        One key per backend, not one per option: the storage layer then never
        needs to know the shape of a backend's settings, so a future printer
        with nested or list-valued options needs no change here.
        """
        try:
            self._store.set(self._options_key(backend_id), json.dumps(dict(options)))
        except (TypeError, ValueError):
            log.exception("backend %r returned non-JSON options", backend_id)

    def backend(self, backend_id: str) -> LabelPrinterBackend | None:
        """The single live instance of a backend, built on first request."""
        if backend_id in self._instances:
            return self._instances[backend_id]
        cls = self._registry.get(backend_id)
        if cls is None:
            return None
        try:
            instance = cls(self.load_options(backend_id))
        except Exception:
            # A broken backend must not take the tool down with it.
            log.exception("printer backend %r failed to initialise", backend_id)
            return None
        self._instances[backend_id] = instance
        return instance

    def current_backend(self) -> LabelPrinterBackend | None:
        return self.backend(self._current_id)

    def persist_current_options(self) -> None:
        """Write the selected backend's options back to storage.

        Also announces that the backend's state may have moved, because the
        backend instance is shared by every tab: configuring the printer on one
        tab changes what the other tabs' dropdowns should be saying about it.
        """
        backend = self.current_backend()
        if backend is None:
            return
        try:
            self.save_options(self._current_id, dict(backend.options()))
        except Exception:
            log.exception("backend %r options() failed", self._current_id)
        self.availability_changed.emit(self._current_id)

    def notify_availability_changed(self) -> None:
        """Tell every view that the selected backend's state may have moved."""
        self.availability_changed.emit(self._current_id)

    # --- what the UI renders ------------------------------------------------

    def availability_of(self, backend_id: str) -> Availability:
        """Availability of a backend, never raising."""
        backend = self.backend(backend_id)
        if backend is None:
            return Availability(False, "not installed")
        try:
            return backend.refresh_availability()
        except Exception:
            log.exception("backend %r refresh_availability() failed", backend_id)
            return Availability(False, "status check failed")

    def visible_backends(self) -> list[tuple[str, str, Availability]]:
        """(id, display_name, availability) in dropdown order.

        The selector widget renders exactly this list and knows nothing else, so
        the dropdown contents can be asserted in tests without a widget.
        """
        rows: list[tuple[str, str, Availability]] = []
        for cls in self._registry.classes():
            rows.append((cls.id, cls.display_name, self.availability_of(cls.id)))
        return rows


_selection: PrinterSelection | None = None


def shared_selection() -> PrinterSelection:
    """The application-wide selection, built on first use.

    Lazy, never at import time: this constructs a QObject and reads QSettings,
    and ``main.py`` imports the entire UI tree before the QApplication exists or
    the organisation name is set.
    """
    global _selection
    if _selection is None:
        if QCoreApplication.instance() is None:
            log.warning(
                "printer selection built with no QApplication — settings may not persist"
            )
        # Imported here so this module stays importable without the app config.
        from ...config.settings import settings

        _selection = PrinterSelection(
            defaults=settings.label_printer.backends,
            default_backend_id=settings.label_printer.backend,
        )
    return _selection


def reset_shared_selection() -> None:
    """Drop the cached selection. For tests only."""
    global _selection
    _selection = None
