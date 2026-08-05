"""WiFi Hub tab — flash ESP32-S3, capture boot log, run tests."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config.settings import AppSettings
from ..devices.wifi_hub import WiFiHubDevice
from ..services.firmware_registry import FirmwareRegistry
from ..services.port_detector import find_cp210x_ports
from ..services.qr_generator import build_device_qr, generate_qr_bytes, prefixed_qr_payload
from ..services.record_logger import RecordLogger
from ..services.serial_generator import SerialGenerator
from ..workers.ble_scanner import BleScanner
from ..workers.esp_flasher import EspFlasher
from ..workers.functional_test import HubTestWorker
from ..workers.serial_monitor import SerialMonitor
from .widgets.big_status import BigStatusBanner
from .widgets.firmware_panel import FirmwarePanel
from .widgets.log_viewer import LogViewer
from .widgets.question_dialog import ask_operator
from .widgets.qr_preview import QrPreview
from .widgets.step_list import StepListWidget


class WiFiHubTab(QWidget):
    def __init__(
        self,
        fw_registry: FirmwareRegistry,
        serial_gen: SerialGenerator,
        record_logger: RecordLogger,
        settings: AppSettings,
        parent=None,
    ):
        super().__init__(parent)
        self.fw_registry = fw_registry
        self.serial_gen = serial_gen
        self.record_logger = record_logger
        self.settings = settings
        self.device = WiFiHubDevice()
        self._worker: EspFlasher | None = None
        self._test_worker: HubTestWorker | None = None
        self._serial_monitor: SerialMonitor | None = None
        self._ble_scanner: BleScanner | None = None
        self._result: dict[str, Any] = {}

        self._build_ui()
        self._refresh_ports()


    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Left panel: steps + controls
        left = QVBoxLayout()

        # Port selection
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Serial Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(200)
        port_row.addWidget(self.port_combo)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_ports)
        port_row.addWidget(self.refresh_btn)

        self.ble_scan_btn = QPushButton("BLE Scan")
        self.ble_scan_btn.setToolTip("Scan for nearby BLE devices (5 seconds)")
        self.ble_scan_btn.setStyleSheet(
            "QPushButton { background-color: #37474F; color: white; padding: 4px 12px; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #546E7A; }"
            "QPushButton:disabled { background-color: #90A4AE; }"
        )
        self.ble_scan_btn.clicked.connect(self._on_ble_scan)
        port_row.addWidget(self.ble_scan_btn)
        port_row.addStretch()
        left.addLayout(port_row)

        # Firmware panel
        self.fw_panel = FirmwarePanel("WiFi Hub")
        self._update_fw_panel()
        left.addWidget(self.fw_panel)

        # Expected FW version — operator-editable, verified against the version
        # parsed from the boot log.
        ver_row = QHBoxLayout()
        ver_label = QLabel("Expected FW version:")
        ver_font = QFont()
        ver_font.setBold(True)
        ver_label.setFont(ver_font)
        ver_row.addWidget(ver_label)
        self.expected_ver_input = QLineEdit()
        self.expected_ver_input.setMaximumWidth(120)
        self.expected_ver_input.setPlaceholderText("X.Y.Z")
        # No fixed default — pre-filling a manifest version misleads the operator
        # when the manifest is out of date. They enter the version expected for
        # this batch; blank = advisory (FW is shown but not gated).
        ver_row.addWidget(self.expected_ver_input)
        ver_row.addWidget(QLabel("(verified against boot log)"))
        ver_row.addStretch()
        left.addLayout(ver_row)

        # Status banner
        self.status_banner = BigStatusBanner()
        left.addWidget(self.status_banner)

        # Step list
        self.step_list = StepListWidget()
        steps = [{"id": s.id, "name": s.name} for s in self.device.all_steps()]
        self.step_list.set_steps(steps)
        left.addWidget(self.step_list, stretch=1)

        # Control buttons
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("START")
        self.start_btn.setFixedHeight(50)
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; font-size: 16px; "
            "font-weight: bold; border-radius: 6px; }"
            "QPushButton:hover { background-color: #1976D2; }"
            "QPushButton:disabled { background-color: #90A4AE; }"
        )
        self.start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self.start_btn, stretch=2)

        self.abort_btn = QPushButton("ABORT")
        self.abort_btn.setFixedHeight(50)
        self.abort_btn.setEnabled(False)
        self.abort_btn.setStyleSheet(
            "QPushButton { background-color: #C62828; color: white; font-size: 16px; "
            "font-weight: bold; border-radius: 6px; }"
            "QPushButton:disabled { background-color: #90A4AE; }"
        )
        self.abort_btn.clicked.connect(self._on_abort)
        btn_row.addWidget(self.abort_btn, stretch=1)
        left.addLayout(btn_row)

        layout.addLayout(left, stretch=2)

        # Right panel: log + QR
        right = QVBoxLayout()
        self.log_viewer = LogViewer()
        right.addWidget(self.log_viewer, stretch=2)

        self.qr_preview = QrPreview()
        right.addWidget(self.qr_preview, stretch=1)

        layout.addLayout(right, stretch=1)

    def _refresh_ports(self) -> None:
        self.port_combo.clear()
        ports = find_cp210x_ports()
        for p in ports:
            self.port_combo.addItem(f"{p.port} — {p.description}", p.port)
        if not ports:
            self.port_combo.addItem("No CP210x ports found", "")

    def _update_fw_panel(self) -> None:
        dev_fw = self.fw_registry.get("wifi_hub")
        if dev_fw:
            files_info = {}
            for role, fw_file in dev_fw.files.items():
                files_info[role] = {
                    "path": str(fw_file.path),
                    "exists": fw_file.exists,
                    "sha256": fw_file.sha256,
                    "override": str(dev_fw.overrides.get(role, "")),
                }
            self.fw_panel.set_firmware_info(dev_fw.version, files_info)

    def _on_start(self) -> None:
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "No Port", "Select a serial port first.")
            return

        # Check operator ID from parent
        main_win = self.window()
        if hasattr(main_win, "operator_id") and not main_win.operator_id:
            QMessageBox.warning(self, "Operator", "Enter your Operator ID before starting.")
            return

        dev_fw = self.fw_registry.get("wifi_hub")
        if not dev_fw or not dev_fw.all_present:
            QMessageBox.warning(self, "Firmware", "Firmware files missing. Check firmware folder.")
            return

        # Reset UI
        self.step_list.reset_all()
        self.log_viewer.clear()
        self.qr_preview.clear()
        self.status_banner.set_status("running")
        self.start_btn.setEnabled(False)
        self.abort_btn.setEnabled(True)
        self._result = {}

        # Build flash file list
        flash_files: list[tuple[int, Path]] = []
        for role, fw_file in dev_fw.files.items():
            effective = dev_fw.effective_path(role)
            if effective and fw_file.offset is not None:
                flash_files.append((fw_file.offset, effective))

        flash_files.sort(key=lambda x: x[0])

        # Start flash worker
        self._worker = EspFlasher(
            port=port,
            firmware_files=flash_files,
            baud=self.settings.flash.esp_baud,
            flash_size=dev_fw.flash_size or "detect",
        )
        self._worker.log_message.connect(self._on_log)
        self._worker.step_update.connect(self._on_step_update)
        self._worker.progress.connect(lambda v: None)
        self._worker.finished_ok.connect(self._on_flash_done)
        self._worker.finished_fail.connect(self._on_fail)
        self._worker.start()

    def _on_flash_done(self, result: dict) -> None:
        self._result.update(result)
        self.log_viewer.append("Flash complete. Starting boot log capture...", "info")

        # Start serial monitor to capture boot log
        port = self.port_combo.currentData()
        self.step_list.update_step("capture_boot_log", "running", "Listening...")

        self._serial_monitor = SerialMonitor(port=port, baud=115200)
        self._serial_monitor.line_received.connect(
            lambda line: self.log_viewer.append(f"[UART] {line}", "debug")
        )
        self._serial_monitor.error.connect(
            lambda e: self.log_viewer.append(f"Serial error: {e}", "error")
        )
        self._serial_monitor.start()

        # Wait for boot log timeout then continue
        QTimer.singleShot(
            self.settings.test.boot_log_timeout_seconds * 1000,
            self._on_boot_log_timeout,
        )

    def _on_boot_log_timeout(self) -> None:
        if self._serial_monitor:
            self._serial_monitor.stop()
            self._serial_monitor.wait(3000)
            boot_log = self._serial_monitor.captured_text
            self._serial_monitor = None

            self.step_list.update_step("capture_boot_log", "pass",
                                       f"{len(boot_log.splitlines())} lines")

            # Run test worker
            self._test_worker = HubTestWorker(
                boot_log=boot_log,
                base_mac=self._result.get("base_mac", ""),
                ble_scan_timeout=self.settings.ble_scan.timeout_seconds,
            )
            self._test_worker.log_message.connect(self._on_log)
            self._test_worker.step_update.connect(self._on_step_update)
            self._test_worker.finished_ok.connect(self._on_tests_done)
            self._test_worker.finished_fail.connect(self._on_fail)
            self._test_worker.start()

    def _on_tests_done(self, result: dict) -> None:
        self._result.update(result)

        # Verify FW version (parsed from the boot log) against the operator's
        # expected value before proceeding.
        if not self._verify_fw_version(self._result.get("fw_version", "")):
            return

        # Hub is a BLE central (doesn't advertise) — skip BLE scan.
        # NimBLE init check already validated BLE hardware.

        # Manual LED check
        self.step_list.update_step("led_check", "running")
        led_ok = ask_operator("Is the LED on the WiFi Hub blinking?", parent=self)
        if led_ok:
            self.step_list.update_step("led_check", "pass")
        else:
            self.step_list.update_step("led_check", "fail", "Operator: LED not visible")
            self._on_fail("LED check failed")
            return

        self._finish_pass()

    def _verify_fw_version(self, fw_ver: str) -> bool:
        """Compare the boot-log FW version to the operator-set expected.

        Mirrors LeakSensorTab._verify_ble_fw_version: exact, case-sensitive
        match; blocking on mismatch. Returns True to continue, False on
        mismatch (the test is failed before returning).
        """
        expected = self.expected_ver_input.text().strip()
        if not expected:
            self.step_list.update_step(
                "verify_fw_version", "pass",
                f"Got v{fw_ver} (no expected set)" if fw_ver else "No expected set",
            )
            return True

        if fw_ver and fw_ver == expected:
            self.step_list.update_step(
                "verify_fw_version", "pass", f"v{fw_ver} matches expected",
            )
            return True

        self.step_list.update_step(
            "verify_fw_version", "fail",
            f"Got v{fw_ver or '?'}, expected v{expected}",
        )
        self._on_fail(
            f"FW version mismatch: device reports v{fw_ver or '(none)'}, "
            f"expected v{expected}. Check that the correct firmware was flashed."
        )
        return False

    def _finish_pass(self) -> None:
        self.status_banner.set_status("pass")
        self.start_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)

        # Generate serial number and QR
        sn = self.serial_gen.next("hub")
        main_win = self.window()
        operator = main_win.operator_id if hasattr(main_win, "operator_id") else ""
        work_order = main_win.work_order if hasattr(main_win, "work_order") else ""

        dev_fw = self.fw_registry.get("wifi_hub")
        fw_ver = self._result.get("fw_version", dev_fw.version if dev_fw else "")

        gateway_id = self._result.get("gateway_id", "")
        wifi_mac = self._result.get("wifi_mac", "")
        short_id = gateway_id[-4:] if len(gateway_id) >= 4 else ""
        ap_ssid = f"WiFi-Hub-{short_id}" if short_id else ""

        # QR is a plain-text query string the Watts app parses:
        #   id=GW-<hex>&type=hub&hw=<mcu>-<rev>&sw=v<fw>
        # The hub id is the Gateway ID (Azure identity), which already carries
        # the "GW-" tag (idempotent — never doubled).
        device_id = prefixed_qr_payload(self.device.device_type, gateway_id)
        qr_payload = build_device_qr(
            device_id, self.device.device_type,
            f"{self.device.mcu}-{self.settings.hw_revision}", fw_ver,
        )
        qr_bytes = generate_qr_bytes(qr_payload)
        qr_info = (
            f"SN:   {sn}\n"
            f"ID:   {device_id}\n"
            f"WiFi: {ap_ssid}\n"
            f"FW:   {fw_ver}"
        )
        self.qr_preview.set_qr_png_bytes(qr_bytes, qr_info)

        # Log record
        self.record_logger.log({
            "device_type": "hub",
            "serial_number": sn,
            "uid": self._result.get("base_mac", ""),
            "gateway_id": gateway_id,
            "wifi_mac": wifi_mac,
            "fw_version": fw_ver,
            "hw_revision": self.settings.hw_revision,
            "sku": self.settings.skus.hub,
            "operator": operator,
            "work_order": work_order,
            "result": "PASS",
            "qr_payload": qr_payload,
        })


        self.log_viewer.append(f"PASS — SN: {sn}", "pass")

    def _on_fail(self, error: str) -> None:
        self.status_banner.set_status("fail")
        self.log_viewer.append(f"FAIL: {error}", "fail")
        self.start_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)

        # Log failure record
        main_win = self.window()
        operator = main_win.operator_id if hasattr(main_win, "operator_id") else ""
        self.record_logger.log({
            "device_type": "hub",
            "serial_number": "",
            "uid": self._result.get("base_mac", ""),
            "result": "FAIL",
            "operator": operator,
            "notes": error,
        })

    def _on_abort(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.abort()
        if self._serial_monitor and self._serial_monitor.isRunning():
            self._serial_monitor.stop()
        if self._test_worker and self._test_worker.isRunning():
            self._test_worker.abort()

        self.status_banner.set_status("fail", "ABORTED")
        self.log_viewer.append("Aborted by operator", "warn")
        self.start_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)

    def _on_log(self, message: str, level: str) -> None:
        self.log_viewer.append(message, level)

    def _on_step_update(self, step_id: str, status: str, detail: str) -> None:
        self.step_list.update_step(step_id, status, detail)

    # --- BLE Scan utility --------------------------------------------------

    def _on_ble_scan(self) -> None:
        self.ble_scan_btn.setEnabled(False)
        self.ble_scan_btn.setText("Scanning...")
        self.log_viewer.append("BLE scan started (5 seconds)...", "info")

        self._ble_scanner = BleScanner(name_prefix="", target_mac="", timeout=5.0)
        self._ble_scanner.observed.connect(self._on_ble_observed)
        self._ble_scanner.scan_finished.connect(self._on_ble_scan_done)
        self._ble_scanner.error.connect(
            lambda e: self.log_viewer.append(f"BLE error: {e}", "error")
        )
        self._ble_scanner.start()

    def _on_ble_observed(self, info: str) -> None:
        self.log_viewer.append(f"[BLE] {info}", "debug")

    def _on_ble_scan_done(self, total: int) -> None:
        self.log_viewer.append(f"BLE scan complete — {total} devices found", "info")
        self.ble_scan_btn.setText("BLE Scan")
        self.ble_scan_btn.setEnabled(True)
        self._ble_scanner = None
