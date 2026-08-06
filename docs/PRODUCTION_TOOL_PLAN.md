# eFloStop II Production Programming & Test Tool

## Overview

PyQt6 Windows desktop application for production operators to flash, test, provision, and label three eFloStop II device types:

| Device | MCU | Flash Tool | Interface |
|--------|-----|-----------|-----------|
| WiFi Hub | ESP32-S3 | esptool (Python lib) | CP2102 USB-UART |
| Valve | STM32WB5MMGH6TR | STM32_Programmer_CLI | ST-Link SWD |
| Leak Sensor | STM32WBA5MMGH6TR | STM32_Programmer_CLI | ST-Link SWD + UART via Tag-Connect |

## Architecture

```
C:\Work\Projects\EfloStop 2\Production tool\
├── main.py
├── app/
│   ├── ui/
│   │   ├── main_window.py          # QTabWidget + operator bar + firmware header
│   │   ├── tab_wifi_hub.py
│   │   ├── tab_valve.py
│   │   ├── tab_leak_sensor.py
│   │   ├── tab_history.py
│   │   └── widgets/
│   │       ├── step_list.py        # Vertical checklist widget
│   │       ├── log_viewer.py       # Color-coded log viewer
│   │       ├── big_status.py       # Large PASS/FAIL banner
│   │       ├── question_dialog.py  # Operator Yes/No dialogs
│   │       ├── firmware_panel.py   # Firmware info + Browse override
│   │       └── qr_preview.py       # QR code preview widget
│   ├── workers/
│   │   ├── base_worker.py          # QThread with standard signals
│   │   ├── esp_flasher.py          # esptool Python library wrapper
│   │   ├── stm32_flasher.py        # STM32_Programmer_CLI subprocess
│   │   ├── serial_monitor.py       # pyserial reader thread
│   │   ├── ble_scanner.py          # bleak async→Qt bridge
│   │   └── functional_test.py      # Test sequence orchestrator
│   ├── devices/
│   │   ├── base.py                 # Device base class
│   │   ├── wifi_hub.py
│   │   ├── valve.py
│   │   └── leak_sensor.py
│   ├── services/
│   │   ├── port_detector.py        # USB VID/PID enumeration
│   │   ├── stlink_detector.py      # ST-Link probe enumeration
│   │   ├── firmware_registry.py    # manifest.yaml loader
│   │   ├── qr_generator.py         # QR code generation
│   │   ├── printing/               # Pluggable label-printer backends
│   │   │   ├── base.py             #   backend contract
│   │   │   ├── geometry.py         #   20 mm spec + print guards (pure, no Qt)
│   │   │   ├── qt_geometry.py      #   QPrinter adapter
│   │   │   ├── qt_driver.py        #   base for driver-based printers
│   │   │   ├── registry.py         #   backend registration
│   │   │   ├── selection.py        #   which backend, persisted per user
│   │   │   └── backends/           #   system / puqu_aq20 / zpl_tcp
│   │   ├── record_logger.py        # JSONL + SQLite logging
│   │   ├── serial_generator.py     # YYWW-NNNNNN serial numbers
│   │   └── cloud_preprovision.py   # Azure provisioning stub
│   ├── config/
│   │   ├── settings.py             # pydantic Settings
│   │   └── default_config.yaml
│   └── resources/
├── firmware/                       # Live firmware binaries
│   ├── manifest.yaml
│   ├── wifi_hub/
│   ├── valve/
│   └── leak_sensor/
├── docs/
├── tests/
├── pyproject.toml
└── build_installer.py
```

## Flash Procedures

### WiFi Hub (ESP32-S3)
Uses esptool Python library directly:
- Offsets: bootloader=0x0000, partition=0x8000, OTA=0xD000, app=0x10000
- Baud: 460800
- MAC read via `esp.read_mac()`

### Valve (STM32WB) — 3-step
1. **FUS check/upgrade**: `STM32_Programmer_CLI -fusgetstate`, upgrade if needed
2. **BLE stack install**: `-fwupgrade` at 0x080C7000
3. **App flash**: `-e all -d valve.hex -v`
- UID at `0x1FFF7590` (3 words)
- DEV_ID `0x495` at `0xE0042000`

### Leak Sensor (STM32WBA) — single-step
- App flash: `-e all -d leak_sensor.hex -v`
- UID at `0x0BF90700` (3 words)
- DEV_ID `0x492` at `0xE0044000`

## Test Approach

Flash production firmware directly, then verify via:
- Boot log parsing (Hub UART, Sensor UART)
- ST-Link memory reads (Valve UID, BLE address)
- BLE advertising scan via bleak (all devices)
- Operator-confirmed visual/audible checks (LED, buzzer, servo)

## Threading Model

- **UI thread**: Qt widgets only, never blocks
- **Flash workers**: QThread per device, emits progress/log/done signals
- **Serial monitor**: QThread with pyserial blocking read
- **BLE scanner**: QThread with own asyncio event loop
- **STM32 CLI**: subprocess in QThread, stdout line-by-line

## Error Handling

- Wrong MCU detection via DEV_ID read before flash
- Single retry on flash failure; 3 consecutive → quarantine
- Plain-English messages for operators (no tracebacks)
- Missing firmware → red banner on affected tab only
