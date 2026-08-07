"""PuQu AQ20 driven directly over its port, speaking raw TSPL.

A second way to drive the same printer as ``puqu_aq20``. That backend goes
through PUQU's Windows driver; this one writes to the printer's port directly,
which needs no driver installed.

**Which port.** Windows does not present this printer the same way on every
machine, so both kinds are offered and the operator picks:

* a **virtual COM port** (USB CDC, or an outgoing Bluetooth SPP port), driven
  through pyserial; or
* an **LPT port** — observed on a real production PC, where Windows bound the
  AQ20 to LPT1. pyserial cannot open one at all (it filters LPT out of its own
  enumeration), so those bytes go to the DOS device as a raw byte pipe. No baud
  rate, no flow control; TSPL needs neither.

**Where the protocol knowledge comes from.** The TSPL command semantics below
are from TSC's TSPL/TSPL2 Programming Manual (2014), which is public and
citable. That the *AQ20* accepts TSPL at all is **not** published by PUQU
anywhere I could find — it comes from hands-on testing by the project owner.
Treat the command set as documented and the fact that this printer speaks it as
verified on the bench, not on paper.

**Why the write runs on a bounded worker thread.** Neither open path has a
timeout of its own: pyserial's timeouts do not cover ``open()``, and opening an
LPT device or a Bluetooth COM port can block for seconds while Windows brings
the link up. The deadline in :meth:`_run_bounded` is the only thing that keeps a
wedged printer port from freezing the tool.

NEEDS BENCH VERIFICATION: the bitmap bit polarity (see :func:`pack_tspl_bitmap`),
that 20 x 20 mm gap stock feeds and calibrates, and a scan test of the result.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping, Sequence
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

from ....services.port_detector import find_all_serial_ports, find_parallel_ports
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


def is_parallel_port(name: str) -> bool:
    """True for an LPT-style port, which is a raw byte pipe, not a serial port."""
    return name.upper().startswith("LPT")


def open_raw_port(name: str):
    """Open an LPT port as a raw byte stream.

    Its own function so the write path has a seam a test can replace — opening a
    real printer port is not something a test suite can do.
    """
    return open(rf"\\.\{name}", "wb", buffering=0)


def available_ports() -> list:
    """Every port the printer could be on: COM (USB or Bluetooth) plus LPT.

    Both are offered because the AQ20 has been seen presenting as each: a
    virtual COM port over USB or Bluetooth on some machines, and LPT1 on others
    depending on which driver Windows binds.
    """
    return find_all_serial_ports() + find_parallel_ports()


class TsplSerialOptions(BaseModel):
    """Per-machine settings for the serial AQ20. Opaque to the UI."""

    port: str = ""
    # A USB CDC virtual COM port ignores the line rate, but a Bluetooth SPP
    # bridge may not, and pyserial requires some value. Unused entirely on an
    # LPT port, which has no line rate.
    baudrate: int = 115200
    label_width_mm: float = float(QR_LABEL_SIZE_MM)
    label_height_mm: float = float(QR_LABEL_SIZE_MM)
    # Vertical gap between die-cut labels, for the printer's gap sensor.
    gap_mm: float = 2.0
    density: int = 8  # TSPL DENSITY, 0-15, manual default 8
    speed: int = 3  # TSPL SPEED, inches/sec
    # Default kept under the ~5 s at which Windows paints a window "Not
    # Responding": the print waits up to 2x this plus a second. A Bluetooth link
    # that needs longer to come up can raise it in config, at the cost of a
    # longer pause when the printer is absent.
    timeout_seconds: float = 1.5
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
    # The bit value that means "leave the paper blank" — normally 1, but 0 when
    # the operator has inverted the output. Seeding each row with it is what
    # keeps the stride padding past the right-hand edge unprinted. Hardcoding
    # 0xFF here burned a black stripe down the edge of every inverted label,
    # straight through the QR's quiet zone.
    blank = 0x00 if invert else 0xFF
    out = bytearray()

    for y in range(height):
        row = bytearray([blank]) * width_bytes
        for x in range(width):
            if image.pixelColor(x, y).value() < 128:  # dark pixel -> burn a dot
                mask = 0x80 >> (x & 7)
                if invert:
                    row[x >> 3] |= mask
                else:
                    row[x >> 3] &= ~mask & 0xFF
        out += row

    return bytes(out), width_bytes, height


@register_backend
class PuquAq20SerialBackend:
    """Sends a rasterised 20 mm QR label to the AQ20 as TSPL over a COM port."""

    id: ClassVar[str] = "puqu_aq20_serial"
    display_name: ClassVar[str] = "PuQu AQ20 (USB Serial)"
    capabilities: ClassVar[BackendCapabilities] = BackendCapabilities(configurable=True)
    sort_order: ClassVar[int] = 15  # directly under the driver-based AQ20 entry

    # The print head's real resolution. Not an operator setting: TSPL SIZE is in
    # millimetres and the printer maps that to its own dots, so a configured DPI
    # that disagreed with the hardware would rasterise the wrong number of dots
    # with nothing able to detect it. A subclass for another TSPL printer
    # overrides this.
    dpi: ClassVar[int] = 203

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        self._opts = TsplSerialOptions()
        self._availability = Availability(False, "no printer port chosen")
        # In-flight bookkeeping. Serial writes run on a daemon thread so a wedged
        # port can never keep the process alive, and only one may be outstanding
        # at a time — see _run_bounded().
        self._lock = threading.Lock()
        self._busy_port: str | None = None
        self._generation = 0
        self._abandoned_through = 0
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
            self._availability = Availability(False, "no printer port chosen")
            return self._availability
        present = any(p.port == self._opts.port for p in available_ports())
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
        dpi = self.dpi
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

        # Both BITMAP coordinates are in dots. Only `width` is in bytes — an
        # earlier version snapped X down to a byte boundary, which shifted the
        # QR up to 7 dots (0.88 mm) off-centre on any label whose width is not a
        # multiple of 8 dots, and put this backend's output out of step with
        # the ZPL one for the same LabelPlan.
        x, y, _, _ = plan.qr_rect
        x_dots = max(0, round(x))
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

    def _write(self, generation: int, opts: TsplSerialOptions, payload: bytes) -> None:
        """Open the port, write the job, close. Runs on the worker thread.

        Takes its settings by value rather than reading ``self._opts``: the
        operator can change the port in Printer Setup while a slow open is still
        in progress, and a worker that re-read the current options would send a
        job built for one printer to a different one.

        The generation check between open and write is the important part. If
        the caller has already given up and told the operator the print failed,
        this job must NOT go on to print — otherwise a label bearing one device's
        serial falls out while the operator is holding the next device.
        """
        if is_parallel_port(opts.port):
            # Windows presents some USB label printers as LPT rather than as a
            # virtual COM port. pyserial cannot open one at all, so the bytes go
            # straight to the DOS device. There is no baud rate and no flow
            # control on this path — it is a raw byte pipe, which is all TSPL
            # needs. The bounded worker above is what stops a wedged printer
            # port hanging the tool, since this open() has no timeout either.
            with open_raw_port(opts.port) as port:
                if self._is_abandoned(generation):
                    log.warning(
                        "discarding label job for %s: the operator was already "
                        "told it failed", opts.port,
                    )
                    return
                port.write(payload)
            return

        with serial.Serial(
            port=opts.port,
            baudrate=opts.baudrate,
            timeout=opts.timeout_seconds,
            write_timeout=opts.timeout_seconds,
        ) as port:
            if self._is_abandoned(generation):
                log.warning(
                    "discarding label job for %s: the operator was already told "
                    "it failed", opts.port,
                )
                return
            port.write(payload)
            # No flush(): pyserial's Windows flush() is an unbounded
            # `while out_waiting: sleep(0.05)` with no timeout, and closing the
            # port drains it anyway.

    def _is_abandoned(self, generation: int) -> bool:
        with self._lock:
            return generation <= self._abandoned_through

    def _run_bounded(self, opts: TsplSerialOptions, payload: bytes) -> str:
        """Do the serial write off the GUI thread. Returns "" or an error.

        A daemon thread rather than a pooled worker: a wedged serial open must
        not keep the process alive. ``concurrent.futures`` workers are
        non-daemon and joined by an atexit hook, so a stuck open left the
        windowed .exe running with no window after the operator closed it.

        Only one job may be outstanding. A second print while one is stuck is
        refused immediately and names the port that is actually stuck, instead
        of queueing behind it and then blaming whichever port is configured by
        the time it times out.
        """
        with self._lock:
            if self._busy_port is not None:
                return (
                    f"A previous label is still being sent to {self._busy_port} "
                    f"and has not finished. Wait a moment, or restart the tool if "
                    f"the printer is not responding."
                )
            self._generation += 1
            generation = self._generation
            self._busy_port = opts.port

        done = threading.Event()
        failure: list[BaseException] = []

        def run() -> None:
            try:
                self._write(generation, opts, payload)
            except BaseException as exc:  # noqa: BLE001 - reported, never raised
                failure.append(exc)
            finally:
                with self._lock:
                    self._busy_port = None
                done.set()

        threading.Thread(target=run, name="tspl-print", daemon=True).start()

        # open() and write() each get their own pyserial timeout, so the worst
        # legitimate case is about twice the configured value.
        budget = opts.timeout_seconds * 2 + 1.0
        if not done.wait(budget):
            with self._lock:
                # Anything up to and including this job is now disowned: if the
                # worker ever gets its port open, it must throw the job away.
                self._abandoned_through = generation
            return (
                f"The printer on {opts.port} did not respond within {budget:g} s. "
                f"Check it is powered on and that the correct COM port is "
                f"selected in Printer Setup. The label was not printed."
            )

        if failure:
            exc = failure[0]
            if isinstance(exc, serial.SerialException):
                return (
                    f"Could not print to {opts.port} — {exc}. Check the printer "
                    f"is connected and the port is not in use by another program."
                )
            log.exception("unexpected failure printing to %s", opts.port, exc_info=exc)
            return f"Could not print to {opts.port} — {exc}."
        return ""

    def print_label(self, request: LabelPrintRequest) -> PrintResult:
        self.refresh_availability()
        if not self._availability:
            return PrintResult(
                PrintStatus.UNAVAILABLE,
                "PuQu AQ20 unavailable",
                f"{self._availability.detail}. Open Printer Setup and choose the "
                f"port the printer is connected on.",
            )

        plan = plan_label(self._metrics())
        if run_guards(plan, request.ui) is GuardOutcome.ABORTED:
            return PrintResult(PrintStatus.CANCELLED)

        payload = self.build_tspl(request.image, plan)

        # Snapshot the settings so a Printer Setup change mid-print cannot
        # redirect this job to a different port.
        problem = self._run_bounded(self._opts.model_copy(), payload)
        if problem:
            return PrintResult(PrintStatus.ERROR, "Print Error", problem)
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
                tooltip="Check the COM port can be opened and is not already in use",
            ),
        )

    def _test_connection(self, parent: QWidget | None) -> None:
        from PyQt6.QtWidgets import QMessageBox

        # Writes nothing: this checks only that the port opens and is free. The
        # printer is never asked to answer, so nothing is fed and no setting is
        # changed.
        problem = self._run_bounded(self._opts.model_copy(), b"")
        if problem:
            QMessageBox.warning(parent, "PuQu AQ20", problem)
        else:
            QMessageBox.information(
                parent, "PuQu AQ20",
                f"{self._opts.port} opened successfully.\n\nThat confirms the port "
                f"exists and nothing else is holding it. It does not confirm a "
                f"printer is attached or that it understands TSPL — print one "
                f"label and check it.",
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
        form.addRow("Printer Port:", port_row)

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
            "The port list shows COM ports (USB or Bluetooth) and LPT ports — "
            "Windows binds this printer to one or the other depending on the "
            "machine. Baud rate is ignored on an LPT port. The label size "
            "describes the stock you loaded; the tool cannot read it from the "
            "printer."
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

        self._port.currentIndexChanged.connect(self._sync_baud_enabled)
        self._reload_ports()

    def _sync_baud_enabled(self) -> None:
        """An LPT port is a raw byte pipe — it has no line rate to set."""
        serial_port = not is_parallel_port(self.selected_port())
        self._baud.setEnabled(serial_port)
        self._baud.setToolTip(
            "" if serial_port else "Not used on an LPT port"
        )

    def _reload_ports(self) -> None:
        """Repopulate the port list, keeping the current selection if present."""
        current = self.selected_port() or self._opts.port
        ports = available_ports()

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
        self._sync_baud_enabled()

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
