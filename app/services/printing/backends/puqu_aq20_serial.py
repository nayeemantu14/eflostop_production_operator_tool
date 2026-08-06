"""PuQu AQ20 over a USB Virtual COM Port, speaking raw TSPL.

A second way to drive the same printer as ``puqu_aq20``. That backend goes
through PUQU's Windows driver; this one talks to the printer directly over the
serial port it enumerates as, which needs no driver installed and also works
over Bluetooth (see below).

**Where the protocol knowledge comes from.** The TSPL command semantics below
are from TSC's TSPL/TSPL2 Programming Manual (2014), which is public and
citable. That the *AQ20* accepts TSPL over its virtual COM port is **not**
published by PUQU anywhere I could find — it comes from hands-on testing by the
project owner. Treat the command set as documented and the fact that this
printer speaks it as verified on the bench, not on paper.

**Bluetooth.** A paired AQ20 exposes an outgoing COM port on Windows, so this
backend drives it over Bluetooth with no extra code — the operator just picks
that port. It is also the reason the write runs on a bounded worker thread:
opening a Bluetooth COM port can block for seconds while Windows brings the link
up, and no pyserial timeout covers ``open()``.

NEEDS BENCH VERIFICATION: the bitmap bit polarity (see :func:`pack_tspl_bitmap`),
that 20 x 20 mm gap stock feeds and calibrates, and a scan test of the result.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, ClassVar

import serial
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from pydantic import BaseModel, field_validator

from ....services.port_detector import find_all_serial_ports
from .. import qt_geometry
from ..base import (
    Availability,
    BackendAction,
    BackendCapabilities,
    LabelPrintRequest,
    PrintResult,
    PrintStatus,
)
from ..geometry import (
    QR_LABEL_SIZE_MM,
    GuardOutcome,
    Margins,
    PrinterMetrics,
    mm_to_px,
    plan_label,
    run_guards,
)
from ..registry import register_backend

log = logging.getLogger(__name__)

# TSPL is ASCII commands, one per line, CRLF-terminated.
EOL = b"\r\n"

# Description substrings that hint a COM port is a label printer rather than a
# debug probe. Only used to sort likely candidates to the top of the picker —
# never to filter, because the AQ20 may enumerate under a generic name.
PORT_NAME_HINTS = ("PUQU", "AQ20", "AQ00", "PQ00", "LABEL", "PRINTER", "BLUETOOTH")


class TsplSerialOptions(BaseModel):
    """Per-machine settings for the serial AQ20. Opaque to the UI."""

    port: str = ""
    # A USB CDC virtual COM port ignores the line rate, but a Bluetooth SPP
    # bridge may not, and pyserial requires some value.
    baudrate: int = 115200
    label_width_mm: float = float(QR_LABEL_SIZE_MM)
    label_height_mm: float = float(QR_LABEL_SIZE_MM)
    # Vertical gap between die-cut labels, for the printer's gap sensor.
    gap_mm: float = 2.0
    dpi: int = 203
    density: int = 8  # TSPL DENSITY, 0-15, manual default 8
    speed: int = 3  # TSPL SPEED, inches/sec
    timeout_seconds: float = 3.0
    # Escape hatch for the one thing that cannot be confirmed without hardware.
    # See pack_tspl_bitmap(). If the first label prints as a photographic
    # negative, flip this instead of editing code.
    invert: bool = False

    @field_validator("baudrate")
    @classmethod
    def _valid_baud(cls, value: int) -> int:
        if not 1200 <= value <= 1000000:
            raise ValueError("baudrate must be between 1200 and 1000000")
        return value

    @field_validator("dpi")
    @classmethod
    def _valid_dpi(cls, value: int) -> int:
        if not 72 <= value <= 2400:
            raise ValueError("dpi must be between 72 and 2400")
        return value

    @field_validator("density")
    @classmethod
    def _valid_density(cls, value: int) -> int:
        # TSPL manual: 0 is lightest, 15 darkest.
        if not 0 <= value <= 15:
            raise ValueError("density must be between 0 and 15")
        return value

    @field_validator("speed")
    @classmethod
    def _valid_speed(cls, value: int) -> int:
        if not 1 <= value <= 20:
            raise ValueError("speed must be between 1 and 20 inches/sec")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _valid_timeout(cls, value: float) -> float:
        # Bounded because a print blocks the operator; long enough for a
        # Bluetooth link to come up.
        if not 0.1 <= value <= 30.0:
            raise ValueError("timeout_seconds must be between 0.1 and 30")
        return value

    @field_validator("label_width_mm", "label_height_mm")
    @classmethod
    def _valid_label_size(cls, value: float) -> float:
        if not 5.0 <= value <= 200.0:
            raise ValueError("label dimensions must be between 5 and 200 mm")
        return value

    @field_validator("gap_mm")
    @classmethod
    def _valid_gap(cls, value: float) -> float:
        # TSPL GAP accepts 0-25.4 mm; 0 means continuous stock.
        if not 0.0 <= value <= 25.4:
            raise ValueError("gap_mm must be between 0 and 25.4")
        return value


def pack_tspl_bitmap(image: QImage, invert: bool = False) -> tuple[bytes, int, int]:
    """Pack a monochrome QImage into TSPL ``BITMAP`` data.

    Returns (data, width_bytes, height_dots) — TSPL's BITMAP takes its width in
    **bytes** and its height in **dots**.

    Polarity is the trap here: in TSPL a **0 bit prints a dot** and a 1 bit
    leaves the paper blank, which is the exact inverse of ZPL's ``^GFA``. Get it
    backwards and the label comes out as a photographic negative — solid black
    with a white QR, which no scanner will read. ``invert`` flips it without a
    code change if a given firmware disagrees.

    Rows are byte-aligned, so the stride rounds up. At 20 mm and 203 dpi that is
    160 dots = exactly 20 bytes, but rounding up is what stops a future
    non-multiple-of-8 label from shearing diagonally.
    """
    width = image.width()
    height = image.height()
    width_bytes = -(-width // 8)  # ceiling division
    out = bytearray()

    for y in range(height):
        # Start with every bit set: 1 = leave blank, so padding bits past the
        # right-hand edge of the image stay unprinted.
        row = bytearray(b"\xff" * width_bytes)
        for x in range(width):
            dark = image.pixelColor(x, y).value() < 128
            if dark != invert:  # dark, unless the operator inverted the output
                row[x >> 3] &= ~(0x80 >> (x & 7)) & 0xFF  # clear bit -> burn dot
        out += row

    return bytes(out), width_bytes, height


@register_backend
class PuquAq20SerialBackend:
    """Sends a rasterised 20 mm QR label to the AQ20 as TSPL over a COM port."""

    id: ClassVar[str] = "puqu_aq20_serial"
    display_name: ClassVar[str] = "PuQu AQ20 (USB Serial)"
    capabilities: ClassVar[BackendCapabilities] = BackendCapabilities(configurable=True)
    sort_order: ClassVar[int] = 15  # directly under the driver-based AQ20 entry

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        self._opts = TsplSerialOptions()
        self._availability = Availability(False, "no COM port chosen")
        # One worker, so two prints can never interleave on the same port.
        self._io = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tspl")
        self.apply_options(options or {})

    # --- options ------------------------------------------------------------

    def apply_options(self, options: Mapping[str, Any]) -> None:
        try:
            self._opts = TsplSerialOptions.model_validate(dict(options or {}))
        except Exception:
            # Bad stored settings must never stop the tool starting; the backend
            # reports itself unconfigured and the operator fixes it in Setup.
            self._opts = TsplSerialOptions()

    def options(self) -> Mapping[str, Any]:
        return self._opts.model_dump()

    # --- availability -------------------------------------------------------

    def availability(self) -> Availability:
        return self._availability

    def refresh_availability(self) -> Availability:
        """Enumeration only — deliberately opens nothing.

        This runs while the printer dropdown is painted. Opening a serial port
        here would put the open cost (and, for Bluetooth, the link-establishment
        delay) on the UI thread every time the list is drawn.
        """
        if not self._opts.port:
            self._availability = Availability(False, "no COM port chosen")
            return self._availability
        present = any(p.port == self._opts.port for p in find_all_serial_ports())
        if not present:
            self._availability = Availability(
                False, f"{self._opts.port} not connected"
            )
        else:
            self._availability = Availability(True, self._opts.port)
        return self._availability

    # --- TSPL ---------------------------------------------------------------

    def _metrics(self) -> PrinterMetrics:
        """Metrics from configuration, tagged as such.

        There is no driver to ask how big the loaded stock is, so these are the
        operator's declared values. ``provenance="declared"`` is what makes
        run_guards use wording that blames the configuration rather than
        pretending a printer reported a hardware margin.
        """
        dpi = self._opts.dpi
        return PrinterMetrics(
            # mm_to_px, not a raw float division: the shared geometry rounds the
            # same way, and a page that disagrees with it by a fraction of a dot
            # makes `side` 159.84 where the spec says 160.
            page_w_px=mm_to_px(self._opts.label_width_mm, dpi),
            page_h_px=mm_to_px(self._opts.label_height_mm, dpi),
            media_w_mm=self._opts.label_width_mm,
            media_h_mm=self._opts.label_height_mm,
            margins_mm=Margins(),  # a direct raster has no driver margin
            dpi=dpi,
            provenance="declared",
        )

    def build_tspl(self, image: QImage, plan) -> bytes:
        """Build the complete TSPL job for one label.

        Every state-bearing command is sent per job rather than relied upon:
        DIRECTION in particular carries a mirror flag that a printer remembers
        across power cycles, and a mirrored QR is unscannable with nothing in
        the tool able to detect it.
        """
        o = self._opts
        side = max(1, int(round(plan.side)))
        mono = qt_geometry.rasterize(image, side)
        data, width_bytes, height_dots = pack_tspl_bitmap(mono, invert=o.invert)

        x, y, _, _ = plan.qr_rect
        # BITMAP's X is in dots but addresses a byte-aligned column, so snap the
        # offset to a byte boundary rather than letting the printer round it.
        x_dots = max(0, round(x) // 8 * 8)
        y_dots = max(0, round(y))

        header = EOL.join([
            # "20 mm" — the space before the unit is required by TSPL.
            f"SIZE {o.label_width_mm:g} mm,{o.label_height_mm:g} mm".encode("ascii"),
            f"GAP {o.gap_mm:g} mm,0 mm".encode("ascii"),
            b"DIRECTION 0,0",  # normal feed, mirror OFF
            b"REFERENCE 0,0",
            f"DENSITY {o.density}".encode("ascii"),
            f"SPEED {o.speed}".encode("ascii"),
            b"CLS",  # must come after SIZE
            b"",
        ])
        bitmap_cmd = (
            f"BITMAP {x_dots},{y_dots},{width_bytes},{height_dots},0,".encode("ascii")
        )
        return header + bitmap_cmd + data + EOL + b"PRINT 1,1" + EOL

    # --- printing -----------------------------------------------------------

    def _write(self, payload: bytes) -> None:
        """Open the port, write the job, close. Runs on the worker thread."""
        o = self._opts
        with serial.Serial(
            port=o.port,
            baudrate=o.baudrate,
            timeout=o.timeout_seconds,
            write_timeout=o.timeout_seconds,
        ) as port:
            port.write(payload)
            port.flush()

    def print_label(self, request: LabelPrintRequest) -> PrintResult:
        self.refresh_availability()
        if not self._availability:
            return PrintResult(
                PrintStatus.UNAVAILABLE,
                "PuQu AQ20 unavailable",
                f"{self._availability.detail}. Open Printer Setup and choose the "
                f"COM port the printer is connected on.",
            )

        plan = plan_label(self._metrics())
        if run_guards(plan, request.ui) is GuardOutcome.ABORTED:
            return PrintResult(PrintStatus.CANCELLED)

        payload = self.build_tspl(request.image, plan)

        # Run the serial I/O off the GUI thread with a hard deadline. pyserial's
        # timeouts cover read and write but NOT open(), and opening a Bluetooth
        # COM port can block for seconds while Windows brings the link up. This
        # is what keeps a dead or wrong port to a bounded pause instead of a
        # frozen tool. A worker stuck in open() is abandoned rather than waited
        # on — the executor is single-threaded, so the next attempt queues
        # behind it and fails the same bounded way.
        budget = self._opts.timeout_seconds * 2 + 1.0
        try:
            self._io.submit(self._write, payload).result(timeout=budget)
        except FutureTimeout:
            return PrintResult(
                PrintStatus.ERROR,
                "Print Error",
                f"The printer on {self._opts.port} did not respond within "
                f"{budget:g} s. Check it is powered on and that the correct COM "
                f"port is selected in Printer Setup.",
            )
        except serial.SerialException as exc:
            return PrintResult(
                PrintStatus.ERROR,
                "Print Error",
                f"Could not print to {self._opts.port} — {exc}. Check the "
                f"printer is connected and the port is not in use by another "
                f"program.",
            )
        except Exception as exc:  # noqa: BLE001 - a slot must never see this
            log.exception("unexpected failure printing to %s", self._opts.port)
            return PrintResult(
                PrintStatus.ERROR,
                "Print Error",
                f"Could not print to {self._opts.port} — {exc}.",
            )

        return PrintResult(PrintStatus.OK)

    # --- setup UI -----------------------------------------------------------

    def configure(self, parent: QWidget | None) -> None:
        dialog = _TsplSerialSetupDialog(self._opts, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self._opts = TsplSerialOptions.model_validate(dialog.values())
            except Exception:
                log.exception("rejected invalid AQ20 serial settings")
            self.refresh_availability()

    def actions(self) -> Sequence[BackendAction]:
        return (
            BackendAction(
                label="Test connection",
                callback=self._test_connection,
                enabled=bool(self._opts.port),
                tooltip="Open the COM port briefly to check the printer answers",
            ),
        )

    def _test_connection(self, parent: QWidget | None) -> None:
        from PyQt6.QtWidgets import QMessageBox

        budget = self._opts.timeout_seconds * 2 + 1.0
        try:
            # An empty write: proves the port opens and accepts data without
            # feeding a label or changing any printer setting.
            self._io.submit(self._write, b"").result(timeout=budget)
        except FutureTimeout:
            QMessageBox.warning(
                parent, "PuQu AQ20",
                f"{self._opts.port} did not respond within {budget:g} s.",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                parent, "PuQu AQ20", f"Could not open {self._opts.port} — {exc}."
            )
        else:
            QMessageBox.information(
                parent, "PuQu AQ20",
                f"{self._opts.port} opened successfully.\n\nThis confirms the port "
                f"is there and free. It cannot confirm the printer understands "
                f"TSPL — print one label and check it.",
            )


class _TsplSerialSetupDialog(QDialog):
    """COM port picker plus the label and print settings."""

    def __init__(self, opts: TsplSerialOptions, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PuQu AQ20 (USB Serial) — setup")
        self._opts = opts

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Port row, matching the main window's Serial Port row.
        port_row = QHBoxLayout()
        self._port = QComboBox()
        self._port.setMinimumWidth(240)
        port_row.addWidget(self._port, stretch=1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._reload_ports)
        port_row.addWidget(self._refresh_btn)
        form.addRow("COM Port:", port_row)

        self._baud = QSpinBox()
        self._baud.setRange(1200, 1000000)
        self._baud.setValue(opts.baudrate)
        form.addRow("Baud rate:", self._baud)

        self._width = QDoubleSpinBox()
        self._width.setRange(5.0, 200.0)
        self._width.setSuffix(" mm")
        self._width.setValue(opts.label_width_mm)
        form.addRow("Label width:", self._width)

        self._height = QDoubleSpinBox()
        self._height.setRange(5.0, 200.0)
        self._height.setSuffix(" mm")
        self._height.setValue(opts.label_height_mm)
        form.addRow("Label height:", self._height)

        self._gap = QDoubleSpinBox()
        self._gap.setRange(0.0, 25.4)
        self._gap.setSuffix(" mm")
        self._gap.setValue(opts.gap_mm)
        form.addRow("Gap between labels:", self._gap)

        self._density = QSpinBox()
        self._density.setRange(0, 15)
        self._density.setValue(opts.density)
        self._density.setToolTip("TSPL print darkness: 0 lightest, 15 darkest")
        form.addRow("Density:", self._density)

        self._speed = QSpinBox()
        self._speed.setRange(1, 20)
        self._speed.setValue(opts.speed)
        self._speed.setSuffix(" ips")
        form.addRow("Speed:", self._speed)

        self._invert = QCheckBox("Invert bitmap (use if the label prints as a negative)")
        self._invert.setChecked(opts.invert)
        form.addRow("", self._invert)

        layout.addLayout(form)

        note = QLabel(
            "The label size describes the stock you loaded — the tool cannot read "
            "it from the printer. A printer paired over Bluetooth also appears "
            "here as a COM port."
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

        self._reload_ports()

    def _reload_ports(self) -> None:
        """Repopulate the port list, keeping the current selection if present."""
        current = self.selected_port() or self._opts.port
        ports = find_all_serial_ports()

        def likely(p) -> bool:
            haystack = f"{p.port} {p.description}".upper()
            return any(h in haystack for h in PORT_NAME_HINTS)

        # Sorted, never filtered — the AQ20 may enumerate under a generic name,
        # and hiding it would leave the operator no way to select it.
        ports.sort(key=lambda p: (not likely(p), p.port))

        blocked = self._port.blockSignals(True)
        try:
            self._port.clear()
            for p in ports:
                label = f"{p.port} — {p.description}" if p.description else p.port
                self._port.addItem(label, p.port)
            if not ports:
                self._port.addItem("No serial ports found", "")
            if current:
                index = self._port.findData(current)
                if index >= 0:
                    self._port.setCurrentIndex(index)
                else:
                    # Keep a configured-but-absent port visible so pressing OK
                    # cannot silently re-point the printer at a different device.
                    self._port.insertItem(0, f"{current} — not connected", current)
                    self._port.setCurrentIndex(0)
        finally:
            self._port.blockSignals(blocked)

    def selected_port(self) -> str:
        data = self._port.currentData()
        return data if isinstance(data, str) else ""

    def values(self) -> dict[str, Any]:
        return {
            **self._opts.model_dump(),
            "port": self.selected_port(),
            "baudrate": self._baud.value(),
            "label_width_mm": self._width.value(),
            "label_height_mm": self._height.value(),
            "gap_mm": self._gap.value(),
            "density": self._density.value(),
            "speed": self._speed.value(),
            "invert": self._invert.isChecked(),
        }
