"""History tab — view, filter, and export production records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..services.record_logger import RecordLogger


class HistoryTab(QWidget):
    def __init__(self, record_logger: RecordLogger, parent=None):
        super().__init__(parent)
        self.record_logger = record_logger
        self._current_page = 0
        self._page_size = 50

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Filter bar
        filter_row = QHBoxLayout()

        filter_row.addWidget(QLabel("Device:"))
        self.device_filter = QComboBox()
        self.device_filter.addItems(["All", "hub", "valve", "sensor"])
        self.device_filter.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.device_filter)

        filter_row.addSpacing(20)

        filter_row.addWidget(QLabel("Result:"))
        self.result_filter = QComboBox()
        self.result_filter.addItems(["All", "PASS", "FAIL"])
        self.result_filter.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.result_filter)

        filter_row.addStretch()

        # Stats
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("font-weight: bold;")
        filter_row.addWidget(self.stats_label)

        filter_row.addSpacing(20)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._load_data)
        filter_row.addWidget(self.refresh_btn)

        self.export_btn = QPushButton("Export CSV")
        self.export_btn.clicked.connect(self._export_csv)
        filter_row.addWidget(self.export_btn)

        layout.addLayout(filter_row)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "Timestamp", "Device", "Serial Number", "UID",
            "BLE MAC", "FW Version", "Operator", "Work Order", "Result", "Notes",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet(
            "QTableWidget { gridline-color: #ddd; }"
            "QTableWidget::item:selected { background-color: #1565C0; color: white; }"
        )

        layout.addWidget(self.table, stretch=1)

        # Pagination
        page_row = QHBoxLayout()
        self.prev_btn = QPushButton("< Previous")
        self.prev_btn.clicked.connect(self._prev_page)
        page_row.addWidget(self.prev_btn)

        self.page_label = QLabel("Page 1")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_row.addWidget(self.page_label, stretch=1)

        self.next_btn = QPushButton("Next >")
        self.next_btn.clicked.connect(self._next_page)
        page_row.addWidget(self.next_btn)

        layout.addLayout(page_row)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load_data()

    def _get_filters(self) -> tuple[str | None, str | None]:
        device = self.device_filter.currentText()
        result = self.result_filter.currentText()
        return (
            device if device != "All" else None,
            result if result != "All" else None,
        )

    def _load_data(self) -> None:
        device_type, result = self._get_filters()

        total = self.record_logger.count(device_type=device_type, result=result)
        pass_count = self.record_logger.count(device_type=device_type, result="PASS")
        fail_count = self.record_logger.count(device_type=device_type, result="FAIL")

        self.stats_label.setText(
            f"Total: {total}  |  Pass: {pass_count}  |  Fail: {fail_count}"
        )

        records = self.record_logger.query(
            device_type=device_type,
            result=result,
            limit=self._page_size,
            offset=self._current_page * self._page_size,
        )

        self.table.setRowCount(len(records))
        for row_idx, record in enumerate(records):
            fields = [
                record.get("timestamp", ""),
                record.get("device_type", ""),
                record.get("serial_number", ""),
                record.get("uid", ""),
                record.get("ble_mac", ""),
                record.get("fw_version", ""),
                record.get("operator", ""),
                record.get("work_order", ""),
                record.get("result", ""),
                record.get("notes", ""),
            ]
            for col_idx, value in enumerate(fields):
                item = QTableWidgetItem(str(value))
                # Color-code result column
                if col_idx == 8:
                    if value == "PASS":
                        item.setForeground(QColor("#4CAF50"))
                        item.setFont(QFont("", -1, QFont.Weight.Bold))
                    elif value == "FAIL":
                        item.setForeground(QColor("#F44336"))
                        item.setFont(QFont("", -1, QFont.Weight.Bold))
                self.table.setItem(row_idx, col_idx, item)

        max_pages = max(1, (total + self._page_size - 1) // self._page_size)
        self.page_label.setText(f"Page {self._current_page + 1} of {max_pages}")
        self.prev_btn.setEnabled(self._current_page > 0)
        self.next_btn.setEnabled(self._current_page < max_pages - 1)

    def _on_filter_changed(self) -> None:
        self._current_page = 0
        self._load_data()

    def _prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._load_data()

    def _next_page(self) -> None:
        self._current_page += 1
        self._load_data()

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Records", "production_records.csv",
            "CSV Files (*.csv)",
        )
        if path:
            device_type, _ = self._get_filters()
            count = self.record_logger.export_csv(Path(path), device_type=device_type)
            QMessageBox.information(
                self, "Export Complete",
                f"Exported {count} records to:\n{path}",
            )
