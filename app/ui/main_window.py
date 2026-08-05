"""Main application window with operator bar, firmware header, and device tabs."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config.settings import settings
from ..services.firmware_registry import FirmwareRegistry
from ..services.record_logger import RecordLogger
from ..services.serial_generator import SerialGenerator
from .tab_wifi_hub import WiFiHubTab
from .tab_valve import ValveTab
from .tab_leak_sensor import LeakSensorTab
from .tab_history import HistoryTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("eFloStop II Production Tool v" + settings.general.tool_version)
        self.setMinimumSize(1100, 750)

        # Services
        self.firmware_registry = FirmwareRegistry(settings.manifest_full_path)
        self.record_logger = RecordLogger(settings.data_path)
        self.serial_generator = SerialGenerator(settings.data_path / "serials.db")

        # Try loading firmware manifest
        try:
            self.firmware_registry.load()
        except FileNotFoundError:
            pass  # Will show warnings in tabs

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Operator bar
        main_layout.addWidget(self._build_operator_bar())

        # Firmware status strip
        main_layout.addWidget(self._build_firmware_strip())

        # Device tabs
        self.tabs = QTabWidget()
        self.tabs.setFont(QFont("", 11))

        self.hub_tab = WiFiHubTab(
            self.firmware_registry,
            self.serial_generator,
            self.record_logger,
            settings,
        )
        self.valve_tab = ValveTab(
            self.firmware_registry,
            self.serial_generator,
            self.record_logger,
            settings,
        )
        self.sensor_tab = LeakSensorTab(
            self.firmware_registry,
            self.serial_generator,
            self.record_logger,
            settings,
        )
        self.history_tab = HistoryTab(self.record_logger)

        self.tabs.addTab(self.hub_tab, "WiFi Hub")
        self.tabs.addTab(self.valve_tab, "Valve")
        self.tabs.addTab(self.sensor_tab, "Leak Sensor")
        self.tabs.addTab(self.history_tab, "History")

        main_layout.addWidget(self.tabs, stretch=1)

    def _build_operator_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background-color: #263238; border-radius: 4px; padding: 4px;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)

        lbl = QLabel("Operator:")
        lbl.setStyleSheet("color: white; font-weight: bold;")
        layout.addWidget(lbl)

        self.operator_input = QLineEdit()
        self.operator_input.setPlaceholderText("Enter operator ID (e.g. OP-0412)")
        self.operator_input.setFixedWidth(200)
        self.operator_input.setStyleSheet(
            "background: white; border-radius: 3px; padding: 4px;"
        )
        layout.addWidget(self.operator_input)

        layout.addSpacing(20)

        wo_lbl = QLabel("Work Order:")
        wo_lbl.setStyleSheet("color: white; font-weight: bold;")
        layout.addWidget(wo_lbl)

        self.work_order_input = QLineEdit()
        self.work_order_input.setPlaceholderText("WO-2026-XXXXX (optional)")
        self.work_order_input.setFixedWidth(200)
        self.work_order_input.setStyleSheet(
            "background: white; border-radius: 3px; padding: 4px;"
        )
        layout.addWidget(self.work_order_input)

        layout.addStretch()

        # Connection status
        self.conn_label = QLabel("No device connected")
        self.conn_label.setStyleSheet("color: #FFC107;")
        layout.addWidget(self.conn_label)

        return bar

    def _build_firmware_strip(self) -> QWidget:
        strip = QWidget()
        strip.setStyleSheet("background-color: #37474F; border-radius: 4px;")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(12, 4, 12, 4)

        fw_label = QLabel("Firmware:")
        fw_label.setStyleSheet("color: white; font-weight: bold;")
        layout.addWidget(fw_label)

        self.fw_status_labels: dict[str, QLabel] = {}
        for device_key, dev in self.firmware_registry.devices.items():
            tag = QLabel(f"{device_key}")
            if dev.all_present:
                tag.setStyleSheet(
                    "color: #4CAF50; background: #1B5E20; padding: 2px 8px; "
                    "border-radius: 3px; font-weight: bold;"
                )
            else:
                tag.setStyleSheet(
                    "color: #F44336; background: #B71C1C; padding: 2px 8px; "
                    "border-radius: 3px; font-weight: bold;"
                )
            self.fw_status_labels[device_key] = tag
            layout.addWidget(tag)

        layout.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(
            "color: white; background: #546E7A; padding: 4px 12px; border-radius: 3px;"
        )
        refresh_btn.clicked.connect(self._refresh_firmware)
        layout.addWidget(refresh_btn)

        return strip

    def _refresh_firmware(self) -> None:
        try:
            self.firmware_registry.load()
        except FileNotFoundError:
            QMessageBox.warning(
                self, "Firmware Manifest",
                f"Manifest not found:\n{settings.manifest_full_path}\n\n"
                "Place firmware binaries and manifest.yaml in the firmware/ folder.",
            )
            return

        for key, label in self.fw_status_labels.items():
            dev = self.firmware_registry.get(key)
            if dev:
                label.setText(f"{key}")
                if dev.all_present:
                    label.setStyleSheet(
                        "color: #4CAF50; background: #1B5E20; padding: 2px 8px; "
                        "border-radius: 3px; font-weight: bold;"
                    )
                else:
                    label.setStyleSheet(
                        "color: #F44336; background: #B71C1C; padding: 2px 8px; "
                        "border-radius: 3px; font-weight: bold;"
                    )

    @property
    def operator_id(self) -> str:
        return self.operator_input.text().strip()

    @property
    def work_order(self) -> str:
        return self.work_order_input.text().strip()

    def closeEvent(self, event) -> None:
        self.record_logger.close()
        self.serial_generator.close()
        super().closeEvent(event)
