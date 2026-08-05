"""QR code preview widget with system print support."""

from __future__ import annotations

from PyQt6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PyQt6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPixmap
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Fixed physical size of the printed QR label, in millimetres. Confirmed with
# the manufacturing partner: every device's QR label (hub, valve, leak sensor)
# is 20 mm x 20 mm. Too small for side text, so the printed label is QR-only.
QR_LABEL_SIZE_MM = 20

# Below this printed size the QR's modules get too small to scan reliably on a
# ~203 dpi thermal printer, so the operator is warned. A full-bleed 20 mm label
# printer prints the full 20 mm and never trips this; it catches a mis-selected
# printer whose hardware margin shrinks the QR (e.g. an office printer -> ~12 mm).
QR_MIN_PRINT_MM = 18


class QrPreview(QWidget):
    """Displays a QR code image with device info below and Print/Setup buttons."""

    # Shared printer instance — retains settings (printer name, paper size,
    # orientation, margins) across prints for the entire session.
    _printer: QPrinter | None = None

    @classmethod
    def _get_printer(cls) -> QPrinter:
        if cls._printer is None:
            cls._printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        return cls._printer

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qr_image: QImage | None = None
        self._info_text: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(320, 320)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.image_label.setStyleSheet("border: 1px solid #ccc; background: white;")

        self.info_label = QLabel("No QR generated")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("color: #ccc; font-size: 11px; font-family: monospace;")
        self.info_label.setWordWrap(True)

        # --- Button row: Print + Printer Setup ---
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.print_btn = QPushButton("Print Label")
        self.print_btn.setFixedHeight(36)
        self.print_btn.setVisible(False)
        self.print_btn.setStyleSheet(
            "QPushButton { background-color: #2E7D32; color: white; font-size: 13px; "
            "font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover { background-color: #388E3C; }"
        )
        self.print_btn.clicked.connect(self._on_print)

        self.setup_btn = QPushButton("Printer Setup")
        self.setup_btn.setFixedHeight(36)
        self.setup_btn.setVisible(False)
        self.setup_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; font-size: 13px; "
            "font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1976D2; }"
        )
        self.setup_btn.clicked.connect(self._on_setup)

        btn_row.addWidget(self.print_btn)
        btn_row.addWidget(self.setup_btn)

        layout.addWidget(self.image_label)
        layout.addWidget(self.info_label)
        layout.addLayout(btn_row)

    def set_qr_png_bytes(self, png_bytes: bytes, info_text: str = "") -> None:
        """Display QR from PNG bytes."""
        img = QImage()
        img.loadFromData(png_bytes)
        self._qr_image = img
        self._info_text = info_text

        pixmap = QPixmap.fromImage(img)
        # Display at 320px with crisp (nearest-neighbour) scaling. The structured
        # payload is a denser v4 QR, so a larger, sharp on-screen code is needed
        # to scan reliably from a phone camera (200px + smoothing was marginal).
        scaled = pixmap.scaled(
            320, 320,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.info_label.setText(info_text)
        self.print_btn.setVisible(True)
        self.setup_btn.setVisible(True)

    def clear(self) -> None:
        self._qr_image = None
        self._info_text = ""
        self.image_label.clear()
        self.image_label.setText("")
        self.info_label.setText("No QR generated")
        self.print_btn.setVisible(False)
        self.setup_btn.setVisible(False)

    def _on_setup(self) -> None:
        """Open printer/page setup dialog to configure printer settings."""
        printer = self._get_printer()
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("Printer Setup")
        dialog.exec()

    def _on_print(self) -> None:
        """Print the QR label directly using the saved printer settings."""
        if self._qr_image is None:
            return

        printer = self._get_printer()

        # If no printer has been configured yet, open setup first
        if not printer.printerName():
            dialog = QPrintDialog(printer, self)
            dialog.setWindowTitle("Select Printer")
            if dialog.exec() != QPrintDialog.DialogCode.Accepted:
                return

        self._paint_label(printer)

    @staticmethod
    def _mm_to_px(mm: float, dpi: int) -> int:
        """Convert millimeters to device pixels at the given DPI.

        Rounds (not truncates) so the physical size lands on the spec rather
        than systematically a hair under it (e.g. 20 mm -> 20.02 mm not 19.90 mm
        at 203 dpi).
        """
        return round(mm / 25.4 * dpi)

    @staticmethod
    def _px_to_mm(px: float, dpi: int) -> float:
        """Convert device pixels to millimetres (inverse of _mm_to_px)."""
        return px * 25.4 / dpi

    @classmethod
    def _is_undersized(cls, side_px: float, dpi: int) -> bool:
        """True if the printed QR would fall below the scannable floor.

        Shared by the print guard and its tests so the boundary can't silently
        drift.
        """
        return side_px < cls._mm_to_px(QR_MIN_PRINT_MM, dpi)

    def _paint_label(self, printer: QPrinter) -> None:
        """Render the QR onto a fixed 20 mm x 20 mm label.

        The manufacturing spec fixes every device's QR label at
        ``QR_LABEL_SIZE_MM`` square — too small for side text, so the label is
        QR-only. The page is forced to a 20 mm square full-bleed so the output
        matches the label stock regardless of the printer's saved page setup;
        the QR is then centred and scaled to fill the printable area. The QR
        image already carries a 4-module quiet zone, which becomes the required
        white border. Sizing is done in millimetres and converted to device
        pixels via the printer's DPI, so the physical size is identical on every
        printer regardless of resolution.
        """
        # Force the label media to the 20 mm x 20 mm manufacturing spec so the
        # output is correct even if the operator's saved page setup differs.
        printer.setFullPage(True)
        printer.setPageSize(
            QPageSize(
                QSizeF(QR_LABEL_SIZE_MM, QR_LABEL_SIZE_MM),
                QPageSize.Unit.Millimeter,
            )
        )
        printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)

        layout = printer.pageLayout()
        dpi = printer.resolution()

        # In full-bleed mode pageRect() is the whole 20 mm media (origin at the
        # media corner). It does NOT reflect the printer's hardware non-printable
        # border — that is exposed only via minimumMargins() — so read those
        # separately and shrink the draw area to what the printer can actually
        # mark. On a true full-bleed label printer the margins are ~0 and the QR
        # fills the full 20 mm; a printer that cannot mark to the edge fits the QR
        # inside the printable area instead of clipping it — and if that pushes
        # the QR under 20 mm the operator is warned (see the size check below).
        page = printer.pageRect(QPrinter.Unit.DevicePixel)
        margins = layout.minimumMargins()  # QMarginsF, in the layout units (mm)
        printable = QRectF(
            page.left() + self._mm_to_px(margins.left(), dpi),
            page.top() + self._mm_to_px(margins.top(), dpi),
            page.width() - self._mm_to_px(margins.left() + margins.right(), dpi),
            page.height() - self._mm_to_px(margins.top() + margins.bottom(), dpi),
        )

        # Fit the QR to the 20 mm target, never exceeding the printable area.
        target_px = self._mm_to_px(QR_LABEL_SIZE_MM, dpi)
        side = min(target_px, printable.width(), printable.height())

        # Read back the media the driver actually accepted. setPageSize is a
        # request, not a guarantee: a driver may reject the 20 mm custom size and
        # fall back to a larger default page (Letter/A4), which would print a
        # correct-size QR centred off the physical label. Catch that instead of
        # silently wasting label stock.
        page_mm = layout.pageSize().size(QPageSize.Unit.Millimeter)
        tol_mm = 1.0
        media_ok = (
            abs(page_mm.width() - QR_LABEL_SIZE_MM) <= tol_mm
            and abs(page_mm.height() - QR_LABEL_SIZE_MM) <= tol_mm
        )
        # A printer that accepts 20 mm media but cannot mark to the edge shrinks
        # the QR. A true full-bleed label printer has ~0 margin so side == target
        # and this stays False; a mis-selected office printer (several mm of
        # border) shrinks the QR below the scannable floor and trips it.
        undersized = self._is_undersized(side, dpi)

        if side <= 0:
            QMessageBox.warning(
                self, "Print Error",
                "The printer reported no printable area, so the 20 mm label "
                "could not be rendered. Select the 20 mm label media in Printer "
                "Setup and try again.",
            )
            return

        if not media_ok:
            proceed = QMessageBox.question(
                self, "Label size is not 20 mm",
                f"The selected printer's page is {page_mm.width():.1f} x "
                f"{page_mm.height():.1f} mm, not the required 20 x 20 mm, so the "
                f"QR may print off the label.\n\nSelect the 20 mm label media in "
                f"Printer Setup, or print anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return
        elif undersized:
            actual_mm = self._px_to_mm(side, dpi)
            proceed = QMessageBox.question(
                self, "QR would print under 20 mm",
                f"This printer's non-printable border shrinks the QR to only "
                f"{actual_mm:.1f} mm instead of 20 mm, so it may not scan "
                f"reliably.\n\nSelect a full-bleed 20 mm label printer in Printer "
                f"Setup, or print anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return

        painter = QPainter(printer)
        if not painter.isActive():
            QMessageBox.warning(
                self, "Print Error",
                "Could not start printing. Check that the printer is available.",
            )
            return

        # Centre the QR within the printable area of the label.
        qr_rect = QRectF(
            printable.left() + (printable.width() - side) / 2,
            printable.top() + (printable.height() - side) / 2,
            side,
            side,
        )
        painter.drawImage(qr_rect, self._qr_image)
        painter.end()
