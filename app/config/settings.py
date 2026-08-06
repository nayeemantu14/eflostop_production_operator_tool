"""Application settings backed by YAML config file."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def _app_root() -> Path:
    """Return the application root directory (where main.py lives)."""
    if getattr(os.sys, "frozen", False):
        return Path(os.sys.executable).parent  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent


def _bundle_root() -> Path:
    """Return the directory where PyInstaller bundles data files.

    When frozen, bundled --add-data files live in sys._MEIPASS (_internal/).
    When running from source, same as _app_root().
    """
    if getattr(os.sys, "frozen", False):
        return Path(getattr(os.sys, "_MEIPASS"))  # type: ignore[attr-defined]
    return _app_root()


class FlashSettings(BaseModel):
    esp_baud: int = 460800
    stm32_programmer_cli: str = (
        r"C:\Program Files\STMicroelectronics\STM32Cube"
        r"\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe"
    )


class BleScanSettings(BaseModel):
    timeout_seconds: int = 10
    hub_name_prefix: str = "eFloStop"
    valve_name_prefix: str = "eFloStop"
    sensor_name_prefix: str = "eleak"


class LabelPrinterSettings(BaseModel):
    """Which label-printer backend to use, and its factory defaults.

    `backends` is deliberately untyped at this level: each backend validates its
    own slice with its own model, so adding a printer never touches this file.
    The label geometry is NOT configurable — 20 mm x 20 mm is a manufacturing
    spec and lives in app/services/printing/geometry.py.

    These are read-only factory defaults. The operator's actual choice and any
    per-machine settings live in QSettings, because when the tool is frozen this
    YAML sits inside PyInstaller's _internal/ directory where operators cannot
    edit it and the installer overwrites it on every upgrade.
    """

    # Backend id, e.g. "system". An id that is not registered degrades to the
    # system printer rather than failing. Ids are a persisted compatibility
    # surface — see docs/PRINTER_BACKENDS.md.
    backend: str = "system"
    backends: dict[str, dict[str, Any]] = Field(default_factory=dict)


class TestSettings(BaseModel):
    boot_log_timeout_seconds: int = 15
    battery_voltage_min: float = 2.5
    battery_voltage_max: float = 3.3


class SerialNumberSettings(BaseModel):
    prefix_by_device: dict[str, str] = Field(default_factory=lambda: {
        "hub": "EFS2H",
        "valve": "EFS2V",
        "sensor": "EFS2S",
    })


class SkuSettings(BaseModel):
    hub: str = "EFS2-HUB-NA"
    valve: str = "EFS2-VLV-1IN"
    sensor: str = "EFS2-LKS-BLE"


class FirmwareSettings(BaseModel):
    manifest_path: str = "firmware/manifest.yaml"


class GeneralSettings(BaseModel):
    company_name: str = "eFloStop"
    tool_version: str = "1.0.0"
    data_dir: str = "data"


class AppSettings(BaseModel):
    general: GeneralSettings = GeneralSettings()
    firmware: FirmwareSettings = FirmwareSettings()
    flash: FlashSettings = FlashSettings()
    serial_number: SerialNumberSettings = SerialNumberSettings()
    ble_scan: BleScanSettings = BleScanSettings()
    label_printer: LabelPrinterSettings = LabelPrinterSettings()
    test: TestSettings = TestSettings()
    skus: SkuSettings = SkuSettings()
    hw_revision: str = "C"

    @property
    def app_root(self) -> Path:
        return _app_root()

    @property
    def data_path(self) -> Path:
        p = self.app_root / self.general.data_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def bundle_root(self) -> Path:
        return _bundle_root()

    @property
    def manifest_full_path(self) -> Path:
        return _bundle_root() / self.firmware.manifest_path

    @property
    def stm32_cli_path(self) -> Path:
        return Path(self.flash.stm32_programmer_cli)


def load_settings(config_path: Path | None = None) -> AppSettings:
    """Load settings from YAML, falling back to defaults."""
    if config_path is None:
        config_path = _bundle_root() / "app" / "config" / "default_config.yaml"

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}
        return AppSettings(**raw)

    return AppSettings()


# Module-level singleton — import and use directly
settings = load_settings()
