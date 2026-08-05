"""Firmware manifest loader and file validator."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class FirmwareFile:
    role: str           # e.g. "bootloader", "application", "ble_stack"
    path: Path          # Absolute path to binary
    offset: int | None  # Flash offset (ESP32) or address (STM32), None if N/A
    exists: bool = False
    sha256: str = ""

    def compute_hash(self) -> str:
        if self.path.exists():
            self.exists = True
            self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        else:
            self.exists = False
            self.sha256 = ""
        return self.sha256


@dataclass
class DeviceFirmware:
    device_type: str
    version: str = ""
    mcu_dev_id: int | None = None
    mcu_id_address: int | None = None
    uid_address: int | None = None
    fus_min_version: str | None = None
    flash_size: str | None = None  # e.g. "16MB" — used by esptool for ESP32
    files: dict[str, FirmwareFile] = field(default_factory=dict)
    overrides: dict[str, Path] = field(default_factory=dict)

    @property
    def all_present(self) -> bool:
        for role, fw_file in self.files.items():
            effective = self.overrides.get(role)
            if effective:
                if not effective.exists():
                    return False
            elif not fw_file.exists:
                return False
        return bool(self.files)

    @property
    def missing_files(self) -> list[str]:
        missing = []
        for role, fw_file in self.files.items():
            effective = self.overrides.get(role)
            if effective:
                if not effective.exists():
                    missing.append(f"{role} (override: {effective})")
            elif not fw_file.exists:
                missing.append(f"{role}: {fw_file.path}")
        return missing

    def effective_path(self, role: str) -> Path | None:
        if role in self.overrides:
            return self.overrides[role]
        if role in self.files:
            return self.files[role].path
        return None

    def set_override(self, role: str, path: Path) -> None:
        self.overrides[role] = path

    def clear_override(self, role: str) -> None:
        self.overrides.pop(role, None)


class FirmwareRegistry:
    """Loads firmware manifest and tracks file status."""

    def __init__(self, manifest_path: Path, firmware_root: Path | None = None):
        self.manifest_path = manifest_path
        self.firmware_root = firmware_root or manifest_path.parent
        self.devices: dict[str, DeviceFirmware] = {}
        self._raw: dict[str, Any] = {}

    def load(self) -> None:
        """Load manifest.yaml and validate file existence."""
        if not self.manifest_path.exists():
            raise FileNotFoundError(f"Firmware manifest not found: {self.manifest_path}")

        with open(self.manifest_path, "r", encoding="utf-8") as f:
            self._raw = yaml.safe_load(f) or {}

        self.devices.clear()

        for device_key, device_data in self._raw.items():
            if not isinstance(device_data, dict):
                continue

            dev = DeviceFirmware(device_type=device_key)
            dev.version = str(device_data.get("version", ""))
            dev.mcu_dev_id = device_data.get("mcu_dev_id")
            dev.mcu_id_address = device_data.get("mcu_id_address")
            dev.uid_address = device_data.get("uid_address")
            dev.fus_min_version = device_data.get("fus_min_version")
            dev.flash_size = device_data.get("flash_size")

            files_dict = device_data.get("files", {})
            offsets_dict = device_data.get("flash_offsets", {})
            addresses_dict = device_data.get("flash_addresses", {})

            for role, rel_path in files_dict.items():
                abs_path = self.firmware_root / rel_path
                offset = offsets_dict.get(role)
                if offset is None:
                    offset = addresses_dict.get(role)
                fw_file = FirmwareFile(role=role, path=abs_path, offset=offset)
                fw_file.compute_hash()
                dev.files[role] = fw_file

            self.devices[device_key] = dev

    def get(self, device_type: str) -> DeviceFirmware | None:
        return self.devices.get(device_type)

    def refresh(self) -> None:
        """Re-check file existence and hashes without reloading manifest."""
        for dev in self.devices.values():
            for fw_file in dev.files.values():
                fw_file.compute_hash()

    @property
    def all_valid(self) -> bool:
        return all(dev.all_present for dev in self.devices.values())

    def status_summary(self) -> dict[str, dict]:
        """Return a summary dict for UI display."""
        result = {}
        for key, dev in self.devices.items():
            result[key] = {
                "version": dev.version,
                "all_present": dev.all_present,
                "missing": dev.missing_files,
                "overrides": {r: str(p) for r, p in dev.overrides.items()},
            }
        return result
