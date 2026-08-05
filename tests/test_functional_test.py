"""Tests for boot log parsing in functional test workers."""

import pytest


def test_hub_version_parsing():
    """Test parsing firmware version from boot log."""
    from app.workers.functional_test import HubTestWorker

    log = """
I (325) app_start: Starting application
I (330) main: Firmware version: v1.4.2
I (335) wifi: WiFi MAC: AA:BB:CC:DD:EE:FF
I (340) NimBLE: NimBLE host task started
I (345) lora: SX1262 initialized
"""
    worker = HubTestWorker(boot_log=log, base_mac="AA:BB:CC:DD:EE:00")
    assert worker._parse_version() == "1.4.2"
    assert worker._check_lora() is True
    assert worker._check_nimble() is True


def test_hub_mac_parsing():
    from app.workers.functional_test import HubTestWorker

    log = """
WiFi MAC: 11:22:33:44:55:66
BLE MAC: AA:BB:CC:DD:EE:FF
"""
    worker = HubTestWorker(boot_log=log, base_mac="")
    wifi, bt = worker._parse_macs()
    assert wifi == "11:22:33:44:55:66".upper()
    assert bt == "AA:BB:CC:DD:EE:FF"


def test_sensor_battery_parsing():
    from app.workers.functional_test import SensorTestWorker

    log = """
>> BATT: 85% (2.92V, raw=1814)
>> APP: Version: v1.0.0
>> BLE: BD_ADDR: AA:BB:CC:DD:EE:FF
"""
    worker = SensorTestWorker(uart_log=log, uid="112233")
    assert worker._parse_battery() == pytest.approx(2.92)
    assert worker._parse_version() == "1.0.0"
    assert worker._parse_ble_addr() == "AA:BB:CC:DD:EE:FF"


def test_sensor_battery_not_found():
    from app.workers.functional_test import SensorTestWorker

    worker = SensorTestWorker(uart_log="no battery info here", uid="")
    assert worker._parse_battery() is None
