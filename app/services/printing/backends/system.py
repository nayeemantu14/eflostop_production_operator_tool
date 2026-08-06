"""System printer — the stock Windows print-dialog behaviour.

The default, and byte-for-byte what the tool did before printer backends
existed: one shared QPrinter for the session, the native print dialog for setup,
and the same 20 mm full-bleed geometry with the same guards. Nothing on the
production line changes until someone deliberately picks another backend.
"""

from __future__ import annotations

from typing import ClassVar

from PyQt6.QtPrintSupport import QPrintDialog
from PyQt6.QtWidgets import QWidget

from ..base import (
    Availability,
    BackendCapabilities,
    LabelPrintRequest,
    PrintResult,
    PrintStatus,
)
from ..qt_driver import QtDriverBackend
from ..registry import register_backend


@register_backend
class SystemPrinterBackend(QtDriverBackend):
    """Prints to whatever printer the operator picked in the Windows dialog."""

    id: ClassVar[str] = "system"
    display_name: ClassVar[str] = "System printer (any)"
    capabilities: ClassVar[BackendCapabilities] = BackendCapabilities(configurable=True)
    sort_order: ClassVar[int] = 0

    # Never pins a queue: the QPrinter carries whatever the print dialog set.
    pins_printer: ClassVar[bool] = False

    def refresh_availability(self) -> Availability:
        # Always usable — if no printer has been chosen yet, print_label opens
        # the selection dialog rather than refusing, which is what this backend
        # has always done.
        #
        # Deliberately does NOT call _get_printer(): this runs while the printer
        # dropdown is being populated, which happens during MainWindow
        # construction, and constructing a QPrinter costs ~1.5 s when the
        # default printer is a network queue. Forcing it here put that delay on
        # every application launch, before the window was even shown. The
        # QPrinter is built on first real use instead.
        name = self._printer.printerName() if self._printer is not None else ""
        self._availability = Availability(True, name)
        return self._availability

    def configure(self, parent: QWidget | None) -> None:
        """Open the native printer/page setup dialog."""
        dialog = QPrintDialog(self._get_printer(), parent)
        dialog.setWindowTitle("Printer Setup")
        dialog.exec()

    def print_label(self, request: LabelPrintRequest) -> PrintResult:
        printer = self._get_printer()
        # If no printer has been configured yet, open setup first.
        if not printer.printerName():
            dialog = QPrintDialog(printer, request.parent)
            dialog.setWindowTitle("Select Printer")
            if dialog.exec() != QPrintDialog.DialogCode.Accepted:
                return PrintResult(PrintStatus.CANCELLED)
        return super().print_label(request)
