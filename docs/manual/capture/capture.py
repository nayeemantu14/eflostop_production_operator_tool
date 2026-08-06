"""Screenshot capture harness for the eFloStop II Operator Manual.

READ-ONLY against the production tool: this script IMPORTS the tool as a library
and drives its widgets into each documented state with canned data. It never
modifies any tool source file. It writes PNGs to docs/manual/assets/.

States that only exist inside worker callbacks (RUNNING / PASS / FAIL / populated
QR) are produced here by calling the tab's own UI methods with fake results
instead of running real flashers/BLE/serial workers. States that genuinely need
a camera photo or an OS dialog are emitted as clearly-labelled placeholders.

Run from the project root:  python docs/manual/capture/capture.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "windows"  # native plugin: real font glyphs
                                           # (the offscreen plugin renders tofu boxes)

# Project root = three levels up from this file (docs/manual/capture/capture.py)
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
ASSETS = ROOT / "docs" / "manual" / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

# Redirect the tool's data dir to a throwaway temp folder so capturing never
# writes to the real production records / serial DB.
_TMP = Path(tempfile.mkdtemp(prefix="efs_capture_"))
from app.config.settings import settings  # noqa: E402
settings.general.data_dir = str(_TMP)      # absolute -> settings.data_path == _TMP

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QPixmap  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication, QMessageBox, QWidget, QVBoxLayout, QLabel,
)
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

app = QApplication(sys.argv)

from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.widgets.big_status import BigStatusBanner  # noqa: E402
from app.ui.widgets.step_list import StepListWidget  # noqa: E402
from app.ui.widgets.question_dialog import QuestionDialog  # noqa: E402

results: list[tuple[str, str]] = []  # (filename, status)

# Render widgets fully but never map them onto the visible screen (no window
# flashes), while still using the native platform's real font rendering.
NOSHOW = Qt.WidgetAttribute.WA_DontShowOnScreen


def show_hidden(w: QWidget) -> None:
    w.setAttribute(NOSHOW, True)
    w.show()


def pump(n: int = 4) -> None:
    for _ in range(n):
        app.processEvents()


def grab(widget: QWidget, name: str) -> None:
    try:
        widget.repaint()
        pump()
        pix: QPixmap = widget.grab()
        out = ASSETS / name
        ok = pix.save(str(out), "PNG")
        results.append((name, "captured" if ok and out.exists() else "FAILED-save"))
    except Exception as e:  # noqa: BLE001
        results.append((name, f"ERROR: {e}"))


# ---------------------------------------------------------------------------
# Main window (real manifest => genuine all-present green firmware strip)
# ---------------------------------------------------------------------------
win = MainWindow()
win.resize(1220, 840)
win.operator_input.setText("OP-0412")
win.work_order_input.setText("WO-2026-00042")
show_hidden(win)
pump(8)

grab(win, "fig01_full_window.png")
grab(win.operator_input.parentWidget(), "fig02_operator_bar.png")
# firmware strip = parent widget of any firmware status tag
_strip = list(win.fw_status_labels.values())[0].parentWidget()
grab(_strip, "fig03_firmware_green.png")

TABS = {"hub": win.hub_tab, "valve": win.valve_tab, "sensor": win.sensor_tab}


def show_tab(tab: QWidget) -> None:
    win.tabs.setCurrentWidget(tab)
    pump(6)


# READY states -------------------------------------------------------------
show_tab(win.hub_tab);    grab(win.hub_tab, "fig04_hub_anatomy.png")
grab(win.hub_tab, "fig09_hub_ready.png")
grab(win.hub_tab.qr_preview, "fig25b_qr_idle.png")   # 'No QR generated' idle panel
show_tab(win.valve_tab);  grab(win.valve_tab, "fig13_valve_ready.png")
show_tab(win.sensor_tab); grab(win.sensor_tab, "fig18_sensor_ready.png")


# --- helpers to drive a tab into run states --------------------------------
def steps_of(tab):
    return tab.device.all_steps()


def set_running(tab, done_frac=0.5, running_detail="working..."):
    tab.status_banner.set_status("running")
    tab.start_btn.setEnabled(False)
    tab.abort_btn.setEnabled(True)
    st = steps_of(tab)
    cut = max(1, int(len(st) * done_frac))
    for s in st[:cut]:
        tab.step_list.update_step(s.id, "pass", "OK")
    if cut < len(st):
        tab.step_list.update_step(st[cut].id, "running", running_detail)


def finish_pass(tab, result: dict):
    for s in steps_of(tab):
        tab.step_list.update_step(s.id, "pass", "OK")
    tab._result = dict(result)
    tab._finish_pass()


# HUB: running + pass -------------------------------------------------------
show_tab(win.hub_tab)
t = win.hub_tab
set_running(t, 0.55, "Listening for boot log...")
t.log_viewer.append("Flashing firmware (esptool)...", "info")
t.log_viewer.append("Flash complete. Base MAC: 34:B7:DA:6A:AD:54", "pass")
t.log_viewer.append("[UART] I (330) main: Firmware version: v1.4.2", "debug")
t.log_viewer.append("[UART] Gateway ID: GW-34B7DA6AAD54", "debug")
grab(t, "fig11_hub_running.png")
finish_pass(t, {"fw_version": "1.4.2", "gateway_id": "GW-34B7DA6AAD54",
                "wifi_mac": "34:B7:DA:6A:AD:54", "base_mac": "34:B7:DA:6A:AD:54"})
grab(t, "fig12_hub_pass.png")
grab(t.qr_preview, "fig25_qr_panel.png")   # populated QR panel close-up

# VALVE: flash mid-run + pass ----------------------------------------------
show_tab(win.valve_tab)
t = win.valve_tab
set_running(t, 0.35, "Installing BLE wireless stack...")
t.log_viewer.append("Verify MCU ID: STM32WB (0x495) OK", "pass")
t.log_viewer.append("Check/upgrade FUS: v1.2.0 OK", "info")
t.log_viewer.append("Installing BLE wireless stack at 0x080C7000...", "info")
grab(t, "fig15_valve_flash.png")
finish_pass(t, {"fw_version": "2.2.0", "ble_mac": "34:B7:DA:6A:AD:54",
                "uid": "0123456789ABCDEF01234567"})
grab(t, "fig17_valve_pass.png")

# SENSOR: battery step + pass ----------------------------------------------
show_tab(win.sensor_tab)
t = win.sensor_tab
t.status_banner.set_status("running")
t.start_btn.setEnabled(False); t.abort_btn.setEnabled(True)
_seen_batt = False
for s in steps_of(t):
    t.step_list.update_step(s.id, "pass", "OK")
    if s.id == "validate_battery":
        t.step_list.update_step(s.id, "pass", "2.67V in range [2.5-3.3V]")
        _seen_batt = True
        break
t.log_viewer.append(">> BATT: 85% (2.67V, raw=1646)", "info")
t.log_viewer.append("Battery 2.67V in range [2.5-3.3V]", "pass")
grab(t, "fig20_sensor_battery.png")
finish_pass(t, {"fw_version": "1.0.1", "ble_mac": "00:80:E1:2A:3F:59",
                "uid": "002F005D5533500120393842"})
grab(t, "fig22_sensor_pass.png")

# FAIL example (reset hub, force a mismatch fail) --------------------------
show_tab(win.hub_tab)
t = win.hub_tab
t.step_list.reset_all()
t.log_viewer.clear()
st = steps_of(t)
for s in st[:2]:
    t.step_list.update_step(s.id, "pass", "OK")
if len(st) > 2:
    t.step_list.update_step(st[2].id, "fail", "not found in boot log")
t._result = {"base_mac": "34:B7:DA:6A:AD:54"}
t._on_fail("FW version mismatch: device reports v1.4.1, expected v1.4.2. "
           "Check that the correct firmware was flashed.")
grab(t, "fig23_fail_example.png")

# History tab with sample records ------------------------------------------
for rec in [
    {"device_type": "hub", "serial_number": "2625-000001", "uid": "34:B7:DA:6A:AD:54",
     "ble_mac": "", "fw_version": "1.4.2", "operator": "OP-0412", "work_order": "WO-2026-00042",
     "result": "PASS", "notes": ""},
    {"device_type": "valve", "serial_number": "2625-000002", "uid": "0123456789AB",
     "ble_mac": "34:B7:DA:6A:AD:54", "fw_version": "2.2.0", "operator": "OP-0412",
     "work_order": "WO-2026-00042", "result": "PASS", "notes": ""},
    {"device_type": "sensor", "serial_number": "", "uid": "002F005D5533500120393842",
     "ble_mac": "", "fw_version": "", "operator": "OP-0412", "work_order": "",
     "result": "FAIL", "notes": "BLE advertising not detected after flash"},
    {"device_type": "sensor", "serial_number": "2625-000003", "uid": "002F005D5533500120393842",
     "ble_mac": "00:80:E1:2A:3F:59", "fw_version": "1.0.1", "operator": "OP-0412",
     "work_order": "WO-2026-00042", "result": "PASS", "notes": ""},
]:
    win.record_logger.log(rec)
show_tab(win.history_tab)
win.history_tab._load_data()
pump(6)
grab(win.history_tab, "fig28_history.png")


# --- standalone widgets ----------------------------------------------------
# Fig 7 / 16 / 21: Operator Check dialogs (constructed, shown, NOT exec'd)
def grab_dialog(question: str, name: str) -> None:
    dlg = QuestionDialog(question)
    dlg.resize(560, 280)
    show_hidden(dlg)
    pump(6)
    grab(dlg, name)
    dlg.close()


grab_dialog("Is the LED on the WiFi Hub blinking?", "fig07_operator_check.png")
grab_dialog("Press the button on the valve.\nDid the servo actuate (valve moved)?",
            "fig16_valve_servo.png")
grab_dialog("Short the leak detection probes with a wet finger or wire.\n"
            "Did the sensor detect a leak? (Check UART log for 'LEAK DETECTED')",
            "fig21_sensor_leak.png")

# Fig 8: pre-flight warning message box
_mb = QMessageBox(QMessageBox.Icon.Warning, "Operator",
                  "Enter your Operator ID before starting.")
show_hidden(_mb); pump(6); grab(_mb, "fig08_warning_operator_id.png"); _mb.close()

# Fig 5: banner four-style legend (idle / running / pass / fail)
_bw = QWidget(); _bw.setStyleSheet("background:#ECEFF1;"); _bl = QVBoxLayout(_bw)
_bl.setContentsMargins(16, 16, 16, 16); _bl.setSpacing(10)
for stt in ["idle", "running", "pass", "fail"]:
    b = BigStatusBanner(); b.set_status(stt); _bl.addWidget(b)
_bw.resize(520, 400); show_hidden(_bw); pump(6)
grab(_bw, "fig05_banner_styles.png"); _bw.close()

# Fig 6: step-status legend (pending / running / pass / fail / skipped)
_sl = StepListWidget()
_legend = [
    {"id": "p", "name": "Pending  - not started yet"},
    {"id": "r", "name": "Running  - in progress"},
    {"id": "ok", "name": "Pass  - step succeeded"},
    {"id": "x", "name": "Fail  - step failed"},
    {"id": "sk", "name": "Skipped - not applicable (not a failure)"},
]
_sl.set_steps(_legend)
_sl.update_step("p", "pending"); _sl.update_step("r", "running")
_sl.update_step("ok", "pass"); _sl.update_step("x", "fail")
_sl.update_step("sk", "skipped")
_sl.resize(520, 200); show_hidden(_sl); pump(6)
grab(_sl, "fig06_step_legend.png"); _sl.close()


# --- authored diagram: QR payload anatomy (Fig 27) -------------------------
def make_qr_anatomy(path: Path) -> None:
    W, H = 1100, 430
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    try:
        fb = ImageFont.truetype("consola.ttf", 26)
        fs = ImageFont.truetype("segoeui.ttf", 22)
        fsb = ImageFont.truetype("segoeuib.ttf", 24)
    except Exception:
        fb = fs = fsb = ImageFont.load_default()
    d.text((30, 24), "QR payload = plain-text query string (the Watts app reads the text)",
           fill="#263238", font=fsb)
    fields = [
        ("id=LK-00:80:E1:2A:3F:59", "#2E7D32", "device id: type tag (LK-/VV-/GW-) + MAC"),
        ("&type=sensor", "#1565C0", "device type"),
        ("&hw=stm32wba-C", "#EF6C00", "MCU + hardware rev"),
        ("&sw=v1.0.1", "#6A1B9A", "device-reported firmware"),
    ]
    x, y = 30, 90
    for text, color, _cap in fields:
        w = int(d.textlength(text, font=fb)) + 24
        d.rectangle([x, y, x + w, y + 52], outline=color, width=3, fill="#FAFAFA")
        d.text((x + 12, y + 12), text, fill=color, font=fb)
        x += w + 6
        if x > W - 200:
            x = 30; y += 76
    yy = 200
    for text, color, cap in fields:
        d.rectangle([30, yy + 6, 54, yy + 30], outline=color, width=3, fill=color)
        d.text((66, yy), f"{text.lstrip('&').split('=')[0]}  -  {cap}", fill="#37474F", font=fs)
        yy += 40
    d.text((30, yy + 12),
           "Prefixes:  GW- = WiFi Hub    VV- = Valve    LK- = Leak Sensor",
           fill="#263238", font=fsb)
    img.save(str(path))
    results.append((path.name, "authored"))


make_qr_anatomy(ASSETS / "fig27_qr_anatomy.png")


# --- placeholders (physical photos / OS dialog / red-strip variant) --------
def make_placeholder(name: str, w: int, h: int, title: str, note: str) -> None:
    img = Image.new("RGB", (w, h), "#F5F5F5")
    d = ImageDraw.Draw(img)
    try:
        ft = ImageFont.truetype("segoeuib.ttf", 30)
        fn = ImageFont.truetype("segoeui.ttf", 20)
    except Exception:
        ft = fn = ImageFont.load_default()
    for i in range(6):  # thick dashed red border
        d.rectangle([6 + i, 6 + i, w - 7 - i, h - 7 - i], outline="#C62828")
    d.text((30, 30), "SCREENSHOT PLACEHOLDER", fill="#C62828", font=ft)
    d.text((30, 80), title, fill="#263238", font=ft)
    # wrap the note
    words, line, yy = note.split(), "", 140
    for wd in words:
        if d.textlength(line + " " + wd, font=fn) > w - 60:
            d.text((30, yy), line, fill="#37474F", font=fn); yy += 30; line = wd
        else:
            line = (line + " " + wd).strip()
    if line:
        d.text((30, yy), line, fill="#37474F", font=fn)
    img.save(str(ASSETS / name))
    results.append((name, "placeholder"))


make_placeholder("fig03b_firmware_red.png", 1180, 60,
                 "Firmware strip - RED (missing firmware)",
                 "Capture per Appendix B: rename firmware/manifest.yaml (or delete one .bin) "
                 "and relaunch; the affected device tag turns red. Restore afterwards.")
make_placeholder("fig10_hub_wiring.png", 900, 560,
                 "WiFi Hub - CP2102 USB-UART connection",
                 "Photo: CP2102 USB-UART adapter connected to the ESP32-S3 WiFi Hub board; "
                 "show TX/RX/GND/5V and the USB cable to the PC. ESD-safe handling.")
make_placeholder("fig14_valve_wiring.png", 900, 560,
                 "Valve - ST-Link SWD connection (one programmer only)",
                 "Photo: ST-Link debugger connected to the Valve board SWD header; only ONE "
                 "programmer attached. Optional ST-Link VCP UART for boot-log capture. ESD-safe.")
make_placeholder("fig19_coincell.png", 900, 560,
                 "Leak Sensor - coin-cell installation and polarity",
                 "Photo: coin cell inserted with correct + / - orientation into the Leak Sensor; "
                 "SAFETY - do not short the cell, observe polarity.")
make_placeholder("fig24_printed_label.png", 900, 460,
                 "Printed QR label (20 mm x 20 mm)",
                 "Photo of the printed label beside a ruler for scale: a 20 mm x 20 mm "
                 "QR-only label. There is no readable text - at 20 mm there is no room.")
make_placeholder("fig26_printer_setup.png", 820, 560,
                 "Printer Setup (selected printer backend)",
                 "Screenshot on the capture host: the dialog opened by 'Printer Setup' for "
                 "whichever printer is chosen in the Printer dropdown - the Windows "
                 "QPrintDialog for 'System printer (any)'.")

# ---------------------------------------------------------------------------
print("CAPTURE SUMMARY ({} figures):".format(len(results)))
for name, status in sorted(results):
    print(f"  {status:12s}  {name}")
ok = sum(1 for _, s in results if s in ("captured", "authored", "placeholder"))
print(f"OK={ok}/{len(results)}  assets_dir={ASSETS}")
