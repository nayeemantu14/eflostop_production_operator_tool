"""The label-printer backend contract.

A backend is the whole answer to "how do these bits reach paper" for one class of
printer. The UI never asks which backend it is holding — it asks the backend to
describe itself, to configure itself, and to print. Adding a printer therefore
means writing one module here and registering it; see docs/PRINTER_BACKENDS.md.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from .geometry import GuardUi

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PyQt6.QtGui import QImage
    from PyQt6.QtWidgets import QWidget


@dataclass(frozen=True)
class Availability:
    """Whether a backend can print right now, and why not if it can't.

    Truthy when usable, so ``if backend.availability():`` reads naturally while
    ``.detail`` still carries something to show the operator. An operator must
    never click Print and get silence.
    """

    ok: bool
    detail: str = ""

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class BackendCapabilities:
    """What UI affordances a backend supports.

    Deliberately just one flag. Anything else a printer wants to offer — test
    print, media calibration, density — arrives through :meth:`actions`, which
    the UI renders generically. Adding a bool here for every new affordance
    would mean editing this file *and* the widget for each new printer, which is
    exactly the coupling the backend layer exists to remove.
    """

    configurable: bool = True


@dataclass(frozen=True)
class BackendAction:
    """An extra operation a backend offers, rendered as a button by the UI.

    The UI knows nothing but the label and that it is callable, so a future
    printer can add "Calibrate media" without any widget change.
    """

    label: str
    callback: Callable[["QWidget | None"], None]
    enabled: bool = True
    tooltip: str = ""


class PrintStatus(Enum):
    """Outcome of a print attempt.

    OK means the job was handed off successfully. For spooler-backed printers
    that means the Windows queue accepted it, not that a label physically came
    out — the driver gives us nothing stronger, and today's code makes the same
    (silent) assumption.
    """

    OK = "ok"
    CANCELLED = "cancelled"  # operator declined a guard; say nothing further
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class PrintResult:
    status: PrintStatus
    title: str = ""
    message: str = ""

    @property
    def is_ok(self) -> bool:
        return self.status is PrintStatus.OK

    @property
    def needs_dialog(self) -> bool:
        """True when the operator must be told something went wrong.

        CANCELLED is excluded: the operator just answered No to a guard dialog,
        so a second popup telling them so would be noise.
        """
        return self.status in (PrintStatus.UNAVAILABLE, PrintStatus.ERROR)


@dataclass(frozen=True)
class LabelPrintRequest:
    """Everything a backend needs to print one label.

    Carries no human-readable text on purpose: the 20 mm label is QR-only by
    manufacturing spec, and handing every backend author an ``info_text`` would
    invite rendering it onto a label with no room, eating the quiet zone.
    """

    image: "QImage"
    ui: GuardUi
    # Parent for any dialog the backend raises. An unparented QMessageBox is
    # non-modal and can end up behind the main window, which on a production
    # line looks like a hang.
    parent: "QWidget | None" = None

    def __post_init__(self) -> None:
        # A null QImage draws as a no-op and would print a blank label; a raster
        # backend would divide by its zero width. Fail loudly at the boundary.
        if self.image is None or self.image.isNull():
            raise ValueError("LabelPrintRequest.image is null — nothing to print")


@runtime_checkable
class LabelPrinterBackend(Protocol):
    """The contract every label printer implements.

    Error policy: no method here may raise. Every entry point is reached from a
    Qt slot, and an exception escaping a slot aborts the interpreter rather than
    unwinding — in a ``--windowed`` build the operator's tool simply vanishes
    mid-job. Backends return :class:`PrintResult` / :class:`Availability` values
    instead, and :class:`~.selection.PrinterSelection` wraps every call as a
    backstop.

    Lifetime policy: nothing under ``app/services/printing`` may construct a Qt
    object at import time. Constructing a ``QPrinter`` before the
    ``QApplication`` exists is a hard fast-fail, and ``main.py`` imports the
    whole UI tree before it creates the application. The registry therefore
    stores classes and reads ``display_name`` off the ClassVar.
    """

    # Persisted into the operator's settings — a stable compatibility surface.
    # Renaming one is a breaking change; see docs/PRINTER_BACKENDS.md.
    id: ClassVar[str]
    display_name: ClassVar[str]
    capabilities: ClassVar[BackendCapabilities]
    # Dropdown position. Declared rather than inherited from import order, so
    # pasting a new import line can't reshuffle the operator's list.
    sort_order: ClassVar[int]

    def __init__(self, options: Mapping[str, Any]) -> None: ...

    def availability(self) -> Availability:
        """Cached, instant, no I/O. Safe to call while painting the UI."""
        ...

    def refresh_availability(self) -> Availability:
        """The only method allowed to block. Re-probes and updates the cache."""
        ...

    def configure(self, parent: "QWidget | None") -> None:
        """Show this backend's own setup UI and persist whatever it changes."""
        ...

    def print_label(self, request: LabelPrintRequest) -> PrintResult:
        """Print one 20 mm label. Must check availability before printing."""
        ...

    def options(self) -> Mapping[str, Any]:
        """Current settings as a JSON-serialisable mapping. Opaque to the UI."""
        ...

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Adopt persisted settings in place.

        Backends are created once per process and never re-instantiated (the
        system backend's QPrinter holds the operator's session page setup), so
        option changes are pushed in rather than triggering a rebuild.
        """
        ...

    def actions(self) -> Sequence[BackendAction]:
        """Extra operations, rendered generically. Default: none."""
        ...


@dataclass
class _NullUi:
    """A GuardUi that declines everything — used when no UI is available."""

    warnings: list[tuple[str, str]] = field(default_factory=list)

    def confirm(self, title: str, message: str) -> bool:
        self.warnings.append((title, message))
        return False

    def warn(self, title: str, message: str) -> None:
        self.warnings.append((title, message))
