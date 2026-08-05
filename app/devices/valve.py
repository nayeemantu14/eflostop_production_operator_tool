"""Valve (STM32WB5MMGH6TR) device definition."""

from __future__ import annotations

from .base import DeviceDefinition, StepMethod, TestStep


class ValveDevice(DeviceDefinition):
    device_type = "valve"
    display_name = "BLE Valve"
    sku = "EFS2-VLV-1IN"
    mcu = "stm32wb"

    def flash_steps(self) -> list[TestStep]:
        return [
            TestStep(
                id="check_mcu_id",
                name="Verify MCU ID (STM32WB)",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="fus_check",
                name="Check/upgrade FUS",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="ble_stack_install",
                name="Install BLE wireless stack",
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
                id="reset_boot",
                name="Reset & wait for boot",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="capture_boot_log",
                name="Capture UART boot log",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="parse_uart_bd_addr",
                name="Parse BD address from UART",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="ble_scan",
                name="BLE advertising scan",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="read_ble_addr",
                name="Read BLE public address",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="verify_bd_address",
                name="Cross-verify BD address (UART vs BLE)",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="read_fw_version",
                name="Read FW version via DIS",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="verify_fw_version",
                name="Verify FW version (DIS)",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="led_check",
                name="LED visible?",
                method=StepMethod.MANUAL,
            ),
            TestStep(
                id="servo_check",
                name="Servo actuation — press button, confirm valve moved",
                method=StepMethod.MANUAL,
            ),
            TestStep(
                id="buzzer_check",
                name="Buzzer audible?",
                method=StepMethod.MANUAL,
            ),
            TestStep(
                id="flash_production",
                name="Flash production firmware (low-power)",
                method=StepMethod.AUTO,
            ),
        ]
