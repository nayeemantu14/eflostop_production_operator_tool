"""eFloStop II Production Programming & Test Tool — Entry Point."""

import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("eFloStop II Production Tool")
    app.setOrganizationName("eFloStop")

    # Set default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Global stylesheet
    app.setStyleSheet("""
        QMainWindow { background-color: #FAFAFA; }
        QTabWidget::pane { border: 1px solid #ccc; }
        QTabBar::tab {
            padding: 8px 20px;
            min-width: 120px;
            font-size: 12px;
        }
        QTabBar::tab:selected {
            background: #1565C0;
            color: white;
            font-weight: bold;
        }
        QTabBar::tab:!selected {
            background: #E0E0E0;
        }
    """)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
