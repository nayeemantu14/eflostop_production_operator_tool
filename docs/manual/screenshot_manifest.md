# Screenshot Manifest — eFloStop II Production Operator Manual

Every figure in the manual, its source, and how it was produced. **Capture status**
key: `auto` = rendered headless from the live tool UI (no hardware); `mock` = rendered
by driving the tab's own UI methods with canned results (run-state that only exists in
worker callbacks); `authored` = a drawn diagram (not a screenshot); `PLACEHOLDER` = a
clearly-labelled bordered box to be replaced by a human capture per Appendix B.

All screenshots were produced by `docs/manual/capture/capture.py` on the native Windows
Qt platform (real fonts) with `WA_DontShowOnScreen` (no windows shown), against the real
`firmware/manifest.yaml` (all files present → genuine green state). No screenshot was
fabricated or AI-generated; no depicted UI element is absent from the code.

| Fig | Manual § | File / asset | Tool state depicted | Source citation | Capture status |
|-----|----------|--------------|---------------------|-----------------|----------------|
| 1  | 4 | fig01_full_window.png | Idle full window: operator bar + firmware strip + 4 tabs | main_window.py:52-91 | auto |
| 2  | 4 | fig02_operator_bar.png | Operator bar, empty Operator ID / Work Order | main_window.py:93-132 | auto |
| 3  | 4 | fig03_firmware_green.png | Firmware strip, all-present (green) | main_window.py:134-169; firmware_registry.py:43-52 | auto |
| 3b | 4 | fig03b_firmware_red.png | Firmware strip, missing firmware (red) | main_window.py:44-47,145 | PLACEHOLDER |
| 4  | 4 | fig04_hub_anatomy.png | WiFi Hub tab, READY (anatomy annotation base) | tab_wifi_hub.py:62-152 | auto |
| 5  | 4 | fig05_banner_styles.png | Status banner: READY/RUNNING/PASS/FAIL styles | big_status.py:13-34; tab_wifi_hub.py:418 (ABORTED) | auto (composed) |
| 6  | 4 | fig06_step_legend.png | Step-status legend: pending/running/pass/fail/skipped | step_list.py:10-16 | auto (composed) |
| 7  | 4 | fig07_operator_check.png | "Operator Check" YES/NO dialog | question_dialog.py:16-84 | auto |
| 8  | 8 | fig08_warning_operator_id.png | Warning "Enter your Operator ID before starting." | tab_wifi_hub.py:196-198 | auto |
| 9  | 5 | fig09_hub_ready.png | WiFi Hub tab, READY | tab_wifi_hub.py:75-92,167-173 | auto |
| 10 | 5 | fig10_hub_wiring.png | CP2102 USB-UART to Hub (photo) | README.md:28 | PLACEHOLDER (photo) |
| 11 | 5 | fig11_hub_running.png | WiFi Hub run in progress (RUNNING + log) | tab_wifi_hub.py:209,224-268 | mock |
| 12 | 5 | fig12_hub_pass.png | WiFi Hub PASS + populated QR | tab_wifi_hub.py:336-390 | mock |
| 13 | 6 | fig13_valve_ready.png | Valve tab, READY | tab_valve.py:83-93,166-175 | auto |
| 14 | 6 | fig14_valve_wiring.png | ST-Link SWD to valve (photo) | README.md:27; stm32_flasher.py:144-253 | PLACEHOLDER (photo) |
| 15 | 6 | fig15_valve_flash.png | Valve flash sequence mid-run | valve.py:14-105; stm32_flasher.py:169-253 | mock |
| 16 | 6 | fig16_valve_servo.png | Servo-check "Operator Check" dialog | tab_valve.py:484-494 | auto |
| 17 | 6 | fig17_valve_pass.png | Valve PASS + populated QR | tab_valve.py:508-569 | mock |
| 18 | 7 | fig18_sensor_ready.png | Leak Sensor tab, READY | tab_leak_sensor.py:74-84,156-162 | auto |
| 19 | 7 | fig19_coincell.png | Coin-cell installation / polarity (photo) | README.md:29; functional_test.py:182-194 | PLACEHOLDER (photo) |
| 20 | 7 | fig20_sensor_battery.png | Battery-range validation step | functional_test.py:184-190; leak_sensor.py:66-68 | mock |
| 21 | 7 | fig21_sensor_leak.png | Leak-probe "Operator Check" dialog | tab_leak_sensor.py:384-394 | auto |
| 22 | 7 | fig22_sensor_pass.png | Leak Sensor PASS + populated QR | tab_leak_sensor.py:399-468 | mock |
| 23 | 8 | fig23_fail_example.png | FAIL banner + "FAIL:" log line | tab_wifi_hub.py:392-408 | mock |
| 24 | 8.1 | fig24_printed_label.png | Printed 20 mm x 20 mm QR-only label (photo, with ruler) | printing/geometry.py (20 mm spec); printing/qt_geometry.py (draw) | PLACEHOLDER (photo) |
| 25 | 4.4/8 | fig25_qr_panel.png | Populated QR panel (Printer dropdown + Print/Setup buttons) | qr_preview.py (QrPreview panel); ui/widgets/printer_selector.py | mock |
| 25b| 4.4 | fig25b_qr_idle.png | Idle "No QR generated" panel (dropdown visible, buttons hidden) | qr_preview.py (QrPreview.clear) | auto |
| 26 | 2.6/8.1 | fig26_printer_setup.png | Printer Setup dialog for the selected backend (Windows print dialog for "System printer (any)") | printing/backends/system.py (configure) | PLACEHOLDER (OS) |
| 27 | 5.6/6.7/7.7 | fig27_qr_anatomy.png | QR payload field-anatomy diagram | qr_generator.py:47-59; DEVICE_QR_PREFIX:18-22 | authored |
| 28 | 9 | fig28_history.png | History tab, populated + filters/stats | record_logger.py:70-93; tab_history.py | mock |

**Placeholders to replace before release (6):** Fig 3b (red strip), Fig 10/14/19 (wiring & coin-cell photos), Fig 24 (printed 20 mm label photo), Fig 26 (Printer Setup dialog). Recipes for each are in **Appendix B — Screenshot & Figure Capture Guide**.
