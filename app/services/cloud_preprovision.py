"""Azure IoT Hub pre-provisioning stub.

This module provides a placeholder for cloud pre-provisioning.
In production, it would register the device with Azure DPS or
create a device identity in IoT Hub.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ProvisionResult:
    success: bool
    message: str
    device_id: str = ""
    connection_string: str = ""


def dry_run(device_type: str, uid: str, serial_number: str) -> ProvisionResult:
    """Simulate provisioning without making any API calls."""
    device_id = f"GW-{uid}" if device_type == "hub" else f"{device_type}-{uid}"
    return ProvisionResult(
        success=True,
        message=f"DRY RUN: Would provision {device_id}",
        device_id=device_id,
    )


def provision(
    device_type: str,
    uid: str,
    serial_number: str,
    **kwargs: Any,
) -> ProvisionResult:
    """Provision a device with Azure IoT Hub.

    TODO: Implement actual DPS enrollment or IoT Hub device creation.
    For now, returns dry_run result.
    """
    return dry_run(device_type, uid, serial_number)
