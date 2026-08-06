"""PUQU AQ20 portable thermal label printer, via its Windows driver.

Verified from the vendor quick guide (QR printer/AQ20.pdf p4, and the same guide
at downloads.puqulabel.com/books/qug-aq.en/): 203 dpi, 48 mm print width,
25-56 mm/s, direct thermal, Bluetooth + USB, "Android & iOS & PC".

PUQU publishes a Windows driver bundle
(puqulabel.com/download/printer-driver/ -> appsres.puqulabel.com/softs/
pc_printing_drivers.zip, covering the "PQ/AQ/TQ/Q1" series), so this backend is
a profile over the same QPrinter machinery the system backend uses: pin the
queue, force 20 x 20 mm full-bleed, print with no dialog on the happy path.

Two things it deliberately does NOT do:

* It does not guess the queue name. PUQU's own PC manual states the driver
  installs a single queue named "PQ00" for the entire range rather than one per
  model, so matching on "AQ20" would find nothing. The operator picks the queue
  from the installed list; the name hints below only sort likely candidates to
  the top, and the exact chosen name is what gets persisted.
* It does not implement a raw Bluetooth/USB transport. PUQU publishes no
  protocol specification and no SDK; the OEM's LPAPI is a closed-source
  Android/JS drawing API that documents no bytes, and the only wire-level
  document in circulation (github.com/sb-child/dz-print) describes a Detonger
  DP27P, a different manufacturer's device. Inventing byte sequences for a
  printer that puts labels on shipped hardware is not a trade worth making, so
  the raw path is absent rather than speculative. See docs/PRINTER_BACKENDS.md
  for the questions outstanding with PUQU support.

NOT YET VERIFIED ON HARDWARE: whether the AQ20 accepts 20 x 20 mm die-cut stock
and whether it prints edge-to-edge at that size. PUQU documents neither a
minimum label height nor an unprintable margin. The shared guards are what
catches it: if the driver reports a hardware margin, the operator is told the
exact millimetre size the QR would print at before anything reaches the label.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from pydantic import BaseModel, Field, field_validator

from ..base import BackendAction, BackendCapabilities
from ..qt_driver import QtDriverBackend, available_printer_names, printer_exists
from ..registry import register_backend

# Substrings that suggest an installed queue belongs to a PUQU printer. Only a
# sorting hint for the setup dialog — never a filter that can hide the real
# queue, because the driver's actual name is not something we can rely on.
DEFAULT_NAME_HINTS = ("PUQU", "AQ20", "AQ00", "PQ00", "TQ", "Q1")


class PuquOptions(BaseModel):
    """Per-machine settings for the PUQU backend.

    Opaque to the UI: it round-trips this through the selection layer as JSON
    without knowing what any key means.
    """

    printer_name: str = ""
    # The AQ20's head is 203 dpi (8 dots/mm across a 48 mm width). Pinning it
    # makes one Qt device pixel one thermal dot. Physical size is computed in
    # millimetres either way, so this changes raster fidelity, not label size.
    resolution_dpi: int = 203
    name_hints: list[str] = Field(default_factory=lambda: list(DEFAULT_NAME_HINTS))

    @field_validator("resolution_dpi")
    @classmethod
    def _sane_dpi(cls, value: int) -> int:
        # A nonsense DPI would silently rescale every label, so reject rather
        # than quietly accept. Bounds are generous: real label printers run
        # 152-600 dpi.
        if not 72 <= value <= 2400:
            raise ValueError("resolution_dpi must be between 72 and 2400")
        return value


@register_backend
class PuquAq20Backend(QtDriverBackend):
    """PUQU AQ20 pinned to one Windows print queue."""

    id: ClassVar[str] = "puqu_aq20"
    display_name: ClassVar[str] = "PUQU AQ20"
    capabilities: ClassVar[BackendCapabilities] = BackendCapabilities(configurable=True)
    sort_order: ClassVar[int] = 10
    pins_printer: ClassVar[bool] = True

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        self._opts = PuquOptions()
        super().__init__(options)

    # --- options ------------------------------------------------------------

    def apply_options(self, options: Mapping[str, Any]) -> None:
        try:
            self._opts = PuquOptions.model_validate(dict(options or {}))
        except Exception:
            # Bad stored settings must not stop the tool from starting; the
            # backend simply reports itself unconfigured and the operator fixes
            # it in Printer Setup.
            self._opts = PuquOptions()

    def options(self) -> Mapping[str, Any]:
        return self._opts.model_dump()

    def target_printer_name(self) -> str:
        return self._opts.printer_name

    def _after_bind(self, printer: QPrinter) -> None:
        # Must come after setPrinterName: selecting a printer re-creates the
        # print engine and resets the resolution to the driver default, so
        # setting it earlier would be discarded.
        printer.setResolution(self._opts.resolution_dpi)

    # --- setup UI -----------------------------------------------------------

    def candidate_printers(self) -> list[str]:
        """Installed queues, likely-PUQU ones first.

        Sorted, not filtered — an operator whose driver installed under an
        unexpected name must still be able to find it.
        """
        hints = [h.upper() for h in self._opts.name_hints if h]
        names = available_printer_names()

        def likely(name: str) -> bool:
            upper = name.upper()
            return any(h in upper for h in hints)

        return sorted(names, key=lambda n: (not likely(n), n.lower()))

    def is_likely_puqu(self, name: str) -> bool:
        upper = name.upper()
        return any(h.upper() in upper for h in self._opts.name_hints if h)

    def configure(self, parent: QWidget | None) -> None:
        dialog = _PuquSetupDialog(self, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._opts = self._opts.model_copy(
                update={"printer_name": dialog.selected_printer()}
            )
            self.refresh_availability()

    def actions(self) -> Sequence[BackendAction]:
        return (
            BackendAction(
                label="Feed / calibrate",
                callback=self._show_calibration_help,
                tooltip="How to advance and align 20 mm label stock on the AQ20",
            ),
        )

    def _show_calibration_help(self, parent: QWidget | None) -> None:
        # Deliberately instructions rather than a command: PUQU documents no
        # calibration command, and the only positioning guidance in the vendor
        # guide is the front-panel button press reproduced here.
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.information(
            parent,
            "PUQU AQ20 — feed and calibrate",
            "PUQU publishes no calibration command, so this is done on the "
            "printer itself:\n\n"
            "1. Load the label roll with the print side up, pushed left against "
            "the baffle.\n"
            "2. Close the cover.\n"
            "3. Short-press the RIGHT button to feed one label and align the "
            "gap sensor.\n"
            "4. Check the LED is solid blue (ready). Solid red means out of "
            "paper or the cover is open.\n\n"
            "Paper gap, darkness and speed are set from the printer's own "
            "button menu (short-press LEFT to cycle items, RIGHT to change "
            "the value).",
        )


class _PuquSetupDialog(QDialog):
    """Pick the Windows print queue the AQ20 installed as."""

    def __init__(self, backend: PuquAq20Backend, parent: QWidget | None) -> None:
        super().__init__(parent)
        self._backend = backend
        self.setWindowTitle("PUQU AQ20 — printer setup")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._combo = QComboBox()
        self._combo.setMinimumWidth(280)
        form.addRow("Windows print queue:", self._combo)

        self._only_likely = QCheckBox("Show only likely PUQU queues")
        self._only_likely.setChecked(True)
        self._only_likely.toggled.connect(self._reload)
        form.addRow("", self._only_likely)

        form.addRow(
            "Label / resolution:",
            QLabel(f"20 x 20 mm at {backend.options()['resolution_dpi']} dpi"),
        )

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #666; font-size: 11px;")
        form.addRow("Status:", self._status)

        layout.addLayout(form)

        note = QLabel(
            "PUQU's driver may install under a generic name such as \"PQ00\" "
            "rather than \"AQ20\" — pick whichever queue is the label printer."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._combo.currentTextChanged.connect(lambda _: self._update_status())
        self._reload()

    def _reload(self) -> None:
        current = self._backend.target_printer_name()
        names = self._backend.candidate_printers()
        if self._only_likely.isChecked():
            likely = [n for n in names if self._backend.is_likely_puqu(n)]
            # Never present an empty list — an operator with an oddly-named
            # driver would have no way forward.
            names = likely or names
        self._combo.clear()
        self._combo.addItems(names)
        if current and current in names:
            self._combo.setCurrentText(current)
        self._update_status()

    def _update_status(self) -> None:
        name = self.selected_printer()
        if not name:
            self._status.setText("No printers installed on this PC.")
            return
        if not printer_exists(name):
            self._status.setText(f"{name} is not installed.")
            return
        # Report the margin the driver claims, so the operator learns before
        # printing whether this queue can actually reach the edge of a 20 mm
        # label — the property PUQU does not document for the AQ20.
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPrinterName(name)
        if printer.printerName() != name:
            self._status.setText(f"Windows would not select {name}.")
            return
        from .. import qt_geometry

        metrics = qt_geometry.prepare(printer)
        m = metrics.margins_mm
        worst = max(m.left, m.top, m.right, m.bottom)
        if worst <= 0.05:
            self._status.setText(
                f"Detected. Full-bleed (0.0 mm margin) at {metrics.dpi} dpi — "
                "the QR will print at the full 20 mm."
            )
        else:
            self._status.setText(
                f"Detected, but the driver reports a {worst:.1f} mm "
                f"non-printable border, which would shrink the QR. You will be "
                f"warned before each print."
            )

    def selected_printer(self) -> str:
        return self._combo.currentText().strip()
