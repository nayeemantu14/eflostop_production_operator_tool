"""Leak Sensor tab — single-step STM32WBA flash, UART log capture, BLE test."""

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
from ..devices.leak_sensor import LeakSensorDevice
from ..services.firmware_registry import FirmwareRegistry
from ..services.port_detector import find_any_serial_ports
from ..services.qr_generator import build_device_qr, generate_qr_bytes, prefixed_qr_payload
from ..services.record_logger import RecordLogger
from ..services.serial_generator import SerialGenerator
from ..workers.ble_scanner import BleScanner
from ..workers.functional_test import SensorTestWorker
from ..workers.serial_monitor import SerialMonitor
from ..workers.stm32_flasher import STM32AppReFlasher, STM32WBAFlasher
from .widgets.big_status import BigStatusBanner
from .widgets.firmware_panel import FirmwarePanel
from .widgets.log_viewer import LogViewer
from .widgets.question_dialog import ask_operator
from .widgets.qr_preview import QrPreview
from .widgets.step_list import StepListWidget


class LeakSensorTab(QWidget):
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
        self.device = LeakSensorDevice()
        self._flasher: STM32WBAFlasher | None = None
        self._prod_flasher: STM32AppReFlasher | None = None
        self._prod_app_path: Path | None = None
        self._serial_monitor: SerialMonitor | None = None
        self._test_worker: SensorTestWorker | None = None
        self._ble_scanner: BleScanner | None = None
        self._ble_scan_devices: list = []
        self._ble_scan_ready: bool = False
        self._tests_done: bool = False
        self._result: dict[str, Any] = {}

        self._build_ui()
        self._refresh_ports()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Left panel
        left = QVBoxLayout()

        # UART port selection (Tag-Connect)
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("UART Port (Tag-Connect):"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(200)
        port_row.addWidget(self.port_combo)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_ports)
        port_row.addWidget(self.refresh_btn)
        port_row.addStretch()
        left.addLayout(port_row)

        # Firmware panel
        self.fw_panel = FirmwarePanel("Leak Sensor")
        self._update_fw_panel()
        left.addWidget(self.fw_panel)

        # Expected FW version — operator-editable, verified against BLE adv mfg data
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
        ver_row.addWidget(QLabel("(verified against BLE manufacturer data)"))
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

        # Right panel
        right = QVBoxLayout()
        self.log_viewer = LogViewer()
        right.addWidget(self.log_viewer, stretch=2)

        self.qr_preview = QrPreview()
        right.addWidget(self.qr_preview, stretch=1)

        layout.addLayout(right, stretch=1)

    def _refresh_ports(self) -> None:
        self.port_combo.clear()
        ports = find_any_serial_ports()
        for p in ports:
            self.port_combo.addItem(f"{p.port} — {p.description}", p.port)
        if not ports:
            self.port_combo.addItem("No serial ports found", "")

    def _update_fw_panel(self) -> None:
        dev_fw = self.fw_registry.get("leak_sensor")
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
        main_win = self.window()
        if hasattr(main_win, "operator_id") and not main_win.operator_id:
            QMessageBox.warning(self, "Operator", "Enter your Operator ID before starting.")
            return

        dev_fw = self.fw_registry.get("leak_sensor")
        if not dev_fw:
            QMessageBox.warning(self, "Firmware", "Leak sensor firmware not configured.")
            return

        # Debug firmware is used for testing (UART log + parsing);
        # production firmware is flashed last before the unit passes.
        debug_path = dev_fw.effective_path("application_debug")
        prod_path = dev_fw.effective_path("application")
        if not debug_path or not debug_path.exists():
            QMessageBox.warning(self, "Firmware", "Debug firmware (application_debug) missing.")
            return
        if not prod_path or not prod_path.exists():
            QMessageBox.warning(self, "Firmware", "Production firmware (application) missing.")
            return

        self._prod_app_path = prod_path

        # Reset UI
        self.step_list.reset_all()
        self.log_viewer.clear()
        self.qr_preview.clear()
        self.status_banner.set_status("running")
        self.start_btn.setEnabled(False)
        self.abort_btn.setEnabled(True)
        self._result = {}

        # Step 1: Flash with DEBUG firmware for testing
        self._flasher = STM32WBAFlasher(
            cli_path=self.settings.stm32_cli_path,
            app_hex=debug_path,
        )
        self._flasher.log_message.connect(self._on_log)
        self._flasher.step_update.connect(self._on_step_update)
        self._flasher.finished_ok.connect(self._on_flash_done)
        self._flasher.finished_fail.connect(self._on_fail)
        self._flasher.start()

    def _on_flash_done(self, result: dict) -> None:
        self._result.update(result)
        self.log_viewer.append("Flash complete. Capturing UART log + scanning BLE...", "info")

        # Reset the concurrent-window coordination state.
        self._tests_done = False
        self._ble_scan_ready = False
        self._ble_scan_devices = []

        # Start the BLE scan NOW — concurrently with the UART capture — so the
        # scanner is already listening during the sensor's brief power-up
        # advertising burst. The leak sensor advertises in a short burst at boot
        # then sleeps in Stop1; a scan started only AFTER the UART capture (the
        # previous behaviour) would miss the burst entirely. Both run in parallel
        # from this post-flash reset; _maybe_proceed_after_scan() joins them.
        self._start_ble_scan()

        port = self.port_combo.currentData()
        if not port:
            self.log_viewer.append("No UART port selected — skipping log capture", "warn")
            self.step_list.update_step("capture_uart_log", "fail", "No UART port")
            self._tests_done = True
            self._maybe_proceed_after_scan()
            return

        self.step_list.update_step("capture_uart_log", "running", "Listening on UART...")

        self._serial_monitor = SerialMonitor(port=port, baud=115200)
        self._serial_monitor.line_received.connect(
            lambda line: self.log_viewer.append(f"[UART] {line}", "debug")
        )
        self._serial_monitor.error.connect(
            lambda e: self.log_viewer.append(f"Serial error: {e}", "error")
        )
        self._serial_monitor.start()

        QTimer.singleShot(
            self.settings.test.boot_log_timeout_seconds * 1000,
            self._on_uart_log_timeout,
        )

    def _on_uart_log_timeout(self) -> None:
        if self._serial_monitor:
            self._serial_monitor.stop()
            self._serial_monitor.wait(3000)
            uart_log = self._serial_monitor.captured_text
            self._serial_monitor = None

            lines = uart_log.splitlines()
            self.step_list.update_step("capture_uart_log", "pass", f"{len(lines)} lines")

            # Run sensor test worker
            self._test_worker = SensorTestWorker(
                uart_log=uart_log,
                uid=self._result.get("uid", ""),
                battery_min=self.settings.test.battery_voltage_min,
                battery_max=self.settings.test.battery_voltage_max,
            )
            self._test_worker.log_message.connect(self._on_log)
            self._test_worker.step_update.connect(self._on_step_update)
            self._test_worker.finished_ok.connect(self._on_tests_done)
            self._test_worker.finished_fail.connect(self._on_fail)
            self._test_worker.start()

    def _on_tests_done(self, result: dict) -> None:
        self._result.update(result)
        self._tests_done = True
        self._maybe_proceed_after_scan()

    def _start_ble_scan(self) -> None:
        self.step_list.update_step(
            "ble_scan", "running", "Scanning during boot advertising..."
        )

        self._ble_scanner = BleScanner(
            name_prefix=self.settings.ble_scan.sensor_name_prefix,
            timeout=self.settings.ble_scan.timeout_seconds,
        )
        self._ble_scanner.scan_complete.connect(self._on_ble_scan_complete)
        self._ble_scanner.error.connect(
            lambda e: self.log_viewer.append(f"BLE scan error: {e}", "error")
        )
        self._ble_scanner.start()

    def _on_ble_scan_complete(self, devices: list) -> None:
        """The concurrent BLE scan finished — stash its result, then continue
        once the UART test path has also finished (they ran in parallel)."""
        self._ble_scan_devices = devices
        self._ble_scan_ready = True
        self._maybe_proceed_after_scan()

    def _maybe_proceed_after_scan(self) -> None:
        """Advance only after BOTH the UART test path and the concurrent BLE
        scan have completed."""
        if self._tests_done and self._ble_scan_ready:
            self._on_ble_scan_done(self._ble_scan_devices)

    def _on_ble_scan_done(self, devices: list) -> None:
        if devices:
            dev = devices[0]
            self.step_list.update_step("ble_scan", "pass",
                                       f"Found: {dev['name']} ({dev['address']})")
            self._result["ble_mac"] = dev["address"]
            self.log_viewer.append(
                f"BLE device found: {dev['name']} addr={dev['address']} RSSI={dev['rssi']}",
                "pass",
            )
        else:
            self.step_list.update_step("ble_scan", "fail", "No BLE device found")
            self._on_fail("BLE advertising not detected")
            return

        # Verify FW version from BLE manufacturer data (ST company ID 0x0030).
        # Payload layout (after company ID): [leak_state, batt_pct, major, minor, patch]
        if not self._verify_ble_fw_version(devices[0]):
            return

        self._run_manual_checks()

    def _verify_ble_fw_version(self, dev: dict) -> bool:
        """Extract FW version from BLE mfg data and compare to operator-set expected.

        Returns True if version matches (or is missing — soft pass), False on
        explicit mismatch (test is failed before returning).
        """
        mfg = dev.get("manufacturer_data", {}).get(0x0030, b"")
        if len(mfg) < 5:
            self.step_list.update_step(
                "verify_fw_version", "fail",
                f"Mfg data too short ({len(mfg)} bytes, need 5)",
            )
            self._on_fail("BLE manufacturer data missing FW version")
            return False

        leak_state = mfg[0]
        batt_pct = mfg[1]
        fw_ver = f"{mfg[2]}.{mfg[3]}.{mfg[4]}"
        self._result["fw_version"] = fw_ver
        self._result["battery_pct_ble"] = batt_pct
        self._result["leak_state_ble"] = leak_state
        self.log_viewer.append(
            f"BLE mfg: FW v{fw_ver}, batt {batt_pct}%, leak={'wet' if leak_state else 'dry'}",
            "info",
        )

        expected = self.expected_ver_input.text().strip()
        if not expected:
            self.step_list.update_step(
                "verify_fw_version", "pass",
                f"Got v{fw_ver} (no expected set)",
            )
            return True

        if fw_ver == expected:
            self.step_list.update_step(
                "verify_fw_version", "pass", f"v{fw_ver} matches expected",
            )
            return True

        self.step_list.update_step(
            "verify_fw_version", "fail",
            f"Got v{fw_ver}, expected v{expected}",
        )
        self._on_fail(
            f"FW version mismatch: device reports v{fw_ver}, "
            f"expected v{expected}. Check that the correct .bin was flashed."
        )
        return False

    def _run_manual_checks(self) -> None:
        # LED check
        self.step_list.update_step("led_check", "running")
        if ask_operator("Is the LED on the Leak Sensor visible?", parent=self):
            self.step_list.update_step("led_check", "pass")
        else:
            self.step_list.update_step("led_check", "fail", "Operator: LED not visible")
            self._on_fail("LED check failed")
            return

        # Buzzer check
        self.step_list.update_step("buzzer_check", "running")
        if ask_operator("Did you hear the buzzer?", parent=self):
            self.step_list.update_step("buzzer_check", "pass")
        else:
            self.step_list.update_step("buzzer_check", "fail", "Operator: Buzzer not heard")
            self._on_fail("Buzzer check failed")
            return

        # Leak probe test
        self.step_list.update_step("leak_probe_test", "running")
        if ask_operator(
            "Short the leak detection probes with a wet finger or wire.\n"
            "Did the sensor detect a leak? (Check UART log for 'LEAK DETECTED')",
            parent=self,
        ):
            self.step_list.update_step("leak_probe_test", "pass")
        else:
            self.step_list.update_step("leak_probe_test", "fail", "Leak probe test failed")
            self._on_fail("Leak probe detection test failed")
            return

        # Re-flash with production firmware (low power, no debug)
        self._flash_production()

    def _flash_production(self) -> None:
        if not self._prod_app_path:
            self._on_fail("Production firmware path not set")
            return

        self.step_list.update_step("flash_production", "running", "Flashing production firmware...")
        self.log_viewer.append("Re-flashing with production firmware (low-power mode)...", "info")

        self._prod_flasher = STM32AppReFlasher(
            cli_path=self.settings.stm32_cli_path,
            app_bin=self._prod_app_path,
        )
        self._prod_flasher.log_message.connect(self._on_log)
        self._prod_flasher.step_update.connect(self._on_step_update)
        self._prod_flasher.finished_ok.connect(self._on_production_flash_done)
        self._prod_flasher.finished_fail.connect(self._on_fail)
        self._prod_flasher.start()

    def _on_production_flash_done(self, result: dict) -> None:
        self.step_list.update_step("flash_production", "pass", "Production firmware flashed")
        self.log_viewer.append("Production firmware flashed successfully", "pass")
        self._finish_pass()

    def _finish_pass(self) -> None:
        self.status_banner.set_status("pass")
        self.start_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)

        sn = self.serial_gen.next("sensor")
        main_win = self.window()
        operator = main_win.operator_id if hasattr(main_win, "operator_id") else ""
        work_order = main_win.work_order if hasattr(main_win, "work_order") else ""

        dev_fw = self.fw_registry.get("leak_sensor")
        fw_ver = self._result.get("fw_version") or (dev_fw.version if dev_fw else "")

        ble_mac = self._result.get("ble_mac", "")

        # QR is a plain-text query string the Watts app parses:
        #   id=<TAG>-<mac>&type=<type>&hw=<mcu>-<rev>&sw=v<fw>
        # The id keeps the device-type prefix and the MAC's colons.
        device_id = prefixed_qr_payload(self.device.device_type, ble_mac)
        qr_payload = build_device_qr(
            device_id, self.device.device_type,
            f"{self.device.mcu}-{self.settings.hw_revision}", fw_ver,
        )
        qr_bytes = generate_qr_bytes(qr_payload)
        # Caption shows SN / id / FW (mirrors the valve & hub labels).
        qr_info = (
            f"SN:  {sn}\n"
            f"ID:  {device_id}\n"
            f"FW:  {fw_ver}"
        )
        self.qr_preview.set_qr_png_bytes(qr_bytes, qr_info)

        self.record_logger.log({
            "device_type": "sensor",
            "serial_number": sn,
            "uid": self._result.get("uid", ""),
            "ble_mac": self._result.get("ble_mac", ""),
            "fw_version": fw_ver,
            "hw_revision": self.settings.hw_revision,
            "sku": self.settings.skus.sensor,
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

        main_win = self.window()
        operator = main_win.operator_id if hasattr(main_win, "operator_id") else ""
        self.record_logger.log({
            "device_type": "sensor",
            "serial_number": "",
            "uid": self._result.get("uid", ""),
            "result": "FAIL",
            "operator": operator,
            "notes": error,
        })

    def _on_abort(self) -> None:
        if self._flasher and self._flasher.isRunning():
            self._flasher.abort()
        if self._prod_flasher and self._prod_flasher.isRunning():
            self._prod_flasher.abort()
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
