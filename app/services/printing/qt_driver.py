"""Reusable base for printers driven through a Windows/Qt print driver.

Both shipped driver backends — the generic system printer and the pinned PUQU —
are this class with different printer-selection policies, and a future
Brother/Zebra with a Windows driver is a ~40-line subclass. Everything fiddly
lives here once: the QPrinter lifetime, the silent-``setPrinterName`` trap, the
shared 20 mm geometry, and the guard sequence.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo
from PyQt6.QtWidgets import QWidget

from . import qt_geometry
from .base import (
    Availability,
    BackendAction,
    BackendCapabilities,
    LabelPrintRequest,
    PrintResult,
    PrintStatus,
)
from .geometry import GuardOutcome, plan_label, run_guards

log = logging.getLogger(__name__)


def available_printer_names() -> list[str]:
    """Installed print queues, newest snapshot.

    ``availablePrinterNames()`` rather than ``availablePrinters()`` — the latter
    builds a full QPrinterInfo per queue and Qt's own docs discourage it.
    """
    return list(QPrinterInfo.availablePrinterNames())


def printer_exists(name: str) -> bool:
    """Whether a queue with this exact name is installed.

    The only reliable check. ``QPrinter.setPrinterName()`` with an unknown name
    is silently ignored — Qt early-returns, leaving the QPrinter pointed at
    whatever it had before (a fresh one points at the system default). So a
    renamed or removed label queue would quietly send the job to the office MFP,
    and ``QPrinter.isValid()`` still returns True throughout.
    """
    return bool(name) and not QPrinterInfo.printerInfo(name).isNull()


class QtDriverBackend:
    """A label printer reached through an installed Windows print driver.

    Subclasses set the ClassVars and override :meth:`target_printer_name` (and
    usually :meth:`configure`). The QPrinter is created lazily on first use and
    then lives for the process: it carries the operator's page setup, which the
    operator manual promises is "remembered for the rest of the session".
    """

    id: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    # Defaults to NOT configurable so a subclass that forgets to override
    # configure() gets a greyed-out Setup button rather than an error dialog.
    # Subclasses that implement configure() set configurable=True.
    capabilities: ClassVar[BackendCapabilities] = BackendCapabilities(configurable=False)
    sort_order: ClassVar[int] = 100

    # Set by subclasses that pin a specific queue. When None the backend uses
    # whatever the QPrinter already points at (the system-printer behaviour).
    pins_printer: ClassVar[bool] = False

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        self._printer: QPrinter | None = None
        self._availability = Availability(True)
        self.apply_options(options or {})

    # --- QPrinter lifetime --------------------------------------------------

    def _get_printer(self) -> QPrinter:
        """The backend's own QPrinter, created on first use.

        Never at construction time: backends are built while the registry is
        being consulted, and a QPrinter constructed before the QApplication
        exists fast-fails the process rather than raising.

        One printer per backend instance, never shared between backends —
        switching a shared QPrinter's name resets its resolution and rewrites
        its page size, and those changes persist after switching back.
        """
        if self._printer is None:
            self._printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        return self._printer

    def target_printer_name(self) -> str:
        """The queue this backend wants. Empty means "whatever is selected"."""
        return ""

    def _bind_printer(self) -> tuple[QPrinter | None, str]:
        """Return the QPrinter to print with, or (None, reason) if we can't.

        Refuses rather than falling back, because Qt's fallback is to keep the
        previous printer — which for a stale pinned name means the system
        default. If that default happens to be Microsoft Print to PDF (0 mm
        margins, accepts a 20 mm page) neither guard fires and the label
        silently disappears into a save dialog.
        """
        printer = self._get_printer()
        wanted = self.target_printer_name()
        if not wanted:
            return printer, ""
        if not printer_exists(wanted):
            return None, (
                f"The print queue {wanted!r} is not installed on this PC. "
                f"Open Printer Setup and choose the label printer again."
            )
        printer.setPrinterName(wanted)
        if printer.printerName() != wanted:
            # Belt and braces: setPrinterName is silent on failure.
            return None, (
                f"Windows would not select the print queue {wanted!r}. "
                f"Open Printer Setup and choose the label printer again."
            )
        self._after_bind(printer)
        return printer, ""

    def _after_bind(self, printer: QPrinter) -> None:
        """Hook for subclasses to pin resolution etc.

        Called after ``setPrinterName``, which is the only correct order:
        selecting a printer re-creates the print engine and resets the
        resolution to the driver default, discarding anything set before it.
        """

    # --- Backend protocol ---------------------------------------------------

    def availability(self) -> Availability:
        return self._availability

    def refresh_availability(self) -> Availability:
        wanted = self.target_printer_name()
        if self.pins_printer and not wanted:
            self._availability = Availability(
                False, "no printer chosen — open Printer Setup"
            )
        elif wanted and not printer_exists(wanted):
            self._availability = Availability(False, f"{wanted} not found")
        else:
            self._availability = Availability(True, wanted or "")
        return self._availability

    def configure(self, parent: QWidget | None) -> None:  # pragma: no cover - UI
        raise NotImplementedError(
            f"{type(self).__name__} declares capabilities.configurable=True but "
            f"does not implement configure()"
        )

    def options(self) -> Mapping[str, Any]:
        return {}

    def apply_options(self, options: Mapping[str, Any]) -> None:
        pass

    def actions(self) -> Sequence[BackendAction]:
        return ()

    def print_label(self, request: LabelPrintRequest) -> PrintResult:
        """Print one 20 mm label through the driver."""
        self.refresh_availability()
        if not self._availability:
            return PrintResult(
                PrintStatus.UNAVAILABLE,
                f"{self.display_name} unavailable",
                self._availability.detail
                or f"{self.display_name} is not ready to print.",
            )

        printer, problem = self._bind_printer()
        if printer is None:
            return PrintResult(
                PrintStatus.UNAVAILABLE, f"{self.display_name} unavailable", problem
            )

        metrics = qt_geometry.prepare(printer)
        plan = plan_label(metrics)
        if run_guards(plan, request.ui) is GuardOutcome.ABORTED:
            return PrintResult(PrintStatus.CANCELLED)

        return qt_geometry.draw(printer, request.image, plan)
