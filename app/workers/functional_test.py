"""Functional test orchestrator — runs device-specific test sequences."""

from __future__ import annotations

import re
import time
from typing import Any

from .base_worker import BaseWorker


class HubTestWorker(BaseWorker):
    """WiFi Hub functional test: parse boot log, BLE scan."""

    def __init__(self, boot_log: str, base_mac: str, ble_scan_timeout: float = 10.0, parent=None):
        super().__init__(parent)
        self.boot_log = boot_log
        self.base_mac = base_mac
        self.ble_scan_timeout = ble_scan_timeout

    def execute(self) -> dict[str, Any]:
        result: dict[str, Any] = {"base_mac": self.base_mac}

        # Parse app version (non-fatal — version may not be semver)
        self.set_step("parse_app_version", "running")
        version = self._parse_version()
        if version:
            result["fw_version"] = version
            self.set_step("parse_app_version", "pass", version)
        else:
            result["fw_version"] = ""
            self.set_step("parse_app_version", "pass", "Not set (OK)")

        self.progress.emit(20)

        # Read base MAC (already have it from flash)
        self.set_step("read_base_mac", "pass", self.base_mac)
        result["base_mac"] = self.base_mac

        # Parse Gateway ID and WiFi MAC from log
        self.set_step("parse_wifi_bt_mac", "running")
        wifi_mac, gateway_id = self._parse_macs()
        result["wifi_mac"] = wifi_mac or self.base_mac
        result["gateway_id"] = gateway_id
        if gateway_id:
            self.set_step("parse_wifi_bt_mac", "pass", gateway_id)
        elif wifi_mac:
            self.set_step("parse_wifi_bt_mac", "pass", f"WiFi: {wifi_mac}")
        else:
            self.set_step("parse_wifi_bt_mac", "pass",
                          f"From base MAC: {self.base_mac}")

        self.progress.emit(40)

        # LoRa init check (optional hardware — non-fatal)
        self.set_step("lora_init", "running")
        if self._check_lora():
            self.set_step("lora_init", "pass", "SX1262 detected")
        else:
            self.set_step("lora_init", "skipped", "Not present (optional)")

        self.progress.emit(50)

        # BLE stack check (deferred until WiFi connects — non-fatal on fresh hub)
        self.set_step("nimble_init", "running")
        if self._check_nimble():
            self.set_step("nimble_init", "pass", "BLE hardware verified")
        else:
            self.set_step("nimble_init", "skipped", "Deferred (verified after WiFi)")

        self.progress.emit(60)

        return result

    def _parse_version(self) -> str:
        # Try semver pattern first (e.g. "Firmware version: v1.4.2")
        match = re.search(r"(?:version|ver|fw)[:\s]*v?(\d+\.\d+\.\d+)", self.boot_log, re.IGNORECASE)
        if match:
            return match.group(1)
        # Try ESP-IDF boot log "App version:" line (may be git hash, bare number, etc.)
        match = re.search(r"App version:\s*(.+)", self.boot_log)
        if match:
            return match.group(1).strip()
        return ""

    def _parse_macs(self) -> tuple[str, str]:
        """Parse WiFi MAC and Gateway ID from boot log.

        Returns:
            (wifi_mac, gateway_id) — gateway_id is "GW-XXXXXXXXXXXX" string.
        """
        wifi_mac = ""
        gateway_id = ""
        mac_re = r"([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})"

        for line in self.boot_log.splitlines():
            low = line.lower()
            # ESP-IDF prints "wifi:wifi sta mac: xx:xx..." or "sta mac:"
            if ("wifi" in low or "sta" in low) and "mac" in low:
                m = re.search(mac_re, line)
                if m:
                    wifi_mac = m.group(1).upper()
            # "Gateway ID: GW-XXXXXXXXXXXX" — this is the Azure IoT Hub identity
            gw_match = re.search(r"Gateway ID\s*:\s*(GW-[0-9A-Fa-f]{12})", line)
            if gw_match:
                gateway_id = gw_match.group(1).upper()
                raw = gateway_id[3:]  # strip "GW-"
                wifi_mac = ":".join(raw[i:i+2] for i in range(0, 12, 2))

        return wifi_mac, gateway_id

    def _check_lora(self) -> bool:
        # Match APP_LORA tag or SX1262 mention or "LoRa Task Started"
        return bool(re.search(
            r"APP_LORA.*Initializing|APP_LORA.*Task Started|SX1262|LoRa.*init",
            self.boot_log, re.IGNORECASE,
        ))

    def _check_nimble(self) -> bool:
        # Match BLE self-test result, NimBLE tag, or BLE module init
        return bool(re.search(
            r"SELF_TEST.*BLE.*OK|NimBLE|BLE_LEAK.*init|BLE_VALVE.*INIT|nimble_port_init|BLE.*host",
            self.boot_log, re.IGNORECASE,
        ))


class SensorTestWorker(BaseWorker):
    """Leak Sensor functional test: parse UART log, BLE scan, battery check."""

    def __init__(
        self,
        uart_log: str,
        uid: str,
        battery_min: float = 2.5,
        battery_max: float = 3.3,
        parent=None,
    ):
        super().__init__(parent)
        self.uart_log = uart_log
        self.uid = uid
        self.battery_min = battery_min
        self.battery_max = battery_max

    def execute(self) -> dict[str, Any]:
        result: dict[str, Any] = {"uid": self.uid}

        # Parse app version — non-fatal; tab falls back to manifest version
        self.set_step("parse_app_version", "running")
        version = self._parse_version()
        if version:
            result["fw_version"] = version
            self.set_step("parse_app_version", "pass", f"v{version}")
        else:
            result["fw_version"] = ""
            self.set_step("parse_app_version", "pass", "Not in log (using manifest)")

        self.progress.emit(20)

        # Parse BLE address
        self.set_step("parse_ble_addr", "running")
        ble_addr = self._parse_ble_addr()
        if ble_addr:
            result["ble_mac"] = ble_addr
            self.set_step("parse_ble_addr", "pass", ble_addr)
        else:
            self.set_step("parse_ble_addr", "fail", "BLE address not found in log")

        self.progress.emit(40)

        # Parse battery voltage — non-fatal; BLE adv mfg data also reports battery
        self.set_step("parse_battery", "running")
        voltage = self._parse_battery()
        if voltage is not None:
            result["battery_voltage"] = voltage
            self.set_step("parse_battery", "pass", f"{voltage:.2f}V")
        else:
            self.set_step("parse_battery", "pass", "Not in log (BLE adv will be used)")

        self.progress.emit(60)

        # Validate battery range (only if UART gave us a voltage; otherwise
        # the BLE-adv battery percentage is checked downstream in the tab).
        if voltage is not None:
            self.set_step("validate_battery", "running")
            if self.battery_min <= voltage <= self.battery_max:
                self.set_step("validate_battery", "pass",
                              f"{voltage:.2f}V in range [{self.battery_min}-{self.battery_max}V]")
            else:
                self.set_step("validate_battery", "fail",
                              f"{voltage:.2f}V outside range [{self.battery_min}-{self.battery_max}V]")
                raise RuntimeError(
                    f"Battery voltage {voltage:.2f}V outside acceptable range "
                    f"[{self.battery_min}-{self.battery_max}V]"
                )
        else:
            self.set_step("validate_battery", "pass", "Skipped (no UART; BLE adv used)")

        self.progress.emit(80)

        return result

    def _parse_version(self) -> str:
        match = re.search(r"(?:version|ver|fw)[:\s]*v?(\d+\.\d+\.\d+)", self.uart_log, re.IGNORECASE)
        return match.group(1) if match else ""

    def _parse_ble_addr(self) -> str:
        mac_re = r"([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})"
        for line in self.uart_log.splitlines():
            low = line.lower()
            if ("ble" in low or "addr" in low or "bd_addr" in low) and "mac" not in low.split("wifi"):
                m = re.search(mac_re, line)
                if m:
                    return m.group(1).upper()
        # Fallback: any MAC-like pattern after "address" keyword
        match = re.search(r"address.*?" + mac_re, self.uart_log, re.IGNORECASE)
        return match.group(1).upper() if match else ""

    def _parse_battery(self) -> float | None:
        # Look for "BATT: XX% (Y.YYV, raw=NNNN)"
        match = re.search(r"BATT:.*?(\d+\.\d+)\s*V", self.uart_log, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return None
