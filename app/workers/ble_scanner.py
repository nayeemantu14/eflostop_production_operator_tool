"""BLE scanner using bleak, bridged to Qt signals."""

from __future__ import annotations

import asyncio
from typing import Any

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from PyQt6.QtCore import QThread, pyqtSignal


class BleScanner(QThread):
    """Scan for BLE advertisements matching a name prefix or MAC.

    Signals:
        device_found(dict): {name, address, rssi, manufacturer_data, service_data}
        scan_complete(list): All matching devices found
        observed(str): Diagnostic — every unique address seen during scan
        scan_started(str): Emitted when scan begins (with status string)
        scan_finished(int): Emitted when scan ends (with total unique devices seen)
        error(str): Error message
    """

    device_found = pyqtSignal(dict)
    scan_complete = pyqtSignal(list)
    observed = pyqtSignal(str)
    scan_started = pyqtSignal(str)
    scan_finished = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(
        self,
        name_prefix: str = "",
        target_mac: str = "",
        timeout: float = 10.0,
        parent=None,
    ):
        super().__init__(parent)
        self.name_prefix = name_prefix.lower()
        self.target_mac = target_mac.upper()
        self.timeout = timeout
        self._found: list[dict[str, Any]] = []

    def run(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._scan())
            finally:
                loop.close()
        except Exception as e:
            self.error.emit(f"BLE scan thread crashed: {e}")

    async def _scan(self) -> None:
        self._found.clear()
        seen_addrs: set[str] = set()

        self.scan_started.emit(
            f"target_mac={self.target_mac or '-'}  "
            f"name_prefix={self.name_prefix or '-'}  "
            f"timeout={self.timeout}s"
        )

        def _callback(device: BLEDevice, adv: AdvertisementData) -> None:
            name = (device.name or adv.local_name or "").lower()
            addr = device.address.upper()

            # Diagnostic: emit each unique device exactly once
            if addr not in seen_addrs:
                seen_addrs.add(addr)
                mfg_keys = ",".join(f"0x{k:04X}" for k in adv.manufacturer_data.keys())
                self.observed.emit(
                    f"{addr}  rssi={adv.rssi:4d}  name={name or '-'}  mfg=[{mfg_keys}]"
                )

            match = False
            if self.target_mac and addr == self.target_mac:
                match = True
            elif self.name_prefix and name.startswith(self.name_prefix):
                match = True

            if match:
                info = {
                    "name": device.name or adv.local_name or "",
                    "address": device.address,
                    "rssi": adv.rssi,
                    "manufacturer_data": dict(adv.manufacturer_data),
                    "service_data": {str(k): v.hex() for k, v in adv.service_data.items()},
                }
                self._found.append(info)
                self.device_found.emit(info)

        # Active scanning gets scan responses too — needed when devices put
        # their full local name in the scan response rather than the adv packet.
        try:
            scanner = BleakScanner(
                detection_callback=_callback,
                scanning_mode="active",
            )
        except TypeError:
            # Older bleak versions don't support scanning_mode kwarg
            scanner = BleakScanner(detection_callback=_callback)

        try:
            await scanner.start()
        except Exception as e:
            self.error.emit(f"BleakScanner.start() failed: {e}")
            self.scan_finished.emit(0)
            self.scan_complete.emit([])
            return

        await asyncio.sleep(self.timeout)

        try:
            await scanner.stop()
        except Exception as e:
            self.error.emit(f"BleakScanner.stop() failed: {e}")

        self.scan_finished.emit(len(seen_addrs))
        self.scan_complete.emit(list(self._found))


class BleServiceReader(QThread):
    """Connect to a BLE device and read a characteristic.

    Used for reading DIS Firmware Revision (0x2A26) from valve.

    Signals:
        value_read(str, bytes): (characteristic_uuid, value)
        error(str): Error message
    """

    value_read = pyqtSignal(str, bytes)
    error = pyqtSignal(str)

    def __init__(
        self,
        address: str,
        characteristic_uuid: str,
        timeout: float = 10.0,
        parent=None,
    ):
        super().__init__(parent)
        self.address = address
        self.characteristic_uuid = characteristic_uuid
        self.timeout = timeout

    def run(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._read())
            finally:
                loop.close()
        except Exception as e:
            self.error.emit(str(e))

    async def _read(self) -> None:
        from bleak import BleakClient

        async with BleakClient(self.address, timeout=self.timeout) as client:
            data = await client.read_gatt_char(self.characteristic_uuid)
            self.value_read.emit(self.characteristic_uuid, bytes(data))
