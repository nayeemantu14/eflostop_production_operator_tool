"""Port detection for ESP32 (CP2102/CP2104), ST-Link VCP, and label printers."""

from __future__ import annotations

import sys
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


def find_parallel_ports() -> list[DetectedPort]:
    """Find LPT ports, which pyserial deliberately hides.

    ``serial.tools.list_ports`` enumerates the "Ports (COM & LPT)" device class
    and then drops anything whose name starts with LPT, because it cannot drive
    one. That is right for pyserial and wrong for us: some USB label printers
    are presented by Windows as LPT1 rather than as a virtual COM port, and a
    printer the operator cannot select is a printer they cannot use.

    Uses QueryDosDevice, which resolves a DOS device name to its NT path without
    opening anything — important, because this runs while the port list is being
    drawn and opening a printer port can block.
    """
    if sys.platform != "win32":
        return []

    import ctypes
    import ctypes.wintypes as wintypes

    query = ctypes.windll.kernel32.QueryDosDeviceW
    query.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    query.restype = wintypes.DWORD

    buffer = ctypes.create_unicode_buffer(1024)
    results: list[DetectedPort] = []
    # LPT1-LPT9 covers every port Windows will hand out; there is no enumeration
    # API for DOS device names that does not also open the device.
    for n in range(1, 10):
        name = f"LPT{n}"
        if query(name, buffer, 1024):
            results.append(DetectedPort(
                port=name,
                description=f"Parallel/printer port ({buffer.value})",
                vid=0,
                pid=0,
                serial_number="",
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
