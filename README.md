# eFloStop II Production Programming & Test Tool

Windows desktop application (PyQt6) for production-line programming, functional testing, and labelling of eFloStop II devices.

## Supported Devices

| Device | MCU | Flash Method |
|--------|-----|-------------|
| WiFi Hub | ESP32-S3 | esptool (USB-UART via CP2102) |
| BLE Valve | STM32WB5MMGH6TR | STM32_Programmer_CLI (ST-Link SWD) |
| BLE Leak Sensor | STM32WBA5MMGH6TR | STM32_Programmer_CLI (ST-Link SWD) |

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the tool
python main.py
```

## Prerequisites

- Python 3.11+
- STM32CubeProgrammer (for Valve and Leak Sensor tabs)
- ST-Link debugger (for STM32 devices)
- CP2102 USB-UART adapter (for WiFi Hub)
- Windows Bluetooth adapter (for BLE verification scans)

## Firmware Setup

Place firmware binaries in the `firmware/` directory and update `firmware/manifest.yaml`:

```
firmware/
├── manifest.yaml
├── wifi_hub/
│   ├── bootloader.bin
│   ├── partition-table.bin
│   ├── ota_data_initial.bin
│   └── eflostop2_hub.bin
├── valve/
│   ├── stm32wb5x_FUS_fw.bin
│   ├── stm32wb5x_BLE_Stack_full_fw.bin
│   └── eflostop2_valve.hex
└── leak_sensor/
    └── eflostop2_leak_sensor.hex
```

## Configuration

Edit `app/config/default_config.yaml` to configure:
- STM32CubeProgrammer CLI path
- BLE scan parameters
- Label printer settings
- Battery voltage thresholds
- SKU identifiers

## Building Installer

```bash
# Build standalone .exe
python build_installer.py

# Build .exe + Inno Setup installer
python build_installer.py --inno
```

## Running Tests

```bash
pytest tests/
```

## Project Structure

See [docs/PRODUCTION_TOOL_PLAN.md](docs/PRODUCTION_TOOL_PLAN.md) for full architecture details.
