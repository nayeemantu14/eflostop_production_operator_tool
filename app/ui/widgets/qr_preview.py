"""QR code preview widget with pluggable label printing.

Owns the on-screen QR and the operator's Print / Printer Setup controls. It does
not know how any printer works: it asks the selected backend to configure itself
or to print, and shows whatever the backend reports. See
app/services/printing/ and docs/PRINTER_BACKENDS.md.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...services.printing import geometry
from ...services.printing.base import LabelPrintRequest
from ...services.printing.selection import PrinterSelection, shared_selection
from .printer_selector import PrinterSelectorCombo

# Re-exported from the shared geometry module so the manufacturing spec has one
# definition. Kept importable from here because the print-geometry tests and
# other callers refer to them by this path.
QR_LABEL_SIZE_MM = geometry.QR_LABEL_SIZE_MM
QR_MIN_PRINT_MM = geometry.QR_MIN_PRINT_MM


class _MessageBoxUi:
    """Shows the shared print guards as native dialogs.

    The guards live in the printing package, which has no business importing
    QMessageBox; this adapter is how their questions reach the operator. Every
    dialog is parented to the widget so it is modal and cannot end up behind the
    main window.
    """

    def __init__(self, parent: QWidget) -> None:
        self._parent = parent

    def confirm(self, title: str, message: str) -> bool:
        return (
            QMessageBox.question(
                self._parent,
                title,
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def warn(self, title: str, message: str) -> None:
        QMessageBox.warning(self._parent, title, message)


class QrPreview(QWidget):
    """Displays a QR code image with device info below and Print/Setup buttons."""

    def __init__(self, parent=None, selection: PrinterSelection | None = None):
        super().__init__(parent)
        self._qr_image: QImage | None = None
        self._info_text: str = ""
        # Shared with every other QrPreview in the app, so changing the printer
        # on one tab changes it everywhere. Injectable for tests.
        self._selection = selection if selection is not None else shared_selection()
        self._guard_ui = _MessageBoxUi(self)

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

        # --- Printer row: which printer the label goes to ---
        printer_row = QHBoxLayout()
        printer_row.setSpacing(6)
        printer_label = QLabel("Printer:")
        printer_label.setStyleSheet("font-size: 11px;")
        self.printer_combo = PrinterSelectorCombo(self._selection)
        self.printer_combo.setMinimumWidth(180)
        printer_row.addWidget(printer_label)
        printer_row.addWidget(self.printer_combo, stretch=1)

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

        # Extra per-backend operations (test print, calibration help, ...). The
        # widget renders whatever the backend offers without knowing what any of
        # it does, so a new printer can add a button with no change here.
        self.actions_row = QHBoxLayout()
        self.actions_row.setSpacing(6)

        layout.addWidget(self.image_label)
        layout.addWidget(self.info_label)
        layout.addLayout(printer_row)
        layout.addLayout(btn_row)
        layout.addLayout(self.actions_row)

        self._selection.changed.connect(self._on_backend_changed)
        self._refresh_backend_ui()

    # --- QR content ---------------------------------------------------------

    def set_qr_png_bytes(self, png_bytes: bytes, info_text: str = "") -> None:
        """Display QR from PNG bytes."""
        img = QImage()
        if not img.loadFromData(png_bytes) or img.isNull():
            # A QImage that failed to load is not None but is null, and would
            # print as a blank 20 mm label. Refuse rather than label a device
            # with nothing.
            self.clear()
            self.info_label.setText("QR image could not be read")
            return
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

    # --- Backend plumbing ---------------------------------------------------

    def _on_backend_changed(self, _backend_id: str) -> None:
        self._refresh_backend_ui()

    def _refresh_backend_ui(self) -> None:
        """Re-render the parts of the panel that depend on the chosen backend."""
        backend = self._selection.current_backend()

        # Setup is offered only if the backend has something to configure —
        # asked as a capability, never as "which backend is this".
        self.setup_btn.setEnabled(
            backend is not None and backend.capabilities.configurable
        )

        while self.actions_row.count():
            item = self.actions_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if backend is None:
            return
        try:
            actions = list(backend.actions())
        except Exception:
            actions = []
        for action in actions:
            button = QPushButton(action.label)
            button.setEnabled(action.enabled)
            if action.tooltip:
                button.setToolTip(action.tooltip)
            button.setStyleSheet("font-size: 11px; padding: 3px 8px;")
            button.clicked.connect(
                lambda _checked, cb=action.callback: self._run_action(cb)
            )
            self.actions_row.addWidget(button)

    def _run_action(self, callback) -> None:
        # Anything a backend raises here would otherwise escape a Qt slot, which
        # terminates the process instead of unwinding.
        try:
            callback(self)
        except Exception as exc:
            QMessageBox.warning(self, "Printer", f"That printer action failed: {exc}")
        else:
            self._selection.persist_current_options()
            self.printer_combo.reload()

    def _on_setup(self) -> None:
        """Open the selected backend's own configuration UI."""
        backend = self._selection.current_backend()
        if backend is None:
            QMessageBox.warning(
                self, "Printer Setup",
                "No label printer backend is available. Check the tool's "
                "configuration.",
            )
            return
        try:
            backend.configure(self)
        except Exception as exc:
            QMessageBox.warning(
                self, "Printer Setup", f"Printer setup failed: {exc}"
            )
            return
        self._selection.persist_current_options()
        self.printer_combo.reload()
        self._refresh_backend_ui()

    def _on_print(self) -> None:
        """Print the QR label using the selected backend."""
        if self._qr_image is None:
            return

        backend = self._selection.current_backend()
        if backend is None:
            QMessageBox.warning(
                self, "Print Error",
                "No label printer backend is available. Check the tool's "
                "configuration.",
            )
            return

        try:
            request = LabelPrintRequest(
                image=self._qr_image, ui=self._guard_ui, parent=self
            )
            result = backend.print_label(request)
        except Exception as exc:
            QMessageBox.warning(
                self, "Print Error", f"Printing failed unexpectedly: {exc}"
            )
            return

        # An operator must never click Print and get silence. CANCELLED is the
        # one quiet case: they just answered No to a guard dialog.
        if result.needs_dialog:
            QMessageBox.warning(
                self, result.title or "Print Error",
                result.message or "The label could not be printed.",
            )
            self.printer_combo.reload()

    # --- Geometry helpers ---------------------------------------------------
    # Thin delegates to the shared geometry module, kept on the widget so the
    # existing print-geometry tests exercise the production predicates.

    @staticmethod
    def _mm_to_px(mm: float, dpi: int) -> int:
        """Convert millimeters to device pixels at the given DPI."""
        return geometry.mm_to_px(mm, dpi)

    @staticmethod
    def _px_to_mm(px: float, dpi: int) -> float:
        """Convert device pixels to millimetres (inverse of _mm_to_px)."""
        return geometry.px_to_mm(px, dpi)

    @classmethod
    def _is_undersized(cls, side_px: float, dpi: int) -> bool:
        """True if the printed QR would fall below the scannable floor."""
        return geometry.is_undersized(side_px, dpi)
