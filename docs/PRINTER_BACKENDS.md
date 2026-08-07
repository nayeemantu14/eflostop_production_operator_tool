# Label printer backends

The tool prints one thing — a **20 mm × 20 mm QR-only label** — but the printer that prints it varies
by production line and changes over time. A *backend* is the whole answer to "how do these bits reach
paper" for one class of printer. The operator picks one from a dropdown in the QR panel; everything
else is shared.

This document is for two audiences: developers adding a printer ([§1](#1-how-to-add-a-new-printer)),
and production support setting up the PUQU AQ20 on a line — either through its Windows driver
([§3](#3-puqu-aq20-setup-for-the-line)) or over USB/Bluetooth serial ([§4](#4-puqu-aq20-usb-serial--tspl)).

---

## 1. How to add a new printer

Adding a printer is **one new module plus one import line** of application code. Nothing else — no
changes to the UI, the device tabs, the config schema, the persistence layer, or the PyInstaller
build. (You will also update three deliberately-pinned assertions in the registry test — see §1.5.)

### 1.1 Pick your starting point

| Your printer is… | Subclass | Effort |
|---|---|---|
| Reachable through an installed **Windows print driver** | `QtDriverBackend` | ~40 lines |
| A **ZPL** printer on the network | `ZplSocketBackend` | ~20 lines |
| A **TSPL** printer on a serial/USB-VCP port | `PuquAq20SerialBackend` | ~30 lines |
| Anything else (raw USB, serial, vendor SDK) | implement the protocol directly | ~150 lines |

Most printers are the first row. If Windows can see it in *Printers & scanners*, use `QtDriverBackend`
and you inherit the 20 mm geometry, all the safety guards, and the stale-queue protection for free.

### 1.2 Write the module

Create `app/services/printing/backends/<your_printer>.py`. This skeleton is complete and working —
copy it and change the marked lines.

```python
"""Brother QL-820NWB label printer, via its Windows driver."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import QInputDialog, QWidget
from pydantic import BaseModel, field_validator

from ..base import BackendAction, BackendCapabilities
from ..qt_driver import QtDriverBackend, available_printer_names
from ..registry import register_backend


class BrotherOptions(BaseModel):
    """Per-machine settings. Opaque to the UI — it round-trips this as JSON."""

    printer_name: str = ""
    resolution_dpi: int = 300

    @field_validator("resolution_dpi")
    @classmethod
    def _sane_dpi(cls, value: int) -> int:
        # Reject nonsense rather than silently rescaling every label.
        if not 72 <= value <= 2400:
            raise ValueError("resolution_dpi must be between 72 and 2400")
        return value


@register_backend                       # <-- the registration
class BrotherQl820Backend(QtDriverBackend):
    id: ClassVar[str] = "brother_ql820"          # <-- persisted; see §2
    display_name: ClassVar[str] = "Brother QL-820NWB"
    capabilities: ClassVar[BackendCapabilities] = BackendCapabilities(configurable=True)
    sort_order: ClassVar[int] = 30               # <-- dropdown position
    pins_printer: ClassVar[bool] = True          # <-- it targets one named queue

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        self._opts = BrotherOptions()
        super().__init__(options)

    # --- options: how your settings persist ---

    def apply_options(self, options: Mapping[str, Any]) -> None:
        try:
            self._opts = BrotherOptions.model_validate(dict(options or {}))
        except Exception:
            # Bad stored settings must never stop the tool starting. Report
            # yourself unconfigured; the operator fixes it in Printer Setup.
            self._opts = BrotherOptions()

    def options(self) -> Mapping[str, Any]:
        return self._opts.model_dump()

    # --- which queue to print to ---

    def target_printer_name(self) -> str:
        return self._opts.printer_name

    def _after_bind(self, printer: QPrinter) -> None:
        # Called AFTER setPrinterName. That order is required: selecting a
        # printer re-creates the print engine and resets the resolution to the
        # driver default, so setting it earlier is silently discarded.
        printer.setResolution(self._opts.resolution_dpi)

    # --- operator setup ---

    def configure(self, parent: QWidget | None) -> None:
        names = available_printer_names()
        if not names:
            return
        current = self._opts.printer_name
        index = names.index(current) if current in names else 0
        name, ok = QInputDialog.getItem(
            parent, "Brother QL-820NWB", "Windows print queue:", names, index, False
        )
        if ok and name:
            self._opts = self._opts.model_copy(update={"printer_name": name})
            self.refresh_availability()

    # --- optional extras, rendered as buttons with no UI change ---

    def actions(self) -> Sequence[BackendAction]:
        return ()
```

You do **not** write `print_label()`, the geometry, or the guards — `QtDriverBackend` does all of that.

### 1.3 Register it

Add one line to `app/services/printing/backends/__init__.py`:

```python
from . import brother_ql820  # noqa: F401
```

Keep it a plain `from . import x`. Discovery via `pkgutil`/`importlib` would look tidier and **break
the shipped product**: PyInstaller decides what to bundle by walking the static import graph, so a
dynamically imported backend works from source and is missing from the frozen `.exe`.

### 1.4 Add config defaults (optional)

In `app/config/default_config.yaml`, under `label_printer.backends`:

```yaml
label_printer:
  backends:
    brother_ql820:
      printer_name: ""
      resolution_dpi: 300
```

These are **factory defaults only**. The schema does not change — `backends` is an opaque
`dict[str, dict[str, Any]]` and your pydantic model is the only thing that validates your slice.
Operator choices are stored per-user in QSettings, not here.

### 1.5 Tests a new backend should bring

Add `tests/test_printing_backends.py` cases (or your own module) covering:

| What | Why |
|---|---|
| Options model rejects nonsense (dpi, port, host) | A bad value silently rescales or misroutes every label |
| Invalid stored options fall back to defaults, not a crash | Settings survive a downgrade or a hand-edit |
| Options round-trip through `apply_options`/`options` | Persistence is JSON — non-serialisable values are lost |
| Unavailable state returns `UNAVAILABLE`, not silence | An operator must never click Print and get nothing |
| A stale/removed target is refused, not redirected | See the `setPrinterName` trap in §1.6 |
| Update the three id/order assertions in `tests/test_printing_registry.py` (`test_backend_ids_are_pinned`, `test_dropdown_order_is_declared_not_import_order`, `test_registry_is_populated_by_import_alone`) | Ids are a compatibility surface, so they are pinned deliberately — adding a printer is expected to update these |

`tests/test_printing_extensibility.py` already proves the *generic* path (registration → dropdown →
selection → persistence → dispatch → guards) for any backend, so you don't need to retest that.

### 1.6 Rules that will bite you

These are all things that have actually gone wrong, verified on Windows with PyQt6 6.11:

- **Never construct a Qt object at module import.** `QPrinter()` before the `QApplication` exists
  aborts the interpreter with `0xC0000409` — not an exception, so `try/except` does nothing, and in
  the windowed build the `.exe` just vanishes. The registry stores *classes* for this reason. Build
  your `QPrinter` lazily (`QtDriverBackend` already does).
- **Never raise.** Every backend method is reached from a Qt slot, and an exception escaping a slot
  terminates the process rather than unwinding. Return `PrintResult` / `Availability` values.
- **`setPrinterName()` fails silently.** Given an unknown name Qt early-returns, leaving the QPrinter
  pointed at whatever it had — for a fresh one, the *system default*. So a renamed label queue would
  quietly print to the office MFP, and `isValid()` still returns `True`. The only reliable check is
  `QPrinterInfo.printerInfo(name).isNull()`; `QtDriverBackend` does this and refuses.
- **`availability()` must be instant and do no I/O.** It is called while painting the dropdown. Put
  blocking probes in `refresh_availability()`, and bound every socket operation — an unbounded
  connect to a dead host freezes the GUI for the ~21 s Windows SYN retry, mid-test.
- **Don't reimplement the geometry.** Use `plan_label()` + `run_guards()`. If your printer isn't a Qt
  driver, build `PrinterMetrics` with `provenance="declared"` so the guards use honest wording — see
  the note in `geometry.py` about why a config-derived warning must not blame the hardware.
- **Don't add a capability flag.** `BackendCapabilities` has exactly one field on purpose. New
  affordances go through `actions()`, which the UI renders generically.

---

## 2. Registered backends

| id | Display name | Transport | Notes |
|---|---|---|---|
| `system` | System printer (any) | Windows driver, native print dialog | The default. Unchanged legacy behaviour. Also the fallback for an unknown id. |
| `puqu_aq20` | PUQU AQ20 | Windows driver, pinned queue | Needs PUQU's Windows driver installed. 203 dpi, 20 × 20 mm forced. See §3. |
| `puqu_aq20_serial` | PuQu AQ20 (USB Serial) | COM **or LPT** port, raw **TSPL** | Same printer, no driver needed. Covers USB, Bluetooth and LPT. See §4. |
| `zpl_tcp` | ZPL printer (network) | Raw TCP:9100, `^GFA` raster | Replaces the tool's old dead ZPL module. |

The two AQ20 entries are alternatives, not duplicates: `puqu_aq20` goes through the Windows print
driver, `puqu_aq20_serial` talks to the printer directly. Use whichever the line has set up.

> **Backend ids are a persisted compatibility surface.** They are written into each operator's
> settings (`HKCU\Software\eFloStop\eFloStop II Production Tool`). **Renaming one is a breaking
> change**: every machine that had it selected silently reverts to `system` at the next launch.
> `tests/test_printing_registry.py::test_backend_ids_are_pinned` fails if you rename one, so the
> decision has to be deliberate. If you must rename, ship a migration in `PrinterSelection._resolve_id`.

### How the pieces fit

```
app/services/printing/
    base.py         the contract: LabelPrinterBackend, PrintResult, Availability, GuardUi
    geometry.py     PURE, no Qt: the 20 mm spec, plan_label(), run_guards()  <-- shared safety code
    qt_geometry.py  Qt adapter: prepare() / rasterize() / draw()
    qt_driver.py    QtDriverBackend — reusable base for driver-based printers
    registry.py     @register_backend, duplicate-id rejection
    selection.py    which backend is chosen; QSettings persistence
    backends/       one module per printer + __init__.py listing them
```

`geometry.py` is deliberately Qt-free so the code that decides whether a label is safe to print can be
tested without a `QApplication`. All three guards live there:

| Guard | Fires when | Operator sees |
|---|---|---|
| No printable area | the printable region computes to zero or less | `Print Error` — abort, no override |
| Wrong media | the page isn't 20 × 20 mm (±1 mm) | `Label size is not 20 mm` — Yes/No, defaults No |
| Undersized | the QR would print below 18 mm | `QR would print under 20 mm` — Yes/No, defaults No |

At most one dialog ever appears. `docs/work_instructions/WI-VALVE-001` reproduces these titles
verbatim and tells operators they get "one of two warnings", so **the wording and the exclusivity are
both a compatibility surface** — `tests/test_printing_geometry.py` pins them.

---

## 3. PUQU AQ20 setup for the line

### 3.1 Install the driver

1. Download PUQU's Windows driver bundle from <https://puqulabel.com/download/printer-driver/>
   (`pc_printing_drivers.zip`, covering the PQ/AQ/TQ/Q1 series).
2. Connect the AQ20 by **USB** and run the installer.
3. Check *Printers & scanners*. **The queue is probably not called "AQ20".** PUQU's own PC manual
   states the driver installs a single queue named **`PQ00`** for the entire product range. Note down
   whatever name it actually used.

### 3.2 Load 20 × 20 mm media

1. Press the cover-release button and open the lid.
2. Spread the guides and drop the roll in **print side up**, pushed **left against the baffle** — the
   AQ20 prints left-justified, so this sets the origin.
3. Close the cover.
4. **Short-press the RIGHT button** to feed one label and let the gap sensor find the label edge. This
   is the only calibration procedure PUQU documents.
5. Check the LED:

| LED | Meaning |
|---|---|
| Solid blue | Ready, Bluetooth connected |
| Flashing blue | Ready, Bluetooth not connected (fine — we print over USB) |
| Solid red | Not ready — out of paper, or the cover is open |
| Fast-flashing red | Print head over temperature |

Paper gap, darkness and speed are set from the printer's own button menu: short-press **LEFT** to
cycle items, **RIGHT** to change the value.

### 3.3 Point the tool at it

1. In the tool, on any device tab, set **Printer** to `PUQU AQ20`.
2. Click **Printer Setup**. Pick the queue you noted in §3.1 — untick *Show only likely PUQU queues*
   if it isn't listed.
3. Read the **Status** line. `Full-bleed (0.0 mm margin)` means the QR will print at the full 20 mm.
   A reported non-printable border means it will be smaller, and you'll be warned before each print.
4. Click OK. The choice is remembered per user and survives restarts and tool upgrades.
5. Print one label and **scan it with the phone app** before running a batch.

### 3.4 Known gaps — needs bench verification

The following could **not** be verified from any PUQU documentation and must be confirmed on the
physical printer:

- **Whether the AQ20 accepts 20 × 20 mm die-cut stock at all.** PUQU publishes no minimum label
  height, and there is no 20 × 20 mm SKU in their catalogue. The default media in their marketing is
  40 × 30 mm.
- **Whether it prints full-bleed at 20 mm.** No margin specification exists in the guide, the FAQ, the
  app manual or the PC manual, and the 48 mm head vs 50 mm media difference is never explained.
- **Whether the installed queue exposes a 20 × 20 mm custom page size.** The driver `.INF` was never
  inspected (the download failed during research).
- **Module density.** At 20 mm and 203 dpi the 41-module QR gets 3.9 dots per module, so module runs
  alternate between 3 and 4 dots before thermal dot gain. Scan-verify the first labels of each batch.

### 3.5 Questions outstanding with PUQU support

1. Is there a protocol specification or SDK for the AQ20? (None is published; the OEM's LPAPI is
   Android/JS-only and documents no wire format.)
2. Which driver package supports the AQ20 specifically, and what queue name does it install?
3. What is the minimum label height the AQ20 can feed and gap-detect?
4. Is there a 20 × 20 mm die-cut media SKU?
5. What is the gap-sensor calibration procedure beyond the front-panel feed button?
6. Does the AQ20 print edge-to-edge, and what are its unprintable margins?

**No raw Bluetooth/USB transport is implemented,** and this is deliberate. PUQU publishes no protocol
spec and no SDK. The only wire-level document in circulation
(<https://github.com/sb-child/dz-print/blob/master/protocol.md>) describes a **Detonger DP27P** — a
different manufacturer's device — and nothing confirms the AQ20 speaks it. Guessing byte sequences for
the printer that labels shipped hardware is not a trade worth making. If PUQU answers question 1, a
raw transport becomes a new backend module under `backends/`, changing nothing else.


---

## 4. PuQu AQ20 (USB Serial) — TSPL

The same printer as §3, reached without installing any driver.

**Windows does not present this printer the same way on every machine.** Depending on which driver
Windows binds, the AQ20 comes up either as a **virtual COM port** (USB CDC, or an outgoing Bluetooth
SPP port) or as an **LPT port** — LPT1 was what a real production PC gave it. Both work; the port
dropdown lists both and you pick whichever is there. The difference matters because pyserial cannot
open an LPT port at all — it filters LPT out of its own enumeration — so the tool writes to those as a
raw byte pipe instead. Baud rate is ignored on an LPT port.

### 4.1 Set it up

1. Plug the AQ20 in over USB, or pair it in Windows Bluetooth settings. Either way it appears in
   *Device Manager → Ports (COM & LPT)*. Note whether it is a **COMn** or an **LPTn**.
2. In the tool, set **Printer** to `PuQu AQ20 (USB Serial)`.
3. Press **Printer Setup**. Pick the **Printer Port** — COM and LPT ports are both listed. Press
   **Refresh** if you plugged it in after opening the dialog. Leave the label size at 20 × 20 mm unless you loaded different stock.
4. **Test connection** confirms the port opens and is not held by another program. It cannot confirm
   the printer understands the commands — only a real label does that.
5. Load media and calibrate as in §3.2, then print one label and **scan it**.

### 4.2 Settings

| Setting | Default | What it does |
|---|---|---|
| Printer Port | — | The port the printer enumerates as. COM (USB or Bluetooth) and LPT ports both appear. |
| Baud rate | 115200 | Ignored by a USB virtual COM port and by LPT entirely; may matter over Bluetooth. Greyed out when an LPT port is selected. |
| Timeout | 1.5 s | Worst case is about twice this plus a second. Kept under the ~5 s at which Windows paints a window "Not Responding". Raise it if a Bluetooth link needs longer to come up. |
| Label width / height | 20 mm | The stock you loaded. The tool cannot read this from the printer. |
| Gap between labels | 2 mm | Vertical gap for the printer's gap sensor. 0 = continuous stock. |
| Density | 8 | TSPL print darkness, 0 (lightest) to 15 (darkest). |
| Speed | 3 | Inches per second. |
| Invert bitmap | off | **If the first label prints as a photographic negative, tick this.** See 4.4. |

### 4.3 If it does not print

- *"no printer port chosen"* / *"COMn not connected"* — the port is not there. Refresh the list in Setup.
- **The printer is not in the list at all** — check *Device Manager → Ports (COM & LPT)*. If it is
  there as LPTn it should be listed; if it appears only under *Printers*, use the driver-based
  **PUQU AQ20** entry (§3) instead of this one.
- *"did not respond within N s"* — the port exists but nothing opened in time. Usually the wrong port
  (some other device), or a Bluetooth link that did not come up. **The label was not printed** — the
  tool disowns a job it has given up on, so it cannot surface later and print the wrong serial.
- *"A previous label is still being sent to COMn and has not finished"* — a stuck port from an earlier
  attempt. Only one job runs at a time, so this refuses immediately rather than queueing. If the
  printer is genuinely wedged, restart the tool.
- *"Access is denied"* — another program holds the port. Close the vendor app or any terminal.

### 4.4 Known gaps — needs bench verification

- **That the AQ20 speaks TSPL at all** rests on hands-on testing, not on anything PUQU publishes.
- **Bitmap polarity.** TSPL prints a dot where the bit is `0` — the inverse of ZPL. That is the
  convention this backend implements. If the first label comes out as a negative (solid black with a
  white QR), tick **Invert bitmap** in Setup; no code change is needed. Inverting also flips the row
  padding, so it will not leave a black stripe down the edge.
- **20 × 20 mm gap stock.** PUQU publishes no minimum label height, so whether the gap sensor can
  index a 20 mm label is still unproven.

### 4.5 Why a print can take a couple of seconds

The serial write runs on a daemon thread with a hard deadline, and the GUI waits on it. Two things
that look like over-engineering are not:

- pyserial's `timeout`/`write_timeout` do **not** cover `open()`, and opening a Bluetooth COM port can
  block for seconds while Windows brings the link up. Only an outer deadline bounds that.
- A job the tool has given up waiting on is **disowned**: if its port ever does open, it checks a
  generation counter and discards the label. Without that, a slow-but-eventually-successful open
  printed a label after the operator had been told it failed and moved to the next device.

### 4.6 How the bytes reach the printer

| Port kind | Opened as | Notes |
|---|---|---|
| `COMn` | pyserial `Serial(port, baudrate, timeout, write_timeout)` | USB CDC or Bluetooth SPP |
| `LPTn` | `open(r"\\.\LPTn", "wb", buffering=0)` | Raw byte pipe. No baud, no flow control, no timeout of its own — the bounded worker in §4.5 is what covers it. |

LPT ports are discovered with `QueryDosDevice`, which resolves the name without opening the device —
opening a printer port can block, and the port list is drawn on the UI thread.

### 4.7 The TSPL job

One label is sent as, in order: `SIZE`, `GAP`, `DIRECTION 0,0`, `REFERENCE 0,0`, `DENSITY`, `SPEED`,
`CLS`, `BITMAP`, `PRINT 1,1` — each CRLF-terminated, per TSC's TSPL/TSPL2 manual. Every state-bearing
command is sent on every job rather than assumed: `DIRECTION`'s second argument is a mirror flag the
printer remembers across power cycles, and a mirrored QR is unscannable with nothing in the tool able
to detect it. `BITMAP` takes its width in **bytes** and its height in **dots**.
