"""Valve tab — 3-step STM32WB flash (FUS + BLE stack + app), BLE test."""

from __future__ import annotations

import re
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
from ..devices.valve import ValveDevice
from ..services.firmware_registry import FirmwareRegistry
from ..services.port_detector import find_stlink_vcp_ports, find_any_serial_ports
from ..services.qr_generator import build_device_qr, generate_qr_bytes, prefixed_qr_payload
from ..services.record_logger import RecordLogger
from ..services.serial_generator import SerialGenerator
from ..workers.ble_scanner import BleScanner, BleServiceReader
from ..workers.serial_monitor import SerialMonitor
from ..workers.stm32_flasher import STM32AppReFlasher, STM32WBFlasher
from .widgets.big_status import BigStatusBanner
from .widgets.firmware_panel import FirmwarePanel
from .widgets.log_viewer import LogViewer
from .widgets.question_dialog import ask_operator
from .widgets.qr_preview import QrPreview
from .widgets.step_list import StepListWidget

# DIS Firmware Revision String UUID
DIS_FW_REV_UUID = "00002a26-0000-1000-8000-00805f9b34fb"

# Regex for BD address printed by valve debug firmware (app_ble.c)
# Format: "Public Bluetooth Address: xx:xx:xx:xx:xx:xx"
_BD_ADDR_RE = re.compile(
    r"Public Bluetooth Address:\s*"
    r"([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:"
    r"[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})"
)


class ValveTab(QWidget):
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
        self.device = ValveDevice()
        self._flasher: STM32WBFlasher | None = None
        self._prod_flasher: STM32AppReFlasher | None = None
        self._ble_scanner: BleScanner | None = None
        self._ble_reader: BleServiceReader | None = None
        self._serial_monitor: SerialMonitor | None = None
        self._result: dict[str, Any] = {}
        # Set by ABORT, for continuations reached synchronously within the run
        # (e.g. after a modal operator dialog returns).
        self._aborted = False
        # Generation counter. Both START and ABORT bump it; every signal and
        # timer callback is bound to the id of the run that armed it, so a
        # callback still in flight from a superseded run is discarded instead of
        # driving the current one. The flag alone is not enough: START resets it,
        # which would re-arm the previous run's pending callbacks.
        self._run_id = 0
        # Latches the one-shot DIS result so a late error from the same reader
        # cannot re-enter the manual checks after a successful read.
        self._fw_read_handled = False

        self._build_ui()
        self._refresh_ports()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Left panel
        left = QVBoxLayout()

        # UART port selection (ST-Link VCP for boot log capture)
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("UART Port (ST-Link VCP):"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(200)
        port_row.addWidget(self.port_combo)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_ports)
        port_row.addWidget(self.refresh_btn)
        port_row.addStretch()
        left.addLayout(port_row)

        # Firmware panel
        self.fw_panel = FirmwarePanel("Valve")
        self._update_fw_panel()
        left.addWidget(self.fw_panel)

        # Expected FW version — operator-editable, verified against the FW
        # revision read from the device over BLE DIS.
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
        ver_row.addWidget(QLabel("(verified against BLE DIS firmware revision)"))
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
        # Prefer ST-Link VCP ports, fall back to all serial ports
        ports = find_stlink_vcp_ports()
        if not ports:
            ports = find_any_serial_ports()
        for p in ports:
            self.port_combo.addItem(f"{p.port} — {p.description}", p.port)
        # Add "None" option to skip UART capture
        self.port_combo.addItem("(Skip UART capture)", "")

    def _update_fw_panel(self) -> None:
        dev_fw = self.fw_registry.get("valve")
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

    def _bind(self, run: int, fn):
        """Wrap a signal/timer callback so deliveries from a stale run are dropped.

        Qt may already have a signal queued when the operator aborts, and a
        QTimer.singleShot cannot be cancelled, so filtering on arrival is the
        only airtight guard: a callback armed by run N does nothing once the
        current run is no longer N.
        """
        def _guarded(*args):
            if run != self._run_id:
                return
            fn(*args)
        return _guarded

    def _on_start(self) -> None:
        main_win = self.window()
        if hasattr(main_win, "operator_id") and not main_win.operator_id:
            QMessageBox.warning(self, "Operator", "Enter your Operator ID before starting.")
            return

        dev_fw = self.fw_registry.get("valve")
        if not dev_fw:
            QMessageBox.warning(self, "Firmware", "Valve firmware not configured in manifest.")
            return

        # Debug firmware is used for testing; production firmware for final flash
        debug_path = dev_fw.effective_path("application_debug")
        prod_path = dev_fw.effective_path("application")
        if not debug_path or not debug_path.exists():
            QMessageBox.warning(self, "Firmware", "Debug firmware (application_debug) missing.")
            return
        if not prod_path or not prod_path.exists():
            QMessageBox.warning(self, "Firmware", "Production firmware (application) missing.")
            return

        # Fail fast if no UART port is selected. Board identity is verified from
        # the BD address in the UART boot log, so without it the run is certain
        # to fail — but only ~90 s later, after a full flash cycle that leaves
        # the board on debug firmware. Catch it before anything is flashed.
        if not self.port_combo.currentData():
            QMessageBox.warning(
                self, "UART Port",
                "Select the ST-Link VCP port before starting.\n\n"
                "The board's identity is verified using the Bluetooth address "
                "printed on the UART boot log, so this run would fail after "
                "flashing.\n\n"
                "Press Refresh if the ST-Link was connected after the tool was "
                "launched.",
            )
            return

        # Refuse to start while the previous run's workers are still winding
        # down — the BLE radio in particular stays busy for several seconds
        # after an abort and would make this board fail spuriously.
        workers = (
            ("flasher", self._flasher),
            ("production flasher", self._prod_flasher),
            ("UART monitor", self._serial_monitor),
            ("BLE scanner", self._ble_scanner),
            ("BLE reader", self._ble_reader),
        )
        # The flashers own the ST-Link — starting a second one is never safe.
        blocking = [n for n, w in workers[:2] if w is not None and w.isRunning()]
        if blocking:
            QMessageBox.warning(
                self, "Busy",
                f"The {blocking[0]} is still running. Wait for it to finish, "
                f"then press START again.",
            )
            return
        # The UART/BLE workers have no cancel API and can hang indefinitely on a
        # wedged port or BLE session. Name them and let the operator proceed,
        # rather than locking the bench out with no way back except killing the
        # tool mid-batch.
        stalled = [n for n, w in workers[2:] if w is not None and w.isRunning()]
        if stalled:
            proceed = QMessageBox.question(
                self, "Previous run still stopping",
                f"Still running from the previous board: {', '.join(stalled)}.\n\n"
                f"Waiting a few seconds usually clears it. Starting now may make "
                f"this board fail the UART or Bluetooth steps.\n\nStart anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if proceed != QMessageBox.StandardButton.Yes:
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
        self._aborted = False
        self._fw_read_handled = False
        # New generation — anything still in flight from a previous run is now
        # stale and will be dropped by _bind().
        self._run_id += 1
        run = self._run_id

        # Resolve paths
        ble_stack = dev_fw.effective_path("ble_stack")
        fus_fw = dev_fw.effective_path("fus_firmware")
        fus_addr = dev_fw.files.get("fus_firmware")
        ble_addr = dev_fw.files.get("ble_stack")

        # Step 1: Flash with DEBUG firmware for testing
        self._flasher = STM32WBFlasher(
            cli_path=self.settings.stm32_cli_path,
            app_hex=debug_path,
            ble_stack_bin=ble_stack,
            fus_bin=fus_fw,
            fus_address=fus_addr.offset if fus_addr and fus_addr.offset else 0x080EC000,
            ble_stack_address=ble_addr.offset if ble_addr and ble_addr.offset else 0x080C7000,
            fus_min_version=dev_fw.fus_min_version or "1.2.0",
        )
        self._flasher.log_message.connect(self._on_log)
        self._flasher.step_update.connect(self._bind(run, self._on_step_update))
        self._flasher.finished_ok.connect(self._bind(run, self._on_flash_done))
        self._flasher.finished_fail.connect(self._bind(run, self._on_fail))
        self._flasher.start()

    def _on_flash_done(self, result: dict) -> None:
        if self._aborted:
            return
        run = self._run_id
        self._result.update(result)
        self.log_viewer.append("Flash complete. Waiting for device boot...", "info")

        # Start UART boot log capture if a port is selected
        uart_port = self.port_combo.currentData()
        if uart_port:
            self.step_list.update_step("capture_boot_log", "running", "Listening for boot log...")
            self._serial_monitor = SerialMonitor(port=uart_port, baud=115200)
            self._serial_monitor.line_received.connect(
                lambda line: self.log_viewer.append(f"[UART] {line}", "debug")
            )
            self._serial_monitor.error.connect(
                lambda e: self.log_viewer.append(f"Serial error: {e}", "error")
            )
            self._serial_monitor.start()

            # Wait for boot log capture then continue
            QTimer.singleShot(
                self.settings.test.boot_log_timeout_seconds * 1000,
                self._bind(run, self._on_boot_log_timeout),
            )
        else:
            # No UART port — mark the steps skipped, not passed. Identity cannot
            # be verified without the boot log, so this run will fail; showing a
            # green tick here would assert a check that did not happen.
            self.step_list.update_step("capture_boot_log", "skipped", "Skipped (no UART port)")
            self.step_list.update_step("parse_uart_bd_addr", "skipped", "Skipped")
            QTimer.singleShot(3000, self._bind(run, self._start_ble_scan))

    def _on_boot_log_timeout(self) -> None:
        if self._aborted:
            return
        boot_log = ""
        if self._serial_monitor:
            self._serial_monitor.stop()
            stopped = self._serial_monitor.wait(3000)
            boot_log = self._serial_monitor.captured_text
            if stopped:
                self._serial_monitor = None
            else:
                # Keep the reference: the thread still holds the COM port, and
                # dropping the last reference to a running QThread aborts the
                # process. Leaving it set also lets the busy gate see it.
                self.log_viewer.append(
                    "UART monitor did not stop — the COM port is still in use",
                    "warn",
                )

        line_count = len(boot_log.splitlines())
        self.step_list.update_step(
            "capture_boot_log", "pass", f"{line_count} lines captured"
        )

        # Parse BD address from UART boot log
        self.step_list.update_step("parse_uart_bd_addr", "running", "Parsing BD address...")
        uart_bd_addr = self._parse_bd_address(boot_log)
        if uart_bd_addr:
            self._result["uart_bd_addr"] = uart_bd_addr
            self.step_list.update_step("parse_uart_bd_addr", "pass", uart_bd_addr)
            self.log_viewer.append(f"UART BD address: {uart_bd_addr}", "info")
        else:
            self.step_list.update_step(
                "parse_uart_bd_addr", "fail",
                "BD address not found in boot log"
            )
            self.log_viewer.append(
                "Could not parse BD address from UART boot log", "warn"
            )
            # Continue to the scan so the log shows what was seen, but without a
            # BD address the identity cross-check cannot pass — _verify_bd_address
            # fails the run. Do NOT weaken that: the scan would otherwise match
            # any nearby "eFloStop" device and label this board with its address.

        self._start_ble_scan()

    @staticmethod
    def _parse_bd_address(boot_log: str) -> str:
        """Extract BD address from valve firmware UART boot log.

        Looks for: "Public Bluetooth Address: XX:XX:XX:XX:XX:XX"
        """
        match = _BD_ADDR_RE.search(boot_log)
        if match:
            return match.group(1).upper()
        return ""

    def _start_ble_scan(self) -> None:
        if self._aborted:
            return
        # Prefer scanning by BD address from UART boot log (exact match).
        # STM32WB does not include the GAP device name in adv packets by
        # default, so name-prefix scanning typically fails.
        target_mac = self._result.get("uart_bd_addr", "")
        if target_mac:
            self.step_list.update_step(
                "ble_scan", "running", f"Scanning for {target_mac}..."
            )
        else:
            self.step_list.update_step(
                "ble_scan", "running", "Scanning for valve advertisements..."
            )

        self._ble_scanner = BleScanner(
            name_prefix=self.settings.ble_scan.valve_name_prefix,
            target_mac=target_mac,
            timeout=self.settings.ble_scan.timeout_seconds,
        )
        self._ble_scanner.scan_started.connect(
            lambda s: self.log_viewer.append(f"BLE scan starting: {s}", "info")
        )
        self._ble_scanner.observed.connect(
            lambda info: self.log_viewer.append(f"[BLE scan] {info}", "info")
        )
        self._ble_scanner.scan_finished.connect(
            lambda n: self.log_viewer.append(
                f"BLE scan finished: observed {n} unique device(s)", "info"
            )
        )
        self._ble_scanner.scan_complete.connect(
            self._bind(self._run_id, self._on_ble_scan_done)
        )
        self._ble_scanner.error.connect(
            lambda e: self.log_viewer.append(f"BLE scan error: {e}", "error")
        )
        self._ble_scanner.start()

    def _on_ble_scan_done(self, devices: list) -> None:
        if self._aborted:
            return
        if devices:
            dev = devices[0]
            self.step_list.update_step("ble_scan", "pass",
                                       f"Found: {dev['name']} ({dev['address']})")
            self._result["ble_mac"] = dev["address"]
            self.log_viewer.append(
                f"BLE device found: {dev['name']} addr={dev['address']} RSSI={dev['rssi']}",
                "pass",
            )
            self.step_list.update_step("read_ble_addr", "pass", dev["address"])

            # Cross-verify BD address from UART vs BLE advertisement
            if not self._verify_bd_address(dev["address"]):
                return  # Mismatch — _on_fail already called

            # Read FW version via DIS
            self._read_fw_version(dev["address"])
        else:
            self.step_list.update_step("ble_scan", "fail", "No BLE device found")
            self._on_fail("BLE advertising not detected after flash")

    def _verify_bd_address(self, ble_addr: str) -> bool:
        """Cross-verify BD address from UART boot log against BLE scan result.

        Returns True if verified, False if unverified or mismatched (fail
        already reported).

        Without a UART BD address the BLE scan had no target and matched on the
        name prefix instead — which also matches other valve boards and the hub,
        and the first advertisement seen wins. The scanned address could then
        belong to a different board and would be printed on this board's label,
        so an unverifiable identity is a hard failure, not a skip.
        """
        uart_bd_addr = self._result.get("uart_bd_addr", "")
        if not uart_bd_addr:
            self.step_list.update_step(
                "verify_bd_address", "fail",
                "No UART BD address — identity unverified",
            )
            self._on_fail(
                "Cannot verify board identity: no BD address was captured over "
                "UART, so the BLE address may belong to a different board. "
                "Select the ST-Link VCP port (not '(Skip UART capture)') and "
                "re-run."
            )
            return False

        # Normalize both addresses to uppercase for comparison
        ble_normalized = ble_addr.upper().replace("-", ":")
        uart_normalized = uart_bd_addr.upper().replace("-", ":")

        if ble_normalized == uart_normalized:
            self.step_list.update_step(
                "verify_bd_address", "pass",
                f"Match: {uart_normalized}"
            )
            self.log_viewer.append(
                f"BD address verified: UART={uart_normalized} == BLE={ble_normalized}",
                "pass",
            )
            return True
        else:
            self.step_list.update_step(
                "verify_bd_address", "fail",
                f"MISMATCH: UART={uart_normalized} vs BLE={ble_normalized}"
            )
            self._on_fail(
                f"BD address mismatch! UART reports {uart_normalized} "
                f"but BLE scan found {ble_normalized}"
            )
            return False

    def _read_fw_version(self, address: str) -> None:
        self.step_list.update_step("read_fw_version", "running", "Connecting via BLE...")

        self._ble_reader = BleServiceReader(
            address=address,
            characteristic_uuid=DIS_FW_REV_UUID,
            timeout=10.0,
        )
        run = self._run_id
        self._ble_reader.value_read.connect(self._bind(run, self._on_fw_version_read))
        self._ble_reader.error.connect(self._bind(run, self._on_fw_version_error))
        self._ble_reader.start()

    def _on_fw_version_read(self, uuid: str, data: bytes) -> None:
        if self._aborted or self._fw_read_handled:
            return
        self._fw_read_handled = True
        fw_ver = data.decode("utf-8", errors="replace").strip()
        self._result["fw_version"] = fw_ver
        self.step_list.update_step("read_fw_version", "pass", f"v{fw_ver}")
        self.log_viewer.append(f"Firmware version (DIS): {fw_ver}", "info")
        if not self._verify_fw_version(fw_ver):
            return
        self._run_manual_checks()

    def _on_fw_version_error(self, error: str) -> None:
        # A BleServiceReader can emit error() *after* a successful value_read()
        # — a failure while disconnecting is common on STM32WB. Without this
        # latch that late error would wipe the version already read and re-enter
        # the manual checks, stacking a second set of operator dialogs and a
        # second production flash.
        if self._aborted or self._fw_read_handled:
            if self._fw_read_handled:
                self.log_viewer.append(
                    f"BLE disconnect reported after version read: {error}", "debug"
                )
            return
        self._fw_read_handled = True
        self.log_viewer.append(f"DIS read failed: {error}", "warn")
        self.step_list.update_step("read_fw_version", "fail", error)
        # Continue anyway — FW version from DIS is nice-to-have. Leave the
        # version EMPTY rather than substituting the manifest version: the
        # manifest can be stale, and the value flows into the printed QR (sw=)
        # and the production record, where it would assert a firmware revision
        # that was never read from the board.
        self._result["fw_version"] = ""
        # No device-reported version to verify against — skip the check
        # (mirrors how a missing UART BD address is treated as a soft skip).
        self.step_list.update_step(
            "verify_fw_version", "skipped", "Skipped (no DIS version)"
        )
        self._run_manual_checks()

    def _verify_fw_version(self, fw_ver: str) -> bool:
        """Compare the DIS-reported FW version to the operator-set expected.

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

    def _run_manual_checks(self) -> None:
        if self._aborted:
            return
        # LED check
        self.step_list.update_step("led_check", "running")
        if ask_operator("Is the LED on the Valve board visible?", parent=self):
            self.step_list.update_step("led_check", "pass")
        else:
            self.step_list.update_step("led_check", "fail", "Operator: LED not visible")
            self._on_fail("LED check failed")
            return

        # Servo check
        self.step_list.update_step("servo_check", "running")
        if ask_operator(
            "Press the button on the valve.\nDid the servo actuate (valve moved)?",
            parent=self,
        ):
            self.step_list.update_step("servo_check", "pass")
        else:
            self.step_list.update_step("servo_check", "fail", "Operator: Servo did not move")
            self._on_fail("Servo actuation check failed")
            return

        # Buzzer check
        self.step_list.update_step("buzzer_check", "running")
        if ask_operator("Did you hear the buzzer?", parent=self):
            self.step_list.update_step("buzzer_check", "pass")
        else:
            self.step_list.update_step("buzzer_check", "fail", "Operator: Buzzer not heard")
            self._on_fail("Buzzer check failed")
            return

        # Re-flash with production firmware (low power, no debug)
        self._flash_production()

    def _flash_production(self) -> None:
        if self._aborted:
            return
        self.step_list.update_step("flash_production", "running", "Flashing production firmware...")
        self.log_viewer.append("Re-flashing with production firmware (low-power mode)...", "info")

        self._prod_flasher = STM32AppReFlasher(
            cli_path=self.settings.stm32_cli_path,
            app_bin=self._prod_app_path,
        )
        run = self._run_id
        self._prod_flasher.log_message.connect(self._on_log)
        self._prod_flasher.step_update.connect(self._bind(run, self._on_step_update))
        self._prod_flasher.finished_ok.connect(
            self._bind(run, self._on_production_flash_done)
        )
        self._prod_flasher.finished_fail.connect(self._bind(run, self._on_fail))
        self._prod_flasher.start()

    def _on_production_flash_done(self, result: dict) -> None:
        if self._aborted:
            return
        self.step_list.update_step("flash_production", "pass", "Production firmware flashed")
        self.log_viewer.append("Production firmware flashed successfully", "pass")
        self._finish_pass()

    def _finish_pass(self) -> None:
        if self._aborted:
            return
        self.status_banner.set_status("pass")
        self.start_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)

        sn = self.serial_gen.next("valve")
        main_win = self.window()
        operator = main_win.operator_id if hasattr(main_win, "operator_id") else ""
        work_order = main_win.work_order if hasattr(main_win, "work_order") else ""

        fw_ver = self._result.get("fw_version", "")
        ble_mac = self._result.get("ble_mac", "")

        # QR is a plain-text query string the Watts app parses:
        #   id=<TAG>-<mac>&type=<type>&hw=<mcu>-<rev>&sw=v<fw>
        device_id = prefixed_qr_payload(self.device.device_type, ble_mac)
        qr_payload = build_device_qr(
            device_id, self.device.device_type,
            f"{self.device.mcu}-{self.settings.hw_revision}", fw_ver,
        )
        qr_bytes = generate_qr_bytes(qr_payload)
        qr_info = (
            f"SN:  {sn}\n"
            f"ID:  {device_id}\n"
            f"FW:  {fw_ver}"
        )
        self.qr_preview.set_qr_png_bytes(qr_bytes, qr_info)

        self.record_logger.log({
            "device_type": "valve",
            "serial_number": sn,
            "uid": self._result.get("uid", ""),
            "ble_mac": self._result.get("ble_mac", ""),
            "fw_version": fw_ver,
            "hw_revision": self.settings.hw_revision,
            "sku": self.settings.skus.valve,
            "operator": operator,
            "work_order": work_order,
            "result": "PASS",
            "qr_payload": qr_payload,
        })

        self.log_viewer.append(f"PASS — SN: {sn}", "pass")

    def _on_fail(self, error: str) -> None:
        if self._aborted:
            # The abort is already reported and recorded — don't overwrite the
            # ABORTED banner with FAIL or log a second record for the same run.
            self.log_viewer.append(f"Stopped after abort: {error}", "warn")
            return
        self.status_banner.set_status("fail")
        self.log_viewer.append(f"FAIL: {error}", "fail")
        self.start_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)

        main_win = self.window()
        operator = main_win.operator_id if hasattr(main_win, "operator_id") else ""
        self.record_logger.log({
            "device_type": "valve",
            "serial_number": "",
            "uid": self._result.get("uid", ""),
            "result": "FAIL",
            "operator": operator,
            "notes": error,
        })

    def _on_abort(self) -> None:
        # Set first: the run advances through QTimer and worker callbacks that
        # stopping the threads cannot cancel. Every continuation checks this and
        # returns, so an aborted run can no longer reach _finish_pass() and
        # award a serial number and QR.
        self._aborted = True
        # Retire this generation so any signal already queued, and the
        # uncancellable boot-log timer, are dropped on arrival by _bind() —
        # including after the operator starts the next board.
        self._run_id += 1

        if self._flasher and self._flasher.isRunning():
            self._flasher.abort()
        if self._prod_flasher and self._prod_flasher.isRunning():
            self._prod_flasher.abort()
        if self._serial_monitor and self._serial_monitor.isRunning():
            self._serial_monitor.stop()

        self.status_banner.set_status("fail", "ABORTED")
        self.log_viewer.append("Aborted by operator", "warn")
        self.start_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)

        # Record the aborted unit — _on_fail is suppressed after an abort, so
        # this is the single record for the run.
        main_win = self.window()
        operator = main_win.operator_id if hasattr(main_win, "operator_id") else ""
        self.record_logger.log({
            "device_type": "valve",
            "serial_number": "",
            "uid": self._result.get("uid", ""),
            "result": "FAIL",
            "operator": operator,
            "notes": "Aborted by operator",
        })

    def _on_log(self, message: str, level: str) -> None:
        self.log_viewer.append(message, level)

    def _on_step_update(self, step_id: str, status: str, detail: str) -> None:
        self.step_list.update_step(step_id, status, detail)
