"""Color-coded log viewer widget."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QTextCharFormat
from PyQt6.QtWidgets import QPlainTextEdit, QWidget, QVBoxLayout


LOG_COLORS = {
    "info":  QColor("#FFFFFF"),
    "warn":  QColor("#FFC107"),
    "error": QColor("#F44336"),
    "debug": QColor("#9E9E9E"),
    "pass":  QColor("#4CAF50"),
    "fail":  QColor("#F44336"),
}


class LogViewer(QWidget):
    """Scrolling log viewer with color-coded levels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMaximumBlockCount(5000)

        font = QFont("Consolas", 9)
        self.text_edit.setFont(font)
        self.text_edit.setStyleSheet(
            "QPlainTextEdit { background-color: #1E1E1E; color: #FFFFFF; "
            "border: 1px solid #333; }"
        )

        layout.addWidget(self.text_edit)

    def append(self, message: str, level: str = "info") -> None:
        """Append a log line with color based on level."""
        color = LOG_COLORS.get(level, LOG_COLORS["info"])
        fmt = QTextCharFormat()
        fmt.setForeground(color)

        cursor = self.text_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(message + "\n", fmt)
        self.text_edit.setTextCursor(cursor)
        self.text_edit.ensureCursorVisible()

    def clear(self) -> None:
        self.text_edit.clear()

    def get_text(self) -> str:
        return self.text_edit.toPlainText()
