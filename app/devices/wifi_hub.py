"""WiFi Hub (ESP32-S3) device definition."""

from __future__ import annotations

from .base import DeviceDefinition, StepMethod, TestStep


class WiFiHubDevice(DeviceDefinition):
    device_type = "hub"
    display_name = "WiFi Hub"
    sku = "EFS2-HUB-NA"
    mcu = "esp32s3"

    def flash_steps(self) -> list[TestStep]:
        return [
            TestStep(
                id="flash_firmware",
                name="Flash firmware (esptool)",
                method=StepMethod.AUTO,
            ),
        ]

    def test_steps(self) -> list[TestStep]:
        return [
            TestStep(
                id="capture_boot_log",
                name="Capture boot log",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="parse_app_version",
                name="Parse app version",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="verify_fw_version",
                name="Verify FW version (boot log)",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="read_base_mac",
                name="Read base MAC",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="parse_wifi_bt_mac",
                name="Parse Gateway ID from log",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="lora_init",
                name="LoRa SX1262 init check",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="nimble_init",
                name="BLE NimBLE init check",
                method=StepMethod.AUTO,
            ),
            TestStep(
                id="led_check",
                name="LED visible?",
                method=StepMethod.MANUAL,
            ),
        ]
