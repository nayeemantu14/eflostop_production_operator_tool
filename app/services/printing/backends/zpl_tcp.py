"""ZPL label printer over a raw TCP socket (port 9100).

Replaces the tool's previously dead ZPL module. Unlike the driver backends there
is no Windows queue and no QPainter — the QR is rasterised to the same pixel
grid the shared geometry computes, packed into a ``^GFA`` bitmap, and sent to the
printer directly.

**Why this backend's warnings are worded differently.** A driver tells us the
media size and the hardware margin it actually has. A socket does not: every
number here comes from configuration, so running the driver-path guards on it
would compare config against itself and produce warnings that can never fire —
a guard that is structurally incapable of firing is worse than no guard, because
the operator has been told those warnings are their check. The metrics are
therefore tagged ``provenance="declared"``, which selects honest wording, and
this backend adds the check a socket *can* make: refusing to emit a raster wider
than the label it was told about.
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from pydantic import BaseModel, field_validator

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
    plan_label,
    run_guards,
)
from ..registry import register_backend

log = logging.getLogger(__name__)


class ZplOptions(BaseModel):
    """Per-machine settings for a ZPL-over-TCP printer."""

    host: str = ""
    port: int = 9100
    dpi: int = 203
    # Kept short and bounded: print_label runs on the GUI thread, and a
    # routable-but-dead host would otherwise block on the Windows SYN retry for
    # ~21 s with the tool frozen mid-test.
    timeout_seconds: float = 3.0
    # Physical stock loaded in the printer. Defaults to the manufacturing spec;
    # a mismatch is what the declared-media guard exists to warn about.
    label_width_mm: float = float(QR_LABEL_SIZE_MM)
    label_height_mm: float = float(QR_LABEL_SIZE_MM)
    margins_mm: float = 0.0

    @field_validator("port")
    @classmethod
    def _valid_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("port must be between 1 and 65535")
        return value

    @field_validator("dpi")
    @classmethod
    def _valid_dpi(cls, value: int) -> int:
        if not 72 <= value <= 2400:
            raise ValueError("dpi must be between 72 and 2400")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _valid_timeout(cls, value: float) -> float:
        if not 0.1 <= value <= 30.0:
            raise ValueError("timeout_seconds must be between 0.1 and 30")
        return value

    @field_validator("margins_mm")
    @classmethod
    def _valid_margin(cls, value: float) -> float:
        # A negative margin would enlarge the printable area past the label and
        # push the QR off it, with the undersize guard reporting a size larger
        # than the media. Non-negative and smaller than the label.
        if not 0.0 <= value < QR_LABEL_SIZE_MM / 2:
            raise ValueError("margins_mm must be >= 0 and less than half the label")
        return value

    @field_validator("label_width_mm", "label_height_mm")
    @classmethod
    def _valid_label_size(cls, value: float) -> float:
        if not 5.0 <= value <= 200.0:
            raise ValueError("label dimensions must be between 5 and 200 mm")
        return value


def pack_gfa(image: QImage) -> tuple[str, int, int, int]:
    """Pack a 1-bit QImage into ZPL ``^GFA`` hex data.

    Returns (hex_data, total_bytes, bytes_per_row, rows).

    ZPL rows are byte-aligned, so the row stride rounds *up* to whole bytes —
    using ``w // 8`` instead would be invisible at 160 dots (exactly 20 bytes)
    and shear the image at any width that is not a multiple of 8. A 1 bit means
    a burnt (black) dot.
    """
    width = image.width()
    height = image.height()
    bytes_per_row = -(-width // 8)  # ceiling division
    rows: list[str] = []

    for y in range(height):
        row = bytearray(bytes_per_row)
        for x in range(width):
            # qGray-free check: after convertToFormat(Format_Mono) the image is
            # a 2-colour palette, but pixelColor() is palette-independent and
            # cheap enough at 160x160.
            if image.pixelColor(x, y).value() < 128:  # dark pixel -> burn
                row[x >> 3] |= 0x80 >> (x & 7)
        rows.append(row.hex().upper())

    return "".join(rows), bytes_per_row * height, bytes_per_row, height


@register_backend
class ZplSocketBackend:
    """Sends a rasterised 20 mm QR label to a ZPL printer over TCP."""

    id: ClassVar[str] = "zpl_tcp"
    display_name: ClassVar[str] = "ZPL printer (network)"
    capabilities: ClassVar[BackendCapabilities] = BackendCapabilities(configurable=True)
    sort_order: ClassVar[int] = 20

    # Subclasses (e.g. a specific Zebra model) override this to add fields.
    options_model: ClassVar[type[ZplOptions]] = ZplOptions

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        self._opts = self.options_model()
        self._availability = Availability(False, "no host configured")
        self.apply_options(options or {})

    # --- options ------------------------------------------------------------

    def apply_options(self, options: Mapping[str, Any]) -> None:
        try:
            self._opts = self.options_model.model_validate(dict(options or {}))
        except Exception:
            self._opts = self.options_model()

    def options(self) -> Mapping[str, Any]:
        return self._opts.model_dump()

    # --- availability -------------------------------------------------------

    def availability(self) -> Availability:
        return self._availability

    def refresh_availability(self) -> Availability:
        """Config-only check — deliberately does no network I/O.

        Called while painting the dropdown, so it must return instantly.
        Reachability is proven by the explicit "Test connection" action and,
        failing that, by the print attempt itself.
        """
        if not self._opts.host:
            self._availability = Availability(False, "no host configured")
        else:
            self._availability = Availability(
                True, f"{self._opts.host}:{self._opts.port}"
            )
        return self._availability

    # --- setup UI -----------------------------------------------------------

    def configure(self, parent: QWidget | None) -> None:
        dialog = _ZplSetupDialog(self._opts, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self._opts = self.options_model.model_validate(dialog.values())
            except Exception:
                log.exception("rejected invalid ZPL printer settings")
            self.refresh_availability()

    def actions(self) -> Sequence[BackendAction]:
        return (
            BackendAction(
                label="Test connection",
                callback=self._test_connection,
                enabled=bool(self._opts.host),
            ),
        )

    def _test_connection(self, parent: QWidget | None) -> None:
        from PyQt6.QtWidgets import QMessageBox

        ok, detail = self._probe()
        if ok:
            QMessageBox.information(
                parent, "ZPL printer", f"Connected to {self._opts.host}:{self._opts.port}."
            )
        else:
            QMessageBox.warning(parent, "ZPL printer", detail)

    def _probe(self) -> tuple[bool, str]:
        if not self._opts.host:
            return False, "No printer host configured. Open Printer Setup."
        try:
            with self._connect():
                return True, ""
        except (OSError, UnicodeError) as exc:
            # UnicodeError, not OSError, is what the IDNA encoder raises for a
            # malformed hostname such as "192.168..50" — and it subclasses
            # ValueError, so an OSError-only handler lets it escape the backend.
            return False, (
                f"Could not reach {self._opts.host}:{self._opts.port} — {exc}. "
                f"Check the printer is powered on and on the network."
            )

    # --- printing -----------------------------------------------------------

    def _connect(self) -> socket.socket:
        """Open a socket to the printer within a single overall time budget.

        Not ``socket.create_connection``: that applies the timeout to EACH
        address ``getaddrinfo`` returns, so a dual-stack host name takes twice
        the configured timeout and three black-holed addresses take three times
        it. This runs on the GUI thread, so the budget has to be the total.

        Name resolution itself is still outside the budget — the OS resolver
        offers no timeout — so an unresolvable name can exceed it. Prefer an IP
        address for the printer host.
        """
        deadline = time.monotonic() + self._opts.timeout_seconds
        infos = socket.getaddrinfo(
            self._opts.host, self._opts.port, 0, socket.SOCK_STREAM
        )
        last: OSError = OSError("no address found for host")
        for family, socktype, proto, _canon, addr in infos:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"timed out after {self._opts.timeout_seconds:g}s"
                ) from last
            sock = socket.socket(family, socktype, proto)
            try:
                sock.settimeout(remaining)
                sock.connect(addr)
            except OSError as exc:
                sock.close()
                last = exc
                continue
            return sock
        raise last

    def _metrics(self) -> PrinterMetrics:
        """Build metrics from configuration, tagged as such.

        page_*_px is computed from the configured label size at the configured
        dpi because there is genuinely no driver to ask — which is precisely
        what ``provenance="declared"`` records, so run_guards words its warnings
        honestly instead of blaming a printer for a YAML value.
        """
        dpi = self._opts.dpi
        margin = self._opts.margins_mm
        return PrinterMetrics(
            page_w_px=self._opts.label_width_mm / 25.4 * dpi,
            page_h_px=self._opts.label_height_mm / 25.4 * dpi,
            media_w_mm=self._opts.label_width_mm,
            media_h_mm=self._opts.label_height_mm,
            margins_mm=Margins(margin, margin, margin, margin),
            dpi=dpi,
            provenance="declared",
        )

    def _preamble(self) -> str:
        """Explicit label state, so a printer's saved config can't rotate us.

        A ZPL printer remembers ``^POI`` (invert), ``^LRY`` (reverse) and
        ``^FWB`` (rotate) across power cycles, and any of them would silently
        mirror or rotate every label with no way for the guards to notice.
        Setting them per job costs nothing and removes the failure mode.
        """
        dpi = self._opts.dpi
        width_dots = round(self._opts.label_width_mm / 25.4 * dpi)
        height_dots = round(self._opts.label_height_mm / 25.4 * dpi)
        return (
            f"^XA^LH0,0^LRN^PON^FWN^CI28"
            f"^PW{width_dots}^LL{height_dots}"
        )

    def build_zpl(self, image: QImage, plan) -> str:
        """Full ZPL job for one label."""
        side = max(1, int(round(plan.side)))
        mono = qt_geometry.rasterize(image, side)
        data, total, per_row, rows = pack_gfa(mono)
        x, y, _, _ = plan.qr_rect
        return (
            f"{self._preamble()}"
            f"^FO{max(0, round(x))},{max(0, round(y))}"
            f"^GFA,{total},{total},{per_row},{data}^FS"
            f"^XZ"
        )

    def print_label(self, request: LabelPrintRequest) -> PrintResult:
        self.refresh_availability()
        if not self._availability:
            return PrintResult(
                PrintStatus.UNAVAILABLE,
                "ZPL printer unavailable",
                "No printer host configured. Open Printer Setup and enter the "
                "printer's IP address.",
            )

        plan = plan_label(self._metrics())
        if run_guards(plan, request.ui) is GuardOutcome.ABORTED:
            return PrintResult(PrintStatus.CANCELLED)

        zpl = self.build_zpl(request.image, plan)

        # Internal invariant, not an operator-facing guard: the raster must fit
        # the page the plan was built from. With the options validated this
        # cannot fire — width_dots and the plan's page width are the same
        # expression over the same two settings — but it is the last thing
        # between a future arithmetic slip and a clipped, unscannable label.
        width_dots = round(self._opts.label_width_mm / 25.4 * self._opts.dpi)
        side = max(1, int(round(plan.side)))
        if round(plan.qr_rect[0]) + side > width_dots:
            return PrintResult(
                PrintStatus.ERROR,
                "Label too small for the QR",
                f"The {side}-dot QR does not fit the configured "
                f"{self._opts.label_width_mm:.0f} mm label. Correct the label "
                f"size in Printer Setup.",
            )

        try:
            with self._connect() as sock:
                sock.sendall(zpl.encode("ascii"))
        except (OSError, UnicodeError) as exc:
            return PrintResult(
                PrintStatus.ERROR,
                "Print Error",
                f"Could not send the label to {self._opts.host}:{self._opts.port} "
                f"— {exc}. Check the printer is powered on and on the network.",
            )

        return PrintResult(PrintStatus.OK)


class _ZplSetupDialog(QDialog):
    """Host/port/media settings for a ZPL printer."""

    def __init__(self, opts: ZplOptions, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ZPL printer — setup")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._host = QLineEdit(opts.host)
        self._host.setPlaceholderText("192.168.1.50")
        form.addRow("Printer IP / host:", self._host)

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(opts.port)
        form.addRow("Port:", self._port)

        self._dpi = QSpinBox()
        self._dpi.setRange(72, 2400)
        self._dpi.setValue(opts.dpi)
        form.addRow("Printer resolution (dpi):", self._dpi)

        self._width = QDoubleSpinBox()
        self._width.setRange(5.0, 200.0)
        self._width.setSuffix(" mm")
        self._width.setValue(opts.label_width_mm)
        form.addRow("Loaded label width:", self._width)

        self._height = QDoubleSpinBox()
        self._height.setRange(5.0, 200.0)
        self._height.setSuffix(" mm")
        self._height.setValue(opts.label_height_mm)
        form.addRow("Loaded label height:", self._height)

        layout.addLayout(form)

        note = QLabel(
            "These values describe the stock you loaded — the tool cannot read "
            "them from the printer. If they don't match the labels in the "
            "machine, the QR will print at the wrong size."
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

        self._opts = opts

    def values(self) -> dict[str, Any]:
        return {
            **self._opts.model_dump(),
            "host": self._host.text().strip(),
            "port": self._port.value(),
            "dpi": self._dpi.value(),
            "label_width_mm": self._width.value(),
            "label_height_mm": self._height.value(),
        }
