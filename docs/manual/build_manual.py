"""Build the eFloStop II Production Operator Manual (.docx) with python-docx.

Content is derived from the current tool source (citations tracked in the
screenshot manifest and the discovery notes). Figures are embedded from
docs/manual/assets/. Run from the project root:  python docs/manual/build_manual.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
OUT = HERE / "eFloStop_II_Production_Operator_Manual.docx"

DOC_ID = "EFS2-MFG-OM-001"
DOC_REV = "Rev A"
DOC_DATE = "2026-07-01"

FILES = {
    1: "fig01_full_window.png", 2: "fig02_operator_bar.png", 3: "fig03_firmware_green.png",
    "3b": "fig03b_firmware_red.png", 4: "fig04_hub_anatomy.png", 5: "fig05_banner_styles.png",
    6: "fig06_step_legend.png", 7: "fig07_operator_check.png", 8: "fig08_warning_operator_id.png",
    9: "fig09_hub_ready.png", 10: "fig10_hub_wiring.png", 11: "fig11_hub_running.png",
    12: "fig12_hub_pass.png", 13: "fig13_valve_ready.png", 14: "fig14_valve_wiring.png",
    15: "fig15_valve_flash.png", 16: "fig16_valve_servo.png", 17: "fig17_valve_pass.png",
    18: "fig18_sensor_ready.png", 19: "fig19_coincell.png", 20: "fig20_sensor_battery.png",
    21: "fig21_sensor_leak.png", 22: "fig22_sensor_pass.png", 23: "fig23_fail_example.png",
    24: "fig24_printed_label.png", 25: "fig25_qr_panel.png", "25b": "fig25b_qr_idle.png",
    26: "fig26_printer_setup.png", 27: "fig27_qr_anatomy.png", 28: "fig28_history.png",
}

doc = Document()

# --- base styles -----------------------------------------------------------
normal = doc.styles["Normal"]
normal.font.name = "Calibri"
normal.font.size = Pt(11)
for h, sz, col in [("Heading 1", 18, "1F3864"), ("Heading 2", 14, "1F4E79"),
                   ("Heading 3", 12, "2E5496")]:
    st = doc.styles[h]
    st.font.name = "Calibri"
    st.font.size = Pt(sz)
    st.font.color.rgb = RGBColor.from_string(col)
    st.font.bold = True


def _set_cell_shading(cell, fill_hex):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill_hex)
    cell._tc.get_or_add_tcPr().append(shd)


def para(text="", size=11, bold=False, italic=False, align=None, color=None, space_after=6):
    p = doc.add_paragraph()
    if align:
        p.alignment = align
    r = p.add_run(text)
    r.bold, r.italic = bold, italic
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = RGBColor.from_string(color)
    p.paragraph_format.space_after = Pt(space_after)
    return p


def bullet(text, level=0):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.left_indent = Inches(0.3 + 0.3 * level)
    p.add_run(text)
    return p


def step(n, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.35)
    p.paragraph_format.first_line_indent = Inches(-0.35)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(f"{n}.  ")
    r.bold = True
    _rich(p, text)
    return p


def _rich(p, text):
    """Render **bold** segments inside a step string."""
    parts = text.split("**")
    for i, seg in enumerate(parts):
        run = p.add_run(seg)
        run.bold = (i % 2 == 1)


def expect(text, good=True):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.7)
    p.paragraph_format.space_after = Pt(4)
    mark = p.add_run(("✔  " if good else "✘  "))
    mark.bold = True
    mark.font.color.rgb = RGBColor.from_string("2E7D32" if good else "C62828")
    r = p.add_run(text)
    r.font.size = Pt(10.5)
    return p


CALLOUT = {
    "WARNING": ("C62828", "FFEBEE", "⚠ WARNING"),
    "SAFETY": ("B71C1C", "FFEBEE", "⚠ SAFETY"),
    "CAUTION": ("EF6C00", "FFF3E0", "⚠ CAUTION"),
    "NOTE": ("1565C0", "E8F0FE", "ℹ NOTE"),
}


def callout(kind, text):
    border, fill, label = CALLOUT[kind]
    tbl = doc.add_table(rows=1, cols=1)
    tbl.autofit = True
    cell = tbl.cell(0, 0)
    _set_cell_shading(cell, fill)
    cell.paragraphs[0].text = ""
    lp = cell.paragraphs[0]
    lr = lp.add_run(label + "  ")
    lr.bold = True
    lr.font.color.rgb = RGBColor.from_string(border)
    _rich(lp, text)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return tbl


def figure(n, caption, max_w=6.3, max_h=6.4):
    path = ASSETS / FILES[n]
    iw, ih = Image.open(path).size
    w = max_w
    h = w * ih / iw
    if h > max_h:
        h = max_h
        w = h * iw / ih
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(path), width=Inches(w))
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cr = c.add_run(f"Figure {n}.  {caption}")
    cr.italic = True
    cr.font.size = Pt(9)
    cr.font.color.rgb = RGBColor.from_string("555555")
    c.paragraph_format.space_after = Pt(10)


def h1(t):
    doc.add_heading(t, level=1)


def h2(t):
    doc.add_heading(t, level=2)


def h3(t):
    doc.add_heading(t, level=3)


def page_break():
    doc.add_page_break()


def _field(paragraph, instr, placeholder=""):
    r = paragraph.add_run()
    for kind in ("begin",):
        fc = OxmlElement("w:fldChar")
        fc.set(qn("w:fldCharType"), kind)
        r._r.append(fc)
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = instr
    r._r.append(it)
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    r._r.append(sep)
    t = OxmlElement("w:t")
    t.text = placeholder
    r._r.append(t)
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    r._r.append(end)


# ===========================================================================
# COVER PAGE
# ===========================================================================
para("", space_after=40)
para("eFloStop II", size=40, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
     color="1F3864", space_after=2)
para("Production Programming & Test Tool", size=22, bold=True,
     align=WD_ALIGN_PARAGRAPH.CENTER, color="1F4E79", space_after=2)
para("Operator Manual", size=20, align=WD_ALIGN_PARAGRAPH.CENTER, color="555555",
     space_after=30)
para("Program • Functionally Test • Label the WiFi Hub, Valve, and Leak Sensor",
     size=12, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, color="555555", space_after=40)

# document-control table
ctl = doc.add_table(rows=4, cols=2)
ctl.style = "Light Grid Accent 1"
ctl.alignment = WD_ALIGN_PARAGRAPH.CENTER
for i, (k, v) in enumerate([
    ("Document ID", DOC_ID),
    ("Revision", DOC_REV),
    ("Issue date", DOC_DATE),
    ("Applies to", "eFloStop II Production Tool (all three device tabs)"),
]):
    ctl.cell(i, 0).paragraphs[0].add_run(k).bold = True
    ctl.cell(i, 1).paragraphs[0].add_run(v)

para("", space_after=14)
para("Document control note", size=11, bold=True, color="1565C0", space_after=2)
para("This is a controlled document. It carries NO fixed firmware version number. "
     "The tool's title bar shows a build/version string that the operator should "
     "DISREGARD; the firmware version to verify is the batch version supplied on the "
     "QA / build release note, which the operator types into the 'Expected FW version' "
     "field. The version reported by the device on screen is the source of truth.",
     size=10, space_after=14)

para("Revision history", size=11, bold=True, space_after=4)
rev = doc.add_table(rows=2, cols=4)
rev.style = "Light Grid Accent 1"
for j, hd in enumerate(["Rev", "Date", "Author", "Change summary"]):
    rev.cell(0, j).paragraphs[0].add_run(hd).bold = True
for j, v in enumerate(["A", DOC_DATE, "Manufacturing Engineering", "Initial release."]):
    rev.cell(1, j).paragraphs[0].add_run(v)
page_break()

# ===========================================================================
# TABLE OF CONTENTS
# ===========================================================================
h1("Table of Contents")
tp = doc.add_paragraph()
_field(tp, 'TOC \\o "1-3" \\h \\z \\u',
       "Right-click here and choose “Update Field” to build the table of contents.")
page_break()

# ===========================================================================
# 1. PURPOSE & SCOPE
# ===========================================================================
h1("1.  Purpose and Scope")
h2("1.1  Who this manual is for")
para("This manual is for production-floor operators. No engineering or firmware "
     "knowledge is assumed. Follow each numbered step exactly and in order. Where the "
     "manual says to click a button or read a status, the exact on-screen wording is "
     "shown in bold.")
h2("1.2  What the tool does")
para("For each device you connect, the eFloStop II Production Tool will, in one guided run:")
bullet("Flash (program) the firmware onto the board.")
bullet("Run a sequence of automatic tests plus a few manual checks you confirm.")
bullet("Generate a serial number and a QR-code label for the device.")
bullet("Record a PASS or FAIL result you can review later on the History tab.")
h2("1.3  The three device types")
para("The tool has one tab per device, plus a History tab: **WiFi Hub**, **Valve**, "
     "**Leak Sensor**, and **History**. Each device tab works the same way; the "
     "differences are called out in that device's chapter.")
h2("1.4  Out of scope")
para("This manual does not cover firmware development, editing the firmware manifest on "
     "the line, installing the tool, or repairing devices. If firmware files are missing "
     "or the tool will not start, refer to your station lead.")
page_break()

# ===========================================================================
# 2. PREREQUISITES & STATION SETUP
# ===========================================================================
h1("2.  Prerequisites and Station Setup")
para("Complete this section once when setting up a station, before programming any unit.")
h2("2.1  Software")
bullet("Windows PC with the eFloStop II Production Tool installed.")
bullet("STM32CubeProgrammer (the STM32_Programmer_CLI) — required for the Valve and "
       "Leak Sensor. (The Hub's flashing tool, esptool, ships with the tool.)")
h2("2.2  Programming hardware per device")
bullet("**WiFi Hub:** a CP2102 USB-UART adapter between the PC and the Hub board.")
bullet("**Valve:** an ST-Link debugger on the board's SWD header (used with "
       "STM32CubeProgrammer).")
bullet("**Leak Sensor:** an ST-Link debugger on SWD, plus an optional Tag-Connect lead "
       "for reading the UART log.")
bullet("**All devices:** a Windows Bluetooth adapter, used for the wireless (BLE) "
       "verification scans.")
callout("CAUTION", "Attach only **one** programmer (ST-Link) at a time. If more than one "
        "is connected, the programming tool may pick the wrong one.")
h2("2.3  USB / Bluetooth drivers")
callout("NOTE", "The exact USB-serial (CP210x), ST-Link, and Bluetooth-dongle driver "
        "names and versions are **not specified in the tool's documentation and must be "
        "confirmed by your station lead (TBD).** Do not assume a driver version; if a "
        "device or port is not detected, have the station lead verify the correct driver "
        "is installed.")
h2("2.4  Firmware files")
para("The tool reads its firmware from a firmware folder described by a file called "
     "manifest.yaml. When firmware is correctly staged, the firmware strip at the top of "
     "the window shows each device in **green**. The Valve and Leak Sensor each need "
     "**both** a debug and a production firmware binary; the Hub needs its four binaries.")
callout("CAUTION", "Stage firmware **strictly by the manifest**. Any firmware file list "
        "in the project README is out of date — it omits the debug binaries the tool "
        "requires and uses the wrong file extensions. Trust manifest.yaml, not the README.")
h2("2.5  Launch the tool")
step(1, "Start the eFloStop II Production Tool (double-click its shortcut, or run it as "
        "your station lead directs).")
step(2, "The main window opens (Figure 1). **Disregard the version number** shown in the "
        "window title bar.")
figure(1, "The main window: operator bar (top), firmware status strip, and the four tabs.")
step(3, "Confirm the firmware strip shows every device in **green**. A red tag means "
        "firmware is missing — see Section 8.1.")
h2("2.6  One-time printer setup")
para("The QR panel on every device tab has a **Printer** dropdown. Choose the label "
     "printer there once — the setting is shared by all three tabs and is remembered "
     "between sessions, so this is normally a one-off per PC. Then press **Printer "
     "Setup** to configure that printer (see Section 8.1).")
callout("NOTE", "If an entry reads \"— not detected\" or \"— no printer chosen\", that "
        "printer is not ready. Pick another, or press Printer Setup to configure it.")
page_break()

# ===========================================================================
# 3. SAFETY
# ===========================================================================
h1("3.  Safety — Read Before You Start")
para("These hazards are real on this line. Read them once here; they are repeated at the "
     "exact step where they apply.")
callout("WARNING", "**Electrostatic discharge (ESD).** You handle bare circuit boards "
        "(ESP32-S3, STM32WB, STM32WBA) and probe them. Wear a grounded wrist strap and "
        "work on an ESD-safe mat, or you may destroy the board.")
callout("WARNING", "**Coin-cell battery (Leak Sensor).** Observe polarity, never short "
        "the cell, and dispose of cells per site rules. A shorted coin cell can overheat.")
callout("WARNING", "**Motorized valve.** During the Valve's servo check the valve "
        "physically moves when you press its button. Keep fingers clear of the mechanism.")
callout("CAUTION", "Handle USB and programmer cables gently; do not hot-unplug a board "
        "mid-programming.")
page_break()

# ===========================================================================
# 4. HOW THE SCREEN WORKS
# ===========================================================================
h1("4.  How the Screen Works")
para("Every device tab is laid out the same way. Learn it once here; the device chapters "
     "then stay short.")
h2("4.1  Operator bar")
para("Along the top are **Operator** (your ID, e.g. OP-0412) and **Work Order** "
     "(optional). At the far right a status reads **No device connected** until a run "
     "starts.")
figure(2, "Operator bar: Operator ID (required) and Work Order (optional).", max_w=6.3)
callout("NOTE", "You **must** enter your Operator ID before starting a run, or the tool "
        "blocks you with **“Enter your Operator ID before starting.”**")
h2("4.2  Firmware status strip")
para("Below the operator bar, one tag per device shows firmware status: **green** = all "
     "files present, **red** = firmware missing. The **Refresh** button re-checks the "
     "firmware folder.")
figure(3, "Firmware strip with all firmware present (green).", max_w=6.3)
h2("4.3  The four tabs")
para("**WiFi Hub**, **Valve**, and **Leak Sensor** each program and test that device. "
     "**History** shows past results (Section 9).")
h2("4.4  A device tab, part by part")
para("Each device tab has, on the left: the **port** row and **Refresh**; the firmware "
     "panel; the **Expected FW version** box; the big **status banner**; the **step "
     "list**; and the **START** / **ABORT** buttons. On the right: the **log** and the "
     "**QR panel**.")
figure(4, "Anatomy of a device tab (WiFi Hub shown) in the READY state.")
h2("4.5  Reading the status banner")
para("The big banner shows one of four states: **READY** (gray), **RUNNING…** "
     "(blue), **PASS** (green), **FAIL** (red).")
figure(5, "The four status-banner styles.", max_w=3.4)
callout("NOTE", "There is no separate colour for an aborted run: **ABORTED** appears in "
        "the red FAIL style with the word ABORTED.")
h2("4.6  Reading the step list")
para("Each step shows a symbol: pending, running, pass, fail, or skipped. A **skipped** "
     "step is normal for optional checks — it is **not** a failure.")
figure(6, "Step-status symbols.", max_w=3.6)
h2("4.7  The Expected FW version box")
para("Type this batch's firmware version here so the tool checks the device reports that "
     "exact version. Leave it blank and the check is advisory only (the version is shown "
     "but not enforced).")
callout("CAUTION", "Type the version **exactly** as digits and dots, e.g. **1.0.0** — "
        "no leading “v”, no spaces. The check is case- and character-exact, so "
        "“V1.0.0” or a trailing space will FAIL a good unit. Get the batch "
        "version from the QA / build release note, not from this manual.")
h2("4.8  The Operator Check dialog")
para("For manual checks the tool shows a large **Operator Check** dialog with a question "
     "and big green **YES** / red **NO** buttons. Answer honestly by what you observe.")
figure(7, "The Operator Check YES / NO dialog.", max_w=3.6)
h2("4.9  What to do on a FAIL")
para("There is **no** automatic retry and **no** per-step retry. If a run fails: fix the "
     "cause and press **START** to run the whole sequence again, or set the unit aside as "
     "a reject. **ABORT** stops a run in progress.")
callout("NOTE", "If a step stays blue (**RUNNING…**) and nothing changes for about "
        "30 seconds, press **ABORT**, reseat the programmer/cable, press **Refresh**, then "
        "**START** again.")
page_break()


# ===========================================================================
# Device chapter helper
# ===========================================================================
def qr_note(prefix):
    para("The QR code is a plain-text string the phone/commissioning (Watts) app reads. "
         f"For this device it begins **id={prefix}-** followed by the device address, then "
         "**&type=**, **&hw=**, and **&sw=** (the device-reported firmware). See Figure 27 "
         "for the field breakdown.")


# ===========================================================================
# 5. WIFI HUB
# ===========================================================================
h1("5.  WiFi Hub — Program, Test, and Label")
para("This chapter programs, tests, and labels one WiFi Hub on the **WiFi Hub** tab. Do "
     "the steps in order.")
h2("5.1  Connect the Hub")
step(1, "Wearing an ESD strap, connect the Hub to the PC with the **CP2102 USB-UART** "
        "adapter (Figure 10).")
figure(10, "Connecting the WiFi Hub via the CP2102 USB-UART adapter.", max_w=4.5)
step(2, "Open the **WiFi Hub** tab. In the **Serial Port:** drop-down choose the Hub's "
        "port. If the list is empty, press **Refresh**.")
figure(9, "The WiFi Hub tab in the READY state.")
expect("The port appears in the **Serial Port:** list.")
expect("**“No CP210x ports found”** means nothing is detected — check the "
       "cable/driver (Section 2.3), then Refresh.", good=False)
h2("5.2  Pre-flight checks")
step(3, "Enter your **Operator ID** in the operator bar.")
step(4, "Confirm the firmware panel shows **All files present**.")
step(5, "Type the batch version into **Expected FW version** (Section 4.7).")
h2("5.3  Program the Hub (Flow A)")
step(6, "Press the big blue **START** button.")
step(7, "Watch the step list. The Hub flashes in one step — **Flash firmware "
        "(esptool)** — which erases and writes all firmware and reads the board's MAC "
        "address.")
callout("NOTE", "The WiFi Hub does **not** re-flash a second time; the Valve and Leak "
        "Sensor do.")
figure(11, "A WiFi Hub run in progress (RUNNING banner and boot log).")
h2("5.4  Functional test (Flow B)")
para("After flashing, the tool captures the Hub's start-up (boot) log and checks it, in "
     "this on-screen order:")
bullet("**Capture boot log** → **Parse app version** → **Verify FW version "
       "(boot log)**")
bullet("**Read base MAC** → **Parse Gateway ID from log**")
bullet("**LoRa SX1262 init check** and **BLE NimBLE init check** (either may show "
       "**skipped** — that is OK)")
callout("NOTE", "The Hub does not run an automatic BLE advertising scan. The separate "
        "**BLE Scan** button on this tab is only a 5-second diagnostic and is not part of "
        "PASS/FAIL.")
step(8, "When the **Operator Check** dialog asks **“Is the LED on the WiFi Hub "
        "blinking?”**, answer **YES** if it blinks, else **NO**.")
h2("5.5  PASS and QR label (Flow C)")
step(9, "On PASS the banner turns green and a QR code appears on the right with a caption "
        "showing **SN**, **ID**, **WiFi** SSID, and **FW**.")
figure(12, "A WiFi Hub PASS with its generated QR label.")
qr_note("GW")
step(10, "Press **Print Label** to print the 20 mm QR label. The first time on this "
         "PC, pick the printer in the **Printer** dropdown and press **Printer "
         "Setup** (Section 8.1).")
para("The Hub's serial number begins **EFS2H**. Apply the printed label to the unit. The "
     "app links the Hub by scanning this QR.")
h2("5.6  If the Hub fails")
para("Follow the FAIL rule in Section 4.9 and the string-matched fixes in Section 8.")
page_break()

# ===========================================================================
# 6. VALVE
# ===========================================================================
h1("6.  Valve — Program, Test, and Label")
para("This chapter programs, tests, and labels one Valve on the **Valve** tab. The Valve "
     "is flashed twice: a debug build for testing, then the production build at the end.")
callout("WARNING", "**ESD:** wear a wrist strap. The Valve's **servo check** later will "
        "physically move the valve — keep fingers clear.")
h2("6.1  Connect the Valve")
step(1, "Connect the Valve with an **ST-Link** on the SWD header (only **one** programmer "
        "attached). Figure 14.")
figure(14, "Connecting the Valve via ST-Link SWD.", max_w=4.5)
step(2, "Open the **Valve** tab. The **UART Port (ST-Link VCP):** drop-down is only for "
        "capturing the boot log; choose the port, or choose **“(Skip UART "
        "capture)”**. Flashing itself goes over SWD, not this port.")
figure(13, "The Valve tab in the READY state.")
h2("6.2  Pre-flight checks")
step(3, "Enter your **Operator ID**.")
step(4, "Confirm the firmware panel shows **All files present** (the Valve needs both "
        "debug and production binaries).")
step(5, "Type the batch version into **Expected FW version**.")
h2("6.3  Program the Valve (Flow A)")
step(6, "Press **START**. The step list runs, in order: **Verify MCU ID (STM32WB)**, "
        "**Check/upgrade FUS**, **Install BLE wireless stack**, **Flash application** "
        "(debug), **Read 96-bit UID**, **Reset & wait for boot**.")
callout("NOTE", "**Check/upgrade FUS** and **Install BLE wireless stack** may show "
        "**skipped** if already present on the board — that is normal.")
figure(15, "The Valve flash sequence in progress.")
h2("6.4  Functional test (Flow B)")
para("The tool then captures the boot log and verifies the radio, in this order:")
bullet("**Capture UART boot log** → **Parse BD address from UART**")
bullet("**BLE advertising scan** (about 15 seconds) → **Read BLE public address**")
bullet("**Cross-verify BD address (UART vs BLE)** → **Read FW version via DIS** "
       "→ **Verify FW version (DIS)**")
h2("6.5  Manual checks")
step(7, "**“Is the LED on the Valve board visible?”** — YES / NO.")
callout("WARNING", "Motorized valve — keep fingers clear during the next step.")
step(8, "**“Press the button on the valve. Did the servo actuate (valve moved)?”** "
        "— press the valve button; answer YES only if the valve physically moved.")
figure(16, "The servo-check Operator Check dialog.", max_w=3.8)
step(9, "**“Did you hear the buzzer?”** — YES / NO.")
h2("6.6  Production re-flash and PASS")
step(10, "As the final automatic step the tool flashes the **production** firmware "
         "(low-power). The banner then turns green (PASS) and the QR appears.")
figure(17, "A Valve PASS with its generated QR label.")
qr_note("VV")
step(11, "**Print Label**. The Valve's serial number begins **EFS2V**. Apply the label.")
h2("6.7  If the Valve fails")
para("Follow Section 4.9 and Section 8. A repeated **Wrong MCU** or **BD address "
     "mismatch** means the unit is a reject.")
page_break()

# ===========================================================================
# 7. LEAK SENSOR
# ===========================================================================
h1("7.  Leak Sensor — Program, Test, and Label")
para("This chapter programs, tests, and labels one Leak Sensor on the **Leak Sensor** "
     "tab. Like the Valve, it is flashed with a debug build for testing and a production "
     "build at the end, and it adds a battery check and a leak-probe test.")
callout("WARNING", "**Coin cell + ESD.** Observe cell polarity and never short it; wear a "
        "wrist strap.")
h2("7.1  Prepare and connect")
step(1, "Install the coin cell with correct polarity (Figure 19).")
figure(19, "Coin-cell installation and polarity.", max_w=4.2)
step(2, "Connect the ST-Link on SWD (one programmer). Optionally connect the **UART Port "
        "(Tag-Connect):** lead for the log.")
figure(18, "The Leak Sensor tab in the READY state.")
expect("**“No serial ports found”** in the UART list means no lead is detected "
       "— this is OK if you are not capturing the log.", good=True)
h2("7.2  Pre-flight checks")
step(3, "Enter your **Operator ID**; confirm firmware **All files present**; type the "
        "batch version into **Expected FW version**.")
h2("7.3  Program the Leak Sensor (Flow A)")
step(4, "Press **START**. Steps run in order: **Verify MCU ID (STM32WBA)**, **Flash "
        "application** (debug), **Read 96-bit UID**, then a reset.")
h2("7.4  Functional test (Flow B)")
para("The tool captures the UART log and checks, in this order:")
bullet("**Reset & capture UART log** → **Parse app version** → **Parse BLE "
       "address** (this one must be found in the log)")
bullet("**Parse battery** → **Validate battery range (2.5-3.3V)**")
bullet("**BLE advertising scan** (about 15 s) → **Verify FW version (BLE mfg data)**")
figure(20, "The battery-range validation step passing.")
callout("NOTE", "The battery must read between **2.5 V and 3.3 V**. Outside that range the "
        "step fails with **“<v>V outside range [2.5-3.3V]”** and the unit is a "
        "reject (try a fresh cell first).")
h2("7.5  Manual checks")
step(5, "**“Is the LED on the Leak Sensor visible?”** — YES / NO.")
step(6, "**“Did you hear the buzzer?”** — YES / NO.")
step(7, "**“Short the leak detection probes with a wet finger or wire. Did the sensor "
        "detect a leak?”** — short the probes; answer YES only if a leak is "
        "detected (the UART log shows **LEAK DETECTED**).")
figure(21, "The leak-probe Operator Check dialog.", max_w=3.8)
h2("7.6  Production re-flash and PASS")
step(8, "The tool flashes the **production (release)** firmware as the final step, then "
        "shows PASS and the QR.")
figure(22, "A Leak Sensor PASS with its generated QR label.")
qr_note("LK")
step(9, "**Print Label**. The Leak Sensor's serial number begins **EFS2S**. Apply the "
        "label.")
h2("7.7  If the Leak Sensor fails")
para("Follow Section 4.9 and Section 8.")
page_break()

# ===========================================================================
# QR reference (shared)
# ===========================================================================
h1("8.  The QR Label and App Linking")
para("Every device's QR encodes the same kind of plain-text string. The phone / "
     "commissioning app reads the text directly and identifies the device from the "
     "**id=** prefix: **GW-** = WiFi Hub, **VV-** = Valve, **LK-** = Leak Sensor.")
figure(27, "Anatomy of the QR payload string.", max_w=6.3)
para("The QR panel shows **No QR generated** until a unit passes; after PASS it shows the "
     "code with a **Printer** dropdown and the **Print Label** and **Printer Setup** "
     "buttons.")
figure(25, "The QR panel after a PASS (Printer dropdown, Print Label, Printer Setup).",
       max_w=3.4)
h2("8.1  Printing")
para("Pick the label printer in the **Printer** dropdown. The choice is shared by all "
     "three device tabs and is remembered between sessions. Then press **Printer Setup** "
     "to configure that printer — for a normal Windows printer this is the standard "
     "Windows print dialog (Figure 26); a dedicated label printer shows its own settings "
     "instead.")
para("**Print Label** then prints a **20 mm x 20 mm** label carrying the QR code only "
     "(Figure 24). There is no readable text on the label — at 20 mm there is no room "
     "for any, and the on-screen caption is where the operator reads the SN and ID.")
figure(26, "The Printer Setup dialog for the selected printer.", max_w=3.6)
figure(24, "A printed 20 mm QR label.", max_w=4.5)
h2("8.2  Print warnings")
para("The tool checks the label size before every print and shows **at most one** of "
     "these. Both default to **No** — answering No cancels the print and changes nothing.")
bullet("**Label size is not 20 mm** — the printer's page is not the 20 mm label stock. "
       "Load 20 mm labels or select the right media in Printer Setup.")
bullet("**QR would print under 20 mm** — the printer cannot mark all the way to the edge, "
       "so the QR would come out smaller than 20 mm and may not scan. The message names "
       "the exact size it would print at. Use a full-bleed label printer.")
para("**Print Error — the printer reported no printable area** cannot be overridden: the "
     "print is cancelled. **Print Error — could not start printing** means the printer "
     "was not reachable; check it is powered on and connected.")
page_break()

# ===========================================================================
# 9. TROUBLESHOOTING
# ===========================================================================
h1("9.  Troubleshooting")
para("Find the exact words you see on screen in the left column.")

tt = doc.add_table(rows=1, cols=3)
tt.style = "Light Grid Accent 1"
for j, hd in enumerate(["On-screen message", "Means", "What to do"]):
    tt.cell(0, j).paragraphs[0].add_run(hd).bold = True
TROUBLE = [
    ("Enter your Operator ID before starting.", "No Operator ID entered.",
     "Type your Operator ID in the operator bar, then START."),
    ("Select a serial port first. (Hub)", "No port chosen.", "Pick the port; Refresh if empty."),
    ("Firmware files missing. Check firmware folder. (Hub)",
     "Hub firmware not staged.", "Tell your station lead; stage firmware per manifest, Refresh."),
    ("Debug firmware (application_debug) missing. / Production firmware (application) missing. (Valve, Sensor)",
     "A required binary is absent.", "Station lead to stage the missing binary. (The Hub never shows these — it has no debug binary.)"),
    ("Leak sensor firmware not configured. / Valve firmware not configured.",
     "That device is not in the manifest.", "Station lead to fix the manifest."),
    ("No CP210x ports found / No serial ports found", "No adapter/lead detected.",
     "Check cable and driver (Section 2.3); Refresh."),
    ("Cannot open <port> after 3s retry", "The port is busy or gone.",
     "ABORT, reseat the cable, Refresh, START. If a step hangs ~30 s, do the same."),
    ("Wrong MCU! Expected STM32WB (0x495) / STM32WBA (0x492)", "Wrong board on the fixture.",
     "Confirm you have the correct device; if it repeats, reject the unit."),
    ("No BLE device found / BLE advertising not detected after flash",
     "The radio did not advertise.", "Re-run once; check the Bluetooth adapter. Persistent = reject."),
    ("BD address mismatch! UART reports X but BLE scan found Y (Valve)",
     "UART and BLE addresses disagree.", "Reject the unit."),
    ("FW version mismatch: device reports v<x>, expected v<y>.",
     "Device version ≠ what you typed.", "First re-check the Expected FW field for a typo (Section 4.7). If correct, the wrong firmware was flashed — re-run or reject."),
    ("<v>V outside range [2.5-3.3V] (Sensor)", "Battery out of range.",
     "Try a fresh cell; if still out of range, reject."),
    ("Operator: LED not visible / Servo did not move / Buzzer not heard / Leak probe test failed",
     "You answered NO to a manual check.", "Reject the unit (or re-seat and re-run if you suspect a fixture issue)."),
    ("Aborted by operator", "You pressed ABORT.", "Fix the cause and START to re-run."),
    ("Print Error — Could not start printing.", "Printer not available.",
     "Check the printer is on/connected; re-open Printer Setup."),
]
for msg, mean, fix in TROUBLE:
    row = tt.add_row().cells
    row[0].paragraphs[0].add_run(msg).font.size = Pt(9.5)
    row[1].paragraphs[0].add_run(mean).font.size = Pt(9.5)
    row[2].paragraphs[0].add_run(fix).font.size = Pt(9.5)
para("")
figure(23, "A FAIL: red banner and a FAIL line in the log.")
callout("NOTE", "Golden rule: a FAIL means **fix and press START** to re-run the whole "
        "sequence. A repeated wrong-MCU, address-mismatch, or out-of-range battery means "
        "set the unit aside as a **reject**.")
page_break()

# ===========================================================================
# 10. HISTORY
# ===========================================================================
h1("10.  Reviewing Records (History Tab)")
para("Every run — PASS or FAIL — is recorded. Open the **History** tab to review "
     "and export.")
figure(28, "The History tab: filters, stats, records, and Export CSV.")
step(1, "Filter with the **Device** and **Result** drop-downs. The **Total / Pass / "
        "Fail** counts update.")
step(2, "Read the 10 columns: Timestamp, Device, Serial Number, UID, BLE MAC, FW Version, "
        "Operator, Work Order, Result, Notes. PASS is green, FAIL is red.")
step(3, "Use **< Previous / Next >** to page through records, and **Refresh** to reload.")
step(4, "Press **Export CSV**, choose a file, and confirm; the tool reports **Export "
        "Complete**. Do this at end of shift for QA.")
page_break()

# ===========================================================================
# 11. GLOSSARY
# ===========================================================================
h1("11.  Glossary")
GLOSS = [
    ("BLE", "Bluetooth Low Energy — the short-range radio the devices use."),
    ("BD address / BLE MAC", "The device's unique Bluetooth address."),
    ("Boot log", "Text a device prints as it starts, captured over the UART lead."),
    ("Debug vs production firmware", "A test build (used during the run) vs the final "
     "low-power build flashed last."),
    ("DIS", "Device Information Service — a BLE service the Valve reports its firmware "
     "version through."),
    ("ESP32-S3 / STM32WB / STM32WBA", "The microchips in the Hub / Valve / Leak Sensor."),
    ("FUS", "Firmware Upgrade Service on the STM32WB — checked/updated before the BLE "
     "stack."),
    ("Gateway ID", "The Hub's identity (begins GW-), used in its QR."),
    ("Manifest", "manifest.yaml — the file that tells the tool which firmware to use."),
    ("QR payload", "The plain text encoded in the QR (id=&type=&hw=&sw=)."),
    ("ST-Link / SWD", "The debugger and the wiring standard used to flash the STM32 boards."),
    ("Tag-Connect", "A no-solder probe lead used to read the Leak Sensor's UART log."),
    ("UART / VCP / CP2102", "A serial connection / virtual COM port / the USB-serial "
     "adapter chip used for it."),
    ("UID", "A unique ID number burned into each STM32 chip."),
    ("Watts app", "The phone/commissioning app that scans the QR to link a device."),
]
gt = doc.add_table(rows=1, cols=2)
gt.style = "Light Grid Accent 1"
gt.cell(0, 0).paragraphs[0].add_run("Term").bold = True
gt.cell(0, 1).paragraphs[0].add_run("Meaning").bold = True
for term, mean in GLOSS:
    r = gt.add_row().cells
    r[0].paragraphs[0].add_run(term).bold = True
    r[1].paragraphs[0].add_run(mean)
page_break()

# ===========================================================================
# APPENDIX A — QUICK REFERENCE
# ===========================================================================
h1("Appendix A — Quick Reference Cards")
qa = doc.add_table(rows=1, cols=4)
qa.style = "Light Grid Accent 1"
for j, hd in enumerate(["", "WiFi Hub", "Valve", "Leak Sensor"]):
    qa.cell(0, j).paragraphs[0].add_run(hd).bold = True
ROWS = [
    ("Tab", "WiFi Hub", "Valve", "Leak Sensor"),
    ("Port label", "Serial Port:", "UART Port (ST-Link VCP):", "UART Port (Tag-Connect):"),
    ("Programmer", "CP2102 USB-UART", "ST-Link SWD", "ST-Link SWD (+Tag-Connect)"),
    ("Manual checks", "LED", "LED, Servo, Buzzer", "LED, Buzzer, Leak-probe"),
    ("Battery check", "—", "—", "2.5-3.3 V"),
    ("Production re-flash", "No", "Yes", "Yes"),
    ("Serial prefix", "EFS2H", "EFS2V", "EFS2S"),
    ("QR id prefix", "GW-", "VV-", "LK-"),
]
for label, a, b, c in ROWS:
    r = qa.add_row().cells
    r[0].paragraphs[0].add_run(label).bold = True
    for k, v in enumerate([a, b, c]):
        r[k + 1].paragraphs[0].add_run(v)
page_break()

# ===========================================================================
# APPENDIX B — SCREENSHOT CAPTURE GUIDE
# ===========================================================================
h1("Appendix B — Screenshot & Figure Capture Guide")
para("Most figures were captured automatically from the live tool UI with the capture "
     "helper at docs/manual/capture/capture.py (no hardware needed). This appendix tells a "
     "human how to reproduce every figure and how to replace the placeholders. **Always "
     "caption a figure with the exact on-screen text — never paraphrase or shorten it.**")
h2("B.1  Auto-captured figures")
para("Run  python docs/manual/capture/capture.py  from the project root. It renders the "
     "tool on the native Windows platform with WA_DontShowOnScreen (no windows appear), "
     "using the real firmware manifest for the green firmware state, and writes PNGs to "
     "docs/manual/assets/. Idle/READY tabs, the operator bar, the firmware strip, the "
     "Operator Check dialog, the banner and step legends, the warning dialog, and the "
     "empty QR panel all come from here directly.")
h2("B.2  Run-state figures (mock-driven)")
para("RUNNING / PASS / FAIL banners, populated step rows and log, and the populated QR "
     "only exist while a worker runs. The helper reproduces them by calling each tab's own "
     "UI methods (status_banner.set_status, step_list.update_step, log_viewer.append, and "
     "_finish_pass / _on_fail) with canned data — no real flasher, BLE, or serial "
     "worker. To re-shoot on a live line instead, photograph a real qualifying run per "
     "device.")
h2("B.3  Placeholders to replace")
bt = doc.add_table(rows=1, cols=2)
bt.style = "Light Grid Accent 1"
bt.cell(0, 0).paragraphs[0].add_run("Figure").bold = True
bt.cell(0, 1).paragraphs[0].add_run("How to produce it").bold = True
PLACE = [
    ("3b — red firmware strip", "Temporarily rename firmware/manifest.yaml (or delete one .bin), relaunch, screenshot the strip, then restore."),
    ("10 — Hub wiring", "Photo of the CP2102 USB-UART adapter connected to the ESP32-S3 Hub (TX/RX/GND/5V + USB to PC)."),
    ("14 — Valve wiring", "Photo of the ST-Link on the Valve SWD header, one programmer only."),
    ("19 — Coin cell", "Photo of the coin cell installed with correct polarity in the Leak Sensor."),
    ("24 — Printed label", "Photo of the printed 20 mm x 20 mm QR-only label, next to a ruler for scale."),
    ("26 — Printer Setup", "Screenshot of the dialog opened by Printer Setup for the selected printer (the Windows print dialog for \"System printer (any)\")."),
]
for fg, how in PLACE:
    r = bt.add_row().cells
    r[0].paragraphs[0].add_run(fg)
    r[1].paragraphs[0].add_run(how)
para("")
callout("NOTE", "Ignore the tool's stale docs when documenting: the base64/JSON QR spec in "
        "docs/QR_PAYLOAD_SPEC.md is not the live behaviour. The real QR is the plain-text "
        "query string and the real print path is the 20 mm QR-only label, produced by the "
        "printer backend selected in the QR panel (see docs/PRINTER_BACKENDS.md).")

# ===========================================================================
# HEADER / FOOTER + update-fields-on-open
# ===========================================================================
sec = doc.sections[0]
hdr = sec.header.paragraphs[0]
hdr.text = f"eFloStop II Production Operator Manual\t\t{DOC_ID}  {DOC_REV}"
for r in hdr.runs:
    r.font.size = Pt(8)
    r.font.color.rgb = RGBColor.from_string("777777")

ftr = sec.footer.paragraphs[0]
ftr.alignment = WD_ALIGN_PARAGRAPH.CENTER
ftr.add_run(f"{DOC_ID} {DOC_REV}   •   Page ")
_field(ftr, "PAGE", "1")
ftr.add_run(" of ")
_field(ftr, "NUMPAGES", "1")
for r in ftr.runs:
    r.font.size = Pt(8)
    r.font.color.rgb = RGBColor.from_string("777777")

# make Word rebuild the TOC / page fields when the document is opened
upd = OxmlElement("w:updateFields")
upd.set(qn("w:val"), "true")
doc.settings.element.append(upd)

doc.save(str(OUT))
print("SAVED:", OUT)
print("figures embedded:", sum(1 for _ in FILES))
