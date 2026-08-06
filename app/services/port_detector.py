"""USB serial port detection for ESP32 (CP2102/CP2104) and ST-Link VCP."""

from __future__ import annotations

from dataclasses import dataclass

import serial.tools.list_ports


# CP2102/CP2104 USB VID:PID
SILICON_LABS_VID = 0x10C4
CP210X_PIDS = {0xEA60, 0xEA70}  # CP2102, CP2104

# STMicroelectronics ST-Link VCP
STMICRO_VID = 0x0483


@dataclass
class DetectedPort:
    port: str
    description: str
    vid: int
    pid: int
    serial_number: str


def find_cp210x_ports() -> list[DetectedPort]:
    """Find all CP2102/CP2104 serial ports."""
    results = []
    for info in serial.tools.list_ports.comports():
        if info.vid == SILICON_LABS_VID and info.pid in CP210X_PIDS:
            results.append(DetectedPort(
                port=info.device,
                description=info.description or "",
                vid=info.vid,
                pid=info.pid,
                serial_number=info.serial_number or "",
            ))
    return results


def find_stlink_vcp_ports() -> list[DetectedPort]:
    """Find ST-Link Virtual COM Ports (VCP).

    ST-Link V2-1, V3, and Nucleo on-board probes expose a VCP
    for UART passthrough. VID is always 0x0483 (STMicroelectronics).
    """
    results = []
    for info in serial.tools.list_ports.comports():
        if info.vid == STMICRO_VID:
            results.append(DetectedPort(
                port=info.device,
                description=info.description or "",
                vid=info.vid,
                pid=info.pid or 0,
                serial_number=info.serial_number or "",
            ))
    return results


def find_any_serial_ports() -> list[DetectedPort]:
    """Find all serial ports with VID/PID info."""
    results = []
    for info in serial.tools.list_ports.comports():
        if info.vid is not None:
            results.append(DetectedPort(
                port=info.device,
                description=info.description or "",
                vid=info.vid,
                pid=info.pid or 0,
                serial_number=info.serial_number or "",
            ))
    return results


def find_all_serial_ports() -> list[DetectedPort]:
    """Find every COM port, including those with no USB VID/PID.

    The detectors above all filter on VID because they are looking for one
    specific USB chip. This one deliberately does not: a Bluetooth SPP port and
    a motherboard's built-in serial port both report ``vid=None``, and a label
    printer paired over Bluetooth shows up as exactly that. Filtering them out
    would hide the printer the operator is trying to select.
    """
    return [
        DetectedPort(
            port=info.device,
            description=info.description or "",
            vid=info.vid or 0,
            pid=info.pid or 0,
            serial_number=info.serial_number or "",
        )
        for info in serial.tools.list_ports.comports()
    ]
