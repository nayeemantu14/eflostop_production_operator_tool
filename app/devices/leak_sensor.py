"""Leak Sensor (STM32WBA5MMGH6TR) device definition."""

from __future__ import annotations

from .base import DeviceDefinition, StepMethod, TestStep


class LeakSensorDevice(DeviceDefinition):
    device_type = "sensor"
    display_name = "BLE Leak Sensor"
    sku = "EFS2-LKS-BLE"
    mcu = "stm32wba"

    def flash_steps(self) -> list[TestStep]:
        return [
            TestStep(
                id="check_mcu_id",
                name="Verify MCU ID (STM32WBA)",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="flash_app",
                name="Flash application firmware",
                method=StepMethod.AUTO,
            ),
        ]

    def test_steps(self) -> list[TestStep]:
        return [
            TestStep(
                id="read_uid",
                name="Read 96-bit UID",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="capture_uart_log",
                name="Reset & capture UART log",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="parse_app_version",
                name="Parse app version from log",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="parse_ble_addr",
                name="Parse BLE address from log",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="ble_scan",
                name="BLE advertising scan",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="verify_fw_version",
                name="Verify FW version (BLE mfg data)",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="parse_battery",
                name="Parse battery voltage from log",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="validate_battery",
                name="Validate battery range (2.5-3.3V)",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="led_check",
                name="LED visible?",
                method=StepMethod.MANUAL,
            ),
            TestStep(
                id="buzzer_check",
                name="Buzzer audible?",
                method=StepMethod.MANUAL,
            ),
            TestStep(
                id="leak_probe_test",
                name="Short leak probes — confirm detection",
                method=StepMethod.SEMI_AUTO,
            ),
            TestStep(
                id="flash_production",
                name="Flash production (release) firmware",
                method=StepMethod.AUTO,
            ),
        ]
