"""Firmware info panel with version display and Browse override."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class FirmwarePanel(QWidget):
    """Displays firmware version and file status. Allows Browse override.

    Signals:
        firmware_overridden(str, str): (role, new_path) emitted when user overrides a file
        firmware_reset(str): (role) emitted when override is cleared
    """

    firmware_overridden = pyqtSignal(str, str)
    firmware_reset = pyqtSignal(str)

    def __init__(self, device_name: str, parent=None):
        super().__init__(parent)
        self.device_name = device_name
        self._overrides: dict[str, Path] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        # Header
        header = QHBoxLayout()
        title = QLabel(f"{device_name} Firmware")
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)

        # Firmware version intentionally not shown — the manifest value can be
        # stale; the device-reported version is surfaced during the test run.
        header.addStretch()

        self.status_label = QLabel("")
        header.addWidget(self.status_label)
        layout.addLayout(header)

        # File rows container
        self.files_layout = QVBoxLayout()
        self.files_layout.setSpacing(2)
        layout.addLayout(self.files_layout)

        self._file_rows: dict[str, _FileRow] = {}

    def set_firmware_info(
        self,
        version: str,
        files: dict[str, dict],  # {role: {path, exists, sha256, override}}
    ) -> None:
        """Update firmware display."""
        # Version intentionally not displayed (manifest value may be stale).

        # Clear existing rows
        for row in self._file_rows.values():
            self.files_layout.removeWidget(row)
            row.deleteLater()
        self._file_rows.clear()

        all_ok = True
        for role, info in files.items():
            row = _FileRow(role, info.get("path", ""), info.get("exists", False))
            row.browse_clicked.connect(lambda r=role: self._on_browse(r))
            row.reset_clicked.connect(lambda r=role: self._on_reset(r))

            if info.get("override"):
                row.set_override(info["override"])
            if not info.get("exists", False) and not info.get("override"):
                all_ok = False

            self._file_rows[role] = row
            self.files_layout.addWidget(row)

        if all_ok:
            self.status_label.setText("All files present")
            self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self.status_label.setText("MISSING FILES")
            self.status_label.setStyleSheet("color: #F44336; font-weight: bold;")

    def _on_browse(self, role: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select {role} firmware", "",
            "Firmware Files (*.bin *.hex);;All Files (*)",
        )
        if path:
            self._overrides[role] = Path(path)
            row = self._file_rows.get(role)
            if row:
                row.set_override(path)
            self.firmware_overridden.emit(role, path)

    def _on_reset(self, role: str) -> None:
        self._overrides.pop(role, None)
        row = self._file_rows.get(role)
        if row:
            row.clear_override()
        self.firmware_reset.emit(role)


class _FileRow(QWidget):
    browse_clicked = pyqtSignal()
    reset_clicked = pyqtSignal()

    def __init__(self, role: str, path: str, exists: bool, parent=None):
        super().__init__(parent)
        self.role = role
        self._default_path = path

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.role_label = QLabel(role + ":")
        self.role_label.setFixedWidth(120)
        self.role_label.setStyleSheet("font-weight: bold;")

        self.path_label = QLabel(Path(path).name if path else "NOT SET")
        self.path_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.status_icon = QLabel("\u2714" if exists else "\u2718")
        self.status_icon.setStyleSheet(
            f"color: {'#4CAF50' if exists else '#F44336'}; font-size: 14px;"
        )
        self.status_icon.setFixedWidth(20)

        self.browse_btn = QPushButton("Browse")
        self.browse_btn.setFixedWidth(70)
        self.browse_btn.clicked.connect(self.browse_clicked.emit)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setFixedWidth(60)
        self.reset_btn.setVisible(False)
        self.reset_btn.clicked.connect(self.reset_clicked.emit)

        layout.addWidget(self.role_label)
        layout.addWidget(self.path_label, stretch=1)
        layout.addWidget(self.status_icon)
        layout.addWidget(self.browse_btn)
        layout.addWidget(self.reset_btn)

    def set_override(self, path: str) -> None:
        self.path_label.setText(f"{Path(path).name} (OVERRIDE)")
        self.path_label.setStyleSheet("color: #FF9800;")
        self.status_icon.setText("\u2714")
        self.status_icon.setStyleSheet("color: #FF9800; font-size: 14px;")
        self.reset_btn.setVisible(True)

    def clear_override(self) -> None:
        self.path_label.setText(Path(self._default_path).name if self._default_path else "NOT SET")
        self.path_label.setStyleSheet("")
        self.reset_btn.setVisible(False)
