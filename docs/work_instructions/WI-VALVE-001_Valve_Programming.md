# WI-VALVE-001 — eFloStop II Valve Board: Programming & Functional Test

**Work Instruction — Trial Assembly (10 boards)**

| | |
|---|---|
| **Document** | WI-VALVE-001 |
| **Revision** | C |
| **Applies to** | eFloStop II BLE Valve board (STM32WB5MMGH6TR), SKU `EFS2-VLV-1IN` |
| **Tool** | eFloStop II Production Tool — **Valve** tab |
| **Quantity** | 10 boards (trial assembly) |
| **Prepared for** | Lex |
| **Date** | ______________ |

---

## 1. Purpose

This instruction covers programming and functional testing of eFloStop II Valve boards using the eFloStop II Production Tool, and printing the QR label for each board that passes.

Each board is programmed **twice** by design:

1. **Debug firmware** is flashed first — it prints diagnostics over UART so the tool can verify the Bluetooth address and firmware version.
2. After the LED / servo / buzzer checks pass, the tool automatically re-flashes the board with **production (low-power) firmware**.

> **A board that finishes with a green PASS is left running production firmware.** If a run fails or is aborted part-way, the board is still running *debug* firmware and **must be re-run from the start** before it can be shipped.

### 1.1 Read this first — four rules

| # | Rule |
|---|---|
| 1 | **Only ONE valve board powered at a time.** Power down every other valve board *and* the WiFi Hub. The tool identifies boards over Bluetooth, and other powered boards can interfere with the check. |
| 2 | **Always select the ST-Link VCP COM port** in the UART Port box. The tool will refuse to start without it. |
| 3 | **Never leave "Expected FW version" blank** for a shippable board (see §2.3). |
| 4 | **Once an operator question appears, the only way out is YES or NO.** ABORT cannot be clicked while a question is on screen, and answering NO fails the board (see §4.5). |

---

## 2. What you need

### 2.1 PC (Windows)

| Item | Requirement |
|---|---|
| Production Tool | `dist\eFloStop_Production_Tool\eFloStop_Production_Tool.exe` |
| STM32CubeProgrammer | Must be installed at `C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe` |
| Bluetooth | **A working, enabled BLE (Bluetooth 4.0+) adapter is mandatory.** The tool connects to each board over Bluetooth to verify it. Classic-Bluetooth-only adapters will not work. |
| ST-Link drivers | Installed (ST-Link V2-1 / V3 / on-board probe) |

> ⚠️ **Check Bluetooth is switched ON in Windows before starting.** If the radio is off or missing, *every* board will fail at the `BLE advertising scan` step even though flashing worked perfectly.

### 2.2 Hardware

- ST-Link debug probe (V2-1, V3, or on-board) with **SWD** connection to the valve board
- **USB cable from the ST-Link to the PC** — this also provides the UART (Virtual COM Port) the tool reads
- Valve board power per the standard bench setup: ______________________
- 10 × valve boards
- **Printer for the QR labels.** For this trial a normal office printer is being used, so you will also need
  plain A4/Letter paper (or A4 label sheets), scissors/cutter, a ruler, and adhesive to fix the cut labels — see §6.6

### 2.3 Batch parameters — fill in before starting

| Field | Value |
|---|---|
| **Operator ID** (typed into the tool) | ______________________ |
| **Work Order** (optional) | ______________________ |
| **Expected FW version** (typed into the tool) | ______________________ |

> ⚠️ **The Expected FW version must be supplied by engineering before the batch starts — do not leave it blank.**
> The comparison is **exact and case-sensitive**: `1.0.2` will not match `v1.0.2`.
> If the field is left blank, the tool still shows a green ✔ on *Verify FW version (DIS)* with the detail `Got v… (no expected set)` — that is a tick that **compared nothing**, and the board's firmware would be unverified.

---

## 3. One-time bench setup

**Step 3.1** — Connect the ST-Link to the PC by USB, and to the valve board via SWD.

**Step 3.2** — Power the valve board. **Confirm no other valve board and no WiFi Hub is powered on the bench** (Rule 1).

**Step 3.3** — Launch `eFloStop_Production_Tool.exe`.

![Fig 1 — Production Tool main window, Valve tab](screenshots/fig-01-main-window-valve-tab.png)
*Figure 1 — Main window with the **Valve** tab selected.*

**Step 3.4** — Type your operator ID into the **Operator:** field in the dark bar at the top (placeholder `Enter operator ID (e.g. OP-0412)`). Fill in **Work Order:** if you have one.

![Fig 2 — Operator bar](screenshots/fig-02-operator-bar.png)
*Figure 2 — Operator bar. The tool will not start a run until the Operator field is filled in.*

**Step 3.5** — Check the **Firmware:** strip below the operator bar. The `valve` tag must be **green**. If it is red, firmware files are missing — stop and escalate.

![Fig 3 — Firmware strip, valve green](screenshots/fig-03-firmware-strip.png)
*Figure 3 — Firmware status strip. `valve` must be green before programming.*

**Step 3.6** — Select the **Valve** tab.

---

## 4. Per-board procedure

Repeat this whole section for each of the 10 boards.

### Step 4.1 — Connect the board

Connect the next valve board to the ST-Link (SWD) and apply power.

**Confirm again that this is the only powered valve board on the bench** (Rule 1).

### Step 4.2 — Select the UART port ⚠️ **critical**

Click **Refresh**, then choose the **ST-Link VCP** COM port from the **UART Port (ST-Link VCP):** drop-down.

![Fig 4 — UART port drop-down](screenshots/fig-04-uart-port-dropdown.png)
*Figure 4 — UART Port drop-down showing the ST-Link Virtual COM Port.*

> ⚠️ **Do NOT choose "(Skip UART capture)".**
> The tool reads the board's Bluetooth address from the UART log and uses it to identify *this exact board*. Without it a board cannot be verified, so **the tool will refuse to start** and show:
> *"Select the ST-Link VCP port before starting."*
>
> If several COM ports are listed, pick the one identified as **ST-Link / STMicroelectronics**. If no ST-Link port appears at all, the ST-Link USB connection or driver is at fault — press **Refresh** first (the list is only rebuilt when the tool starts and when you press Refresh), then fix the connection if it is still missing.

### Step 4.3 — Enter the expected firmware version

Type the batch value from §2.3 into **Expected FW version** (placeholder `X.Y.Z`). Do not leave it blank.

![Fig 5 — Expected FW version field](screenshots/fig-05-expected-fw-version.png)
*Figure 5 — Expected FW version field.*

### Step 4.4 — Start the run

Press the blue **START** button. The banner changes to **RUNNING...** and the steps begin.

![Fig 6 — Run in progress](screenshots/fig-06-run-in-progress.png)
*Figure 6 — Run in progress. Step symbols: `○` not started · `◔` running · `✔` passed · `✘` failed · `─` skipped.*

**Do not touch the board or cables during flashing.** The tool now performs, without operator input:

| # | Step shown on screen | What it does |
|---|---|---|
| 1 | Verify MCU ID (STM32WB) | Confirms an STM32WB is connected |
| 2 | Check/upgrade FUS | Checks the ST firmware upgrade service (may say *Stack already running* — normal on a re-run) |
| 3 | Install BLE wireless stack | Installs the Bluetooth stack (skipped if already present) |
| 4 | Flash application firmware | Flashes the **debug** firmware |
| 5 | Read 96-bit UID | Reads the chip's unique ID |
| 6 | Reset & wait for boot | Resets the board |
| 7 | Capture UART boot log | Listens on the COM port (~15 s) |
| 8 | Parse BD address from UART | Extracts the Bluetooth address |
| 9 | BLE advertising scan | Finds the board over Bluetooth (~15 s) |
| 10 | Read BLE public address | Records the Bluetooth address |
| 11 | Cross-verify BD address (UART vs BLE) | Confirms the UART and Bluetooth addresses agree |
| 12 | Read FW version via DIS | Reads the firmware version over Bluetooth |
| 13 | Verify FW version (DIS) | Compares against your **Expected FW version** |

Steps 14–16 are the operator checks (§4.5) and step 17 is the production re-flash (§4.6).

> ℹ️ Steps 2 and 3 take noticeably longer on a **brand-new blank board** (the Bluetooth stack is being installed — allow up to 5 minutes). On boards that have been programmed before, these are skipped and the run is much faster.

### Step 4.5 — Answer the three operator checks

The tool now pauses three times with an **Operator Check** dialog. Each has **YES** and **NO** buttons.

> ⚠️ **Answering NO immediately fails the board and ends the run — there is no retry.** Closing the dialog or pressing `Esc` counts as **NO**.
> While a question is on screen you **cannot** press ABORT — the only way forward is YES or NO. Check the board properly, then answer.

**a) Step `LED visible?`** — dialog asks *"Is the LED on the Valve board visible?"*

![Fig 7 — LED check dialog](screenshots/fig-07-led-check-dialog.png)
*Figure 7 — LED check.*

**b) Step `Servo actuation — press button, confirm valve moved`** — dialog shows two lines:

> *Press the button on the valve.*
> *Did the servo actuate (valve moved)?*

**Press the button on the board first**, watch the valve move, **then** answer.

![Fig 8 — Servo check dialog](screenshots/fig-08-servo-check-dialog.png)
*Figure 8 — Servo actuation check. Press the board button before answering.*

**c) Step `Buzzer audible?`** — dialog asks *"Did you hear the buzzer?"*

![Fig 9 — Buzzer check dialog](screenshots/fig-09-buzzer-check-dialog.png)
*Figure 9 — Buzzer check.*

### Step 4.6 — Production firmware re-flash (automatic)

After the three checks pass, the tool automatically re-flashes the board with **production (low-power)** firmware — step **Flash production firmware (low-power)**. Do not disconnect the board.

### Step 4.7 — Confirm PASS

The banner turns green and reads **PASS**. A serial number is allocated and a QR code appears on the right.

![Fig 10 — PASS result](screenshots/fig-10-pass-result.png)
*Figure 10 — Completed run: green PASS banner, all steps ✔.*

A good run shows `Match: <address>` on *Cross-verify BD address (UART vs BLE)* and `v<version> matches expected` on *Verify FW version (DIS)*. The board's identity is enforced by the tool — it cannot pass without a confirmed Bluetooth address match.

> ℹ️ One check the tool cannot enforce: if **Expected FW version** was left blank, *Verify FW version (DIS)* shows a green ✔ reading `Got v… (no expected set)` — a tick that compared nothing. That is why Rule 3 exists.

Serial numbers are in the form `YYWW-NNNNNN` (year-week + counter, e.g. `2628-000001`). **A serial number is only issued when a board passes** — failed boards do not consume one.

---

## 5. If a board FAILS

The banner turns red and reads **FAIL** with the reason in the log.

![Fig 11 — FAIL example](screenshots/fig-11-fail-example.png)
*Figure 11 — Example of a failed run.*

1. Note the board number and the failure message in the batch log (§8).
2. Set the board aside — **label it as debug firmware / not shippable**.
3. Check the troubleshooting table (§7). Where it says *retry*, you may reconnect and press **START** again.
4. Do not ship any board that has not completed with a green **PASS**.

### 5.1 Using ABORT

**ABORT** stops the run. The banner turns red and reads **ABORTED**, the board is recorded as a failure, and no serial number is used. That board must be re-run from the beginning.

Notes:

- ABORT **cannot** be pressed while an Operator Check question is on screen — answer YES or NO (§4.5).
- After an abort, the UART and Bluetooth connections take a few seconds to release. If you press START too soon the tool tells you what is still stopping and asks whether to start anyway — **click No, wait a few seconds, and press START again.**

---

## 6. Printing the QR label

Each passing board gets one **20 mm × 20 mm** QR label.

> ℹ️ **The printed label is the QR code only — no serial number and no readable text.** The QR encodes:
> `id=VV-<BLE MAC>&type=valve&hw=stm32wb-C&sw=v<firmware version>`
> There is **no serial number in the QR**, so the only link between a board and its serial number is the batch log in §8. Fill it in as you go.

**Step 6.1** — With the PASS result on screen, check the QR panel on the right. The caption shows `SN:`, `ID:` and `FW:` for the board just programmed.

![Fig 12 — QR preview panel](screenshots/fig-12-qr-preview.png)
*Figure 12 — QR preview with SN / ID / FW caption and the Print Label + Printer Setup buttons.*

**Step 6.2** — **Record the `SN:` and `ID:` values in the batch log (§8) against this board number _before_ printing.**

**Step 6.3 (first board only)** — In the QR panel, set the **Printer** dropdown to `System printer (any)` for this trial, then click **Printer Setup** and select the office printer. Both settings are remembered — the dropdown choice persists between sessions, and the printer choice for the rest of this session.

> The **Printer** dropdown selects which kind of label printer the tool drives. It is shared across all three device tabs, so setting it here also sets it for WiFi Hub and Leak Sensor. If an entry shows `— not detected`, that printer is not connected.

![Fig 13 — Printer Setup dialog](screenshots/fig-13-printer-setup.png)
*Figure 13 — Printer dropdown and Printer Setup.*

**Step 6.4** — Click **Print Label**, then follow §6.6 below for this trial (office printer).

**Step 6.5** — Apply the label to the board per the assembly drawing. Scan it with a phone camera and **confirm the `id=` in the scanned text matches the `ID:` shown in the QR caption for this board.** This is the only check that the right label went on the right board.

### 6.6 Printing on a normal office printer (this trial) ⚠️

A proper 20 mm label printer is **not** available for this trial, so the QR will be printed on plain A4/Letter paper and cut out. **The QR itself will still be exactly 20 mm**, which is what matters for scanning.

When you click **Print Label** you will get **one of two warnings**. What you do depends on which one:

| Warning shown | What it means | What to do |
|---|---|---|
| **"Label size is not 20 mm"** — *"The selected printer's page is 210.0 x 297.0 mm, not the required 20 x 20 mm…"* | Normal on an office printer. The QR will still print at the correct **20 mm**, centred on the sheet. | Click **Yes**. Then **cut out the QR** and apply it to the board. |
| **"QR would print under 20 mm"** — *"…the QR would print at only 11.8 mm instead of 20 mm…"* | This printer is **shrinking** the code — it would not scan reliably. | Click **No**. Do **not** use this printer/setting. Try selecting A4 or Letter paper in **Printer Setup** and print again. |

**Step 6.6.1** — On the first printed sheet, **measure the QR with a ruler — it must be 20 mm × 20 mm.** If it is not, stop and report it.

**Step 6.6.2** — Scan the cut-out QR with a phone camera and confirm the `id=` matches the `ID:` in the caption (§6.5) before applying it.

> ℹ️ **Tip:** you can print several boards' labels onto sheets and apply them at the end — just keep them in board order and use the batch log (§8) to keep track. Recording `SN:` and `ID:` per board (§6.2) is what makes that safe.
>
> If a proper 20 mm label printer becomes available later, the boards can simply be re-labelled from the batch log — no re-programming is needed.

---

## 7. Troubleshooting

| Message on screen | Cause | Action |
|---|---|---|
| **"Enter your Operator ID before starting."** | Operator field empty | Fill in the **Operator:** field in the top bar |
| **"Valve firmware not configured in manifest."** / **"Debug firmware … missing."** / **"Production firmware … missing."** | Firmware files missing from the tool | Stop — escalate to engineering |
| **"Wrong MCU! Expected STM32WB (0x495)…"** | Not a valve board, or wrong tab | Confirm it is a valve board and you are on the **Valve** tab |
| **"STM32_Programmer_CLI exited with code …"** | Flashing failed — usually SWD wiring, power, or a board fault | Check SWD connections and power, re-seat the board, retry |
| **"STM32_Programmer_CLI timed out after …"** | Programmer stopped responding | Unplug/replug the ST-Link, retry |
| **"Select the ST-Link VCP port before starting."** | No UART port selected (or "(Skip UART capture)" chosen) | Press **Refresh**, select the ST-Link VCP port, press START again |
| **"Still running from the previous board: …"** | The previous run's UART/Bluetooth connection has not released yet | Click **No**, wait a few seconds, press START again |
| `Capture UART boot log` detail says **`0 lines captured`**, and/or log shows **"Serial error: Cannot open COM… after 3s retry"** | Wrong COM port, or another program (terminal/monitor) is holding the port | Close any terminal program, re-select the ST-Link VCP port, re-run |
| `Parse BD address from UART` shows ✘ **"BD address not found in boot log"**, then the run fails with **"Cannot verify board identity…"** | Wrong COM port, or the boot log was not captured | Re-run with the correct ST-Link VCP port. If it recurs on the same board, set it aside and escalate |
| `BLE advertising scan` → **"No BLE device found"** → **"BLE advertising not detected after flash"** | ① PC Bluetooth off/missing · ② board not advertising | ① Turn Bluetooth on · ② If it still fails on a second attempt, set the board aside and escalate |
| **"BD address mismatch! UART reports … but BLE scan found …"** | The tool saw a *different* nearby valve board | Power down all other valve boards and the WiFi Hub, then retry |
| **"FW version mismatch: device reports v…, expected v…"** | Expected FW version typed incorrectly, or wrong firmware loaded in the tool | Re-check the value in §2.3. If the value is right, stop and escalate — the firmware may be wrong |
| `Read FW version via DIS` shows ✘ **"DIS read failed: …"** and `Verify FW version (DIS)` shows `─ Skipped (no DIS version)`, but the run continues | Bluetooth connection dropped before the version could be read | The firmware version was **not** verified and the QR's `sw=` field will be blank. **Re-run the board rather than shipping it** |
| No COM ports listed at all | ST-Link USB or driver problem | Press **Refresh** first. If still empty, re-plug the ST-Link USB cable and confirm it appears in Windows Device Manager |

> ℹ️ **How to read the step symbols.** `○` not started · `◔` running · `✔` passed · `✘` failed · `─` skipped.
> The grey text at the right of each row gives the detail — the address matched, the version read, the number of log lines. It is worth reading when a board behaves oddly.
> A `✔` reading `Already installed (skipped)` on *Check/upgrade FUS* or *Install BLE wireless stack* is **normal** on a board that has been programmed before.

---

## 8. Batch log — trial assembly (10 boards)

Operator: ______________  Work Order: ______________  Date: ____________
Expected FW version used: ______________

| # | Serial Number (from tool) | BLE ID (from QR caption) | Result | Label printed | Notes / failure reason |
|---|---|---|---|---|---|
| 1 | | | ☐ PASS ☐ FAIL | ☐ | |
| 2 | | | ☐ PASS ☐ FAIL | ☐ | |
| 3 | | | ☐ PASS ☐ FAIL | ☐ | |
| 4 | | | ☐ PASS ☐ FAIL | ☐ | |
| 5 | | | ☐ PASS ☐ FAIL | ☐ | |
| 6 | | | ☐ PASS ☐ FAIL | ☐ | |
| 7 | | | ☐ PASS ☐ FAIL | ☐ | |
| 8 | | | ☐ PASS ☐ FAIL | ☐ | |
| 9 | | | ☐ PASS ☐ FAIL | ☐ | |
| 10 | | | ☐ PASS ☐ FAIL | ☐ | |

**Totals:** Passed ______ / 10   Failed ______ / 10

---

## 9. End of batch — export the records

The tool logs every board automatically. At the end of the trial:

**Step 9.1** — Open the **History** tab.

**Step 9.2** — Set the **Device** filter to `valve` to show only this batch.

![Fig 14 — History tab](screenshots/fig-14-history-tab.png)
*Figure 14 — History tab filtered to `valve`, showing the trial records.*

**Step 9.3** — Click **Export CSV**, save as `production_records.csv`, and send the file with this completed instruction.

> ℹ️ The **Result** filter is *not* applied to the export — the CSV contains both passes and failures, which is what we want for the trial report.

Records are stored automatically in the `data\` folder next to `eFloStop_Production_Tool.exe`. Do not delete it.

---

## 10. Sign-off

| | Name | Signature | Date |
|---|---|---|---|
| Assembled / programmed by | | | |
| Reviewed by | | | |

---

<!--
==================================================================
APPENDIX (internal) — SCREENSHOT CAPTURE LIST
Save each as PNG into:  docs/work_instructions/screenshots/
Filenames must match exactly for the images to appear.
==================================================================

fig-01-main-window-valve-tab.png   Full app window, Valve tab selected, idle (READY banner).
                                   Shows operator bar + firmware strip + all 4 tabs.
fig-02-operator-bar.png            Close-up of the dark top bar with the Operator: and Work Order: fields filled in.
fig-03-firmware-strip.png          Close-up of the "Firmware:" strip with the green `valve` tag.
fig-04-uart-port-dropdown.png      Valve tab, UART Port drop-down OPEN, showing an ST-Link VCP COM port
                                   and the "(Skip UART capture)" entry.
fig-05-expected-fw-version.png     Close-up of "Expected FW version:" with a version typed in.
fig-06-run-in-progress.png         Mid-run: RUNNING... banner, several steps ✔ and one ◔ running.
                                   Ideally include a row whose grey detail text is visible.
fig-07-led-check-dialog.png        "Operator Check" dialog — "Is the LED on the Valve board visible?"
fig-08-servo-check-dialog.png      "Operator Check" dialog — servo/button question (two lines).
fig-09-buzzer-check-dialog.png     "Operator Check" dialog — "Did you hear the buzzer?"
fig-10-pass-result.png             Completed run: green PASS banner, all 17 steps ✔, QR visible.
                                   IMPORTANT: capture wide enough to show the grey detail text at the
                                   right of each step row (§4.7 tells the operator to read it).
fig-11-fail-example.png            A failed run: red FAIL banner + the failed step with its ✘ detail.
                                   (Easy to produce: run with Bluetooth switched off.)
fig-12-qr-preview.png              QR panel close-up: QR image, SN/ID/FW caption,
                                   "Print Label" + "Printer Setup" buttons.
fig-13-printer-setup.png           The Windows printer dialog opened by "Printer Setup".
fig-14-history-tab.png             History tab, Device filter = valve, rows visible, Export CSV button.
-->
