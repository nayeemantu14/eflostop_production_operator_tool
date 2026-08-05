"""Large PASS/FAIL/IDLE status banner widget."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel, QSizePolicy


class BigStatusBanner(QLabel):
    """48pt status banner: IDLE (gray), RUNNING (blue), PASS (green), FAIL (red)."""

    STYLES = {
        "idle": {
            "text": "READY",
            "bg": "#424242",
            "fg": "#FFFFFF",
        },
        "running": {
            "text": "RUNNING...",
            "bg": "#1565C0",
            "fg": "#FFFFFF",
        },
        "pass": {
            "text": "PASS",
            "bg": "#2E7D32",
            "fg": "#FFFFFF",
        },
        "fail": {
            "text": "FAIL",
            "bg": "#C62828",
            "fg": "#FFFFFF",
        },
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(80)
        font = QFont()
        font.setPointSize(36)
        font.setBold(True)
        self.setFont(font)
        self.set_status("idle")

    def set_status(self, status: str, custom_text: str = "") -> None:
        style = self.STYLES.get(status, self.STYLES["idle"])
        text = custom_text or style["text"]
        self.setText(text)
        self.setStyleSheet(
            f"background-color: {style['bg']}; "
            f"color: {style['fg']}; "
            f"border-radius: 8px; "
            f"padding: 8px;"
        )
