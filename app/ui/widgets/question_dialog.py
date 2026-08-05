"""Large operator-friendly Yes/No question dialog."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class QuestionDialog(QDialog):
    """Large-button Yes/No dialog for production operators.

    Usage:
        dlg = QuestionDialog("Is the LED blinking?", parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # Yes
        else:
            # No
    """

    def __init__(self, question: str, parent=None, yes_text: str = "YES", no_text: str = "NO"):
        super().__init__(parent)
        self.setWindowTitle("Operator Check")
        self.setMinimumSize(500, 250)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # Question label
        q_label = QLabel(question)
        q_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        q_label.setWordWrap(True)
        q_font = QFont()
        q_font.setPointSize(18)
        q_label.setFont(q_font)
        layout.addWidget(q_label)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(30)

        btn_font = QFont()
        btn_font.setPointSize(20)
        btn_font.setBold(True)

        self.yes_btn = QPushButton(yes_text)
        self.yes_btn.setFont(btn_font)
        self.yes_btn.setFixedHeight(70)
        self.yes_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; border-radius: 8px; }"
            "QPushButton:hover { background-color: #66BB6A; }"
            "QPushButton:pressed { background-color: #388E3C; }"
        )
        self.yes_btn.clicked.connect(self.accept)

        self.no_btn = QPushButton(no_text)
        self.no_btn.setFont(btn_font)
        self.no_btn.setFixedHeight(70)
        self.no_btn.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white; border-radius: 8px; }"
            "QPushButton:hover { background-color: #EF5350; }"
            "QPushButton:pressed { background-color: #D32F2F; }"
        )
        self.no_btn.clicked.connect(self.reject)

        btn_layout.addWidget(self.yes_btn, stretch=1)
        btn_layout.addWidget(self.no_btn, stretch=1)
        layout.addLayout(btn_layout)


def ask_operator(question: str, parent=None) -> bool:
    """Show a Yes/No dialog and return True for Yes."""
    dlg = QuestionDialog(question, parent=parent)
    return dlg.exec() == QDialog.DialogCode.Accepted
