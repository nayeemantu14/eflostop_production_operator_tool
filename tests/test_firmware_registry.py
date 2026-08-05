"""Tests for firmware registry / manifest loader."""

import tempfile
from pathlib import Path

import pytest
import yaml

from app.services.firmware_registry import FirmwareRegistry, DeviceFirmware


@pytest.fixture
def manifest_dir(tmp_path):
    """Create a temporary firmware directory with manifest."""
    fw_dir = tmp_path / "firmware"
    fw_dir.mkdir()

    # Create dummy firmware files
    hub_dir = fw_dir / "wifi_hub"
    hub_dir.mkdir()
    (hub_dir / "bootloader.bin").write_bytes(b"\x00" * 100)
    (hub_dir / "app.bin").write_bytes(b"\x00" * 200)

    sensor_dir = fw_dir / "leak_sensor"
    sensor_dir.mkdir()
    (sensor_dir / "app.hex").write_text(":00000001FF")

    manifest = {
        "wifi_hub": {
            "version": "1.2.3",
            "files": {
                "bootloader": "wifi_hub/bootloader.bin",
                "application": "wifi_hub/app.bin",
            },
            "flash_offsets": {
                "bootloader": 0x0000,
                "application": 0x10000,
            },
        },
        "leak_sensor": {
            "version": "2.0.0",
            "mcu_dev_id": 0x492,
            "mcu_id_address": 0xE0044000,
            "uid_address": 0x0BF90700,
            "files": {
                "application": "leak_sensor/app.hex",
            },
        },
        "valve": {
            "version": "1.0.0",
            "files": {
                "application": "valve/missing.hex",
            },
        },
    }

    manifest_path = fw_dir / "manifest.yaml"
    manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

    return fw_dir, manifest_path


def test_load_manifest(manifest_dir):
    fw_dir, manifest_path = manifest_dir
    reg = FirmwareRegistry(manifest_path, fw_dir)
    reg.load()

    assert "wifi_hub" in reg.devices
    assert "leak_sensor" in reg.devices
    assert "valve" in reg.devices


def test_file_existence(manifest_dir):
    fw_dir, manifest_path = manifest_dir
    reg = FirmwareRegistry(manifest_path, fw_dir)
    reg.load()

    hub = reg.get("wifi_hub")
    assert hub is not None
    assert hub.all_present is True

    sensor = reg.get("leak_sensor")
    assert sensor is not None
    assert sensor.all_present is True

    valve = reg.get("valve")
    assert valve is not None
    assert valve.all_present is False
    assert len(valve.missing_files) == 1


def test_version(manifest_dir):
    fw_dir, manifest_path = manifest_dir
    reg = FirmwareRegistry(manifest_path, fw_dir)
    reg.load()

    assert reg.get("wifi_hub").version == "1.2.3"
    assert reg.get("leak_sensor").version == "2.0.0"


def test_mcu_metadata(manifest_dir):
    fw_dir, manifest_path = manifest_dir
    reg = FirmwareRegistry(manifest_path, fw_dir)
    reg.load()

    sensor = reg.get("leak_sensor")
    assert sensor.mcu_dev_id == 0x492
    assert sensor.uid_address == 0x0BF90700


def test_override(manifest_dir):
    fw_dir, manifest_path = manifest_dir
    reg = FirmwareRegistry(manifest_path, fw_dir)
    reg.load()

    valve = reg.get("valve")
    assert not valve.all_present

    # Create an override file
    override = fw_dir / "override.hex"
    override.write_text(":00000001FF")
    valve.set_override("application", override)

    assert valve.all_present
    assert valve.effective_path("application") == override


def test_sha256_computed(manifest_dir):
    fw_dir, manifest_path = manifest_dir
    reg = FirmwareRegistry(manifest_path, fw_dir)
    reg.load()

    hub = reg.get("wifi_hub")
    boot = hub.files["bootloader"]
    assert boot.sha256 != ""
    assert len(boot.sha256) == 64  # SHA-256 hex digest length
