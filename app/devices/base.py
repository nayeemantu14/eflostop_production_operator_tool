"""Base device definition for production tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


class StepMethod(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"
    SEMI_AUTO = "semi_auto"


@dataclass
class TestStep:
    id: str
    name: str
    method: StepMethod
    status: StepStatus = StepStatus.PENDING
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceResult:
    """Collected results from a full flash+test cycle."""
    device_type: str = ""
    serial_number: str = ""
    uid: str = ""
    ble_mac: str = ""
    wifi_mac: str = ""
    fw_version: str = ""
    hw_revision: str = ""
    sku: str = ""
    result: str = "UNKNOWN"  # PASS / FAIL
    steps: list[dict[str, Any]] = field(default_factory=list)
    qr_payload: str = ""
    notes: str = ""


class DeviceDefinition:
    """Base class for device-specific flash and test configuration."""

    device_type: str = ""
    display_name: str = ""
    sku: str = ""
    mcu: str = ""

    def flash_steps(self) -> list[TestStep]:
        """Return ordered list of flash steps."""
        raise NotImplementedError

    def test_steps(self) -> list[TestStep]:
        """Return ordered list of functional test steps."""
        raise NotImplementedError

    def all_steps(self) -> list[TestStep]:
        """Flash steps followed by test steps."""
        return self.flash_steps() + self.test_steps()

    def qr_fields(self) -> dict[str, str]:
        """Return device-specific QR payload fields."""
        return {
            "v": "1",
            "t": self.device_type,
            "sku": self.sku,
        }
