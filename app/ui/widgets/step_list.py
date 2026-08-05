"""Step list widget — vertical checklist showing pending/running/pass/fail steps."""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter
from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget


STATUS_STYLES = {
    "pending": {"icon": "\u25cb", "color": "#888888", "bg": None},        # ○
    "running": {"icon": "\u25d4", "color": "#2196F3", "bg": "#E3F2FD"},   # ◔
    "pass":    {"icon": "\u2714", "color": "#4CAF50", "bg": "#E8F5E9"},   # ✔
    "fail":    {"icon": "\u2718", "color": "#F44336", "bg": "#FFEBEE"},   # ✘
    "skipped": {"icon": "\u2500", "color": "#9E9E9E", "bg": None},        # ─
}


class StepRow(QWidget):
    """A single step row with icon, name, and detail.

    The entire row is drawn in a single paintEvent — no child widgets — to
    avoid Qt double-buffering / WA_TranslucentBackground compositing artifacts
    that left stale text from previous status states overlapping on Windows.
    """

    _ROW_HEIGHT = 36
    _MARGIN = 8
    _ICON_WIDTH = 24
    _ICON_GAP = 4

    def __init__(self, step_id: str, name: str, parent=None):
        super().__init__(parent)
        self.step_id = step_id
        self.name = name
        self.detail = ""
        self.status = "pending"
        self._style = STATUS_STYLES["pending"]

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self._ROW_HEIGHT)

    def set_status(self, status: str, detail: str = "") -> None:
        self.status = status
        self.detail = detail
        self._style = STATUS_STYLES.get(status, STATUS_STYLES["pending"])
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        rect = self.rect()

        # 1) Background fill (rounded). When None, leave the area transparent
        #    so the parent shows through.
        bg = self._style["bg"]
        if bg:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(bg)))
            painter.drawRoundedRect(rect, 4, 4)

        # 2) Icon (status glyph), centered in a fixed-width column on the left.
        icon_font = QFont()
        icon_font.setPointSize(14)
        painter.setFont(icon_font)
        painter.setPen(QColor(self._style["color"]))
        icon_rect = QRect(
            rect.left() + self._MARGIN,
            rect.top(),
            self._ICON_WIDTH,
            rect.height(),
        )
        painter.drawText(
            icon_rect,
            Qt.AlignmentFlag.AlignCenter,
            self._style["icon"],
        )

        # 3) Detail (right-aligned). Measure first so the name area can avoid
        #    overlapping it.
        name_font = QFont()
        name_font.setPointSize(10)
        painter.setFont(name_font)
        fm = painter.fontMetrics()

        detail_text = self.detail or ""
        detail_w = fm.horizontalAdvance(detail_text) if detail_text else 0

        # 4) Name (left-aligned) — fills the space between the icon and the
        #    detail text. Elide if necessary.
        name_left = rect.left() + self._MARGIN + self._ICON_WIDTH + self._ICON_GAP
        name_right = rect.right() - self._MARGIN - (detail_w + self._ICON_GAP if detail_w else 0)
        name_rect = QRect(
            name_left,
            rect.top(),
            max(0, name_right - name_left),
            rect.height(),
        )
        elided_name = fm.elidedText(self.name, Qt.TextElideMode.ElideRight, name_rect.width())
        painter.setPen(QColor("#000000"))
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_name,
        )

        # 5) Detail text on the right.
        if detail_text:
            detail_rect = QRect(
                rect.right() - self._MARGIN - detail_w,
                rect.top(),
                detail_w,
                rect.height(),
            )
            painter.setPen(QColor("#666666"))
            painter.drawText(
                detail_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                detail_text,
            )

        painter.end()


class StepListWidget(QWidget):
    """Vertical list of step rows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(2)
        self._rows: dict[str, StepRow] = {}

    def set_steps(self, steps: list[dict]) -> None:
        """Initialize the step list.

        Args:
            steps: List of {"id": str, "name": str} dicts
        """
        self.clear()
        for step in steps:
            row = StepRow(step["id"], step["name"])
            self._rows[step["id"]] = row
            self.layout_.addWidget(row)
        self.layout_.addStretch()

    def update_step(self, step_id: str, status: str, detail: str = "") -> None:
        """Update a specific step's status."""
        row = self._rows.get(step_id)
        if row:
            row.set_status(status, detail)

    def reset_all(self) -> None:
        """Reset all steps to pending."""
        for row in self._rows.values():
            row.set_status("pending", "")

    def clear(self) -> None:
        """Remove all step rows."""
        for row in self._rows.values():
            self.layout_.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
