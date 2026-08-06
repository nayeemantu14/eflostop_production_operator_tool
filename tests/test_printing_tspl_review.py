"""Regression tests for the adversarial review of the TSPL serial backend.

Each test names the failure it locks out. The first one is the reason this file
exists: a print reported as failed that then went on to physically print.
"""

import threading
import time

from PyQt6.QtGui import QImage

from app.services.printing import PrintStatus, plan_label
from app.services.printing.backends.puqu_aq20_serial import (
    PuquAq20SerialBackend,
    TsplSerialOptions,
    pack_tspl_bitmap,
)
from app.services.printing.base import LabelPrintRequest


class Ui:
    def __init__(self, answer=True):
        self.answer = answer
        self.confirms: list[tuple[str, str]] = []
        self.warnings: list[tuple[str, str]] = []

    def confirm(self, title, message):
        self.confirms.append((title, message))
        return self.answer

    def warn(self, title, message):
        self.warnings.append((title, message))


def qr_image() -> QImage:
    img = QImage(410, 410, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF)
    return img


def solid(width: int, height: int, white: bool) -> QImage:
    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF if white else 0xFF000000)
    return img


def hanging_serial(seconds: float, writes: list):
    """A serial.Serial stand-in whose open() blocks for `seconds`."""

    class Hanging:
        def __init__(self, *a, **k):
            self.port = k.get("port")
            time.sleep(seconds)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def write(self, data):
            writes.append((self.port, data))

        def flush(self):
            pass

    return Hanging


def present(port="COM9"):
    return lambda: [type("P", (), {"port": port, "description": ""})()]


# --- The abandoned-job bug --------------------------------------------------


def test_a_timed_out_job_must_never_print(monkeypatch):
    """The worst defect this backend had.

    Waiting on a future with a timeout stops the waiter, not the work. The
    operator was told the label had failed, moved on to the next device, and the
    abandoned job then opened the port and printed anyway — putting the previous
    device's serial on a label while the operator was holding the next one.
    """
    from app.services.printing.backends import puqu_aq20_serial as mod

    writes: list = []
    monkeypatch.setattr(mod.serial, "Serial", hanging_serial(1.5, writes))
    monkeypatch.setattr(mod, "find_all_serial_ports", present())

    backend = PuquAq20SerialBackend({"port": "COM9", "timeout_seconds": 0.2})
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    assert result.status is PrintStatus.ERROR

    # Give the abandoned worker time to finish its slow open and reach the write.
    time.sleep(2.5)
    assert writes == [], "an abandoned job printed after being reported as failed"


def test_a_second_print_while_one_is_stuck_names_the_stuck_port(monkeypatch):
    """It must refuse at once and blame the right port.

    Queueing behind the stuck job meant the second print spent its whole budget
    waiting, then reported that the *newly corrected* port had not responded —
    telling the operator their correct fix had failed.
    """
    from app.services.printing.backends import puqu_aq20_serial as mod

    writes: list = []
    monkeypatch.setattr(mod.serial, "Serial", hanging_serial(4.0, writes))
    monkeypatch.setattr(mod, "find_all_serial_ports", present("COM9"))

    backend = PuquAq20SerialBackend({"port": "COM9", "timeout_seconds": 0.2})
    backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))

    # Operator corrects the port to a healthy one and prints again.
    monkeypatch.setattr(mod, "find_all_serial_ports", present("COM3"))
    backend.apply_options({**backend.options(), "port": "COM3"})

    start = time.monotonic()
    second = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    elapsed = time.monotonic() - start

    assert second.status is PrintStatus.ERROR
    assert "COM9" in second.message, "blamed the port the operator just corrected to"
    assert elapsed < 0.5, "queued behind the stuck job instead of refusing at once"


def test_options_are_snapshotted_at_submit(monkeypatch):
    """A Setup change mid-print must not redirect the in-flight job."""
    from app.services.printing.backends import puqu_aq20_serial as mod

    writes: list = []
    monkeypatch.setattr(mod.serial, "Serial", hanging_serial(0.6, writes))
    monkeypatch.setattr(mod, "find_all_serial_ports", present("COM9"))

    backend = PuquAq20SerialBackend({"port": "COM9", "timeout_seconds": 3.0})

    def change_port():
        time.sleep(0.2)
        backend.apply_options({**backend.options(), "port": "COM5"})

    threading.Thread(target=change_port, daemon=True).start()
    backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))

    assert writes, "nothing was written"
    assert writes[0][0] == "COM9", (
        f"job was built for COM9 but went to {writes[0][0]}"
    )


# --- Process lifetime and GUI responsiveness --------------------------------


def test_no_non_daemon_thread_survives_a_wedged_print(monkeypatch):
    """A wedged port must not keep the windowed .exe alive after its window closes.

    concurrent.futures workers are non-daemon and joined by an atexit hook, so a
    stuck open left the process resident in Task Manager with no UI.
    """
    from app.services.printing.backends import puqu_aq20_serial as mod

    monkeypatch.setattr(mod.serial, "Serial", hanging_serial(30.0, []))
    monkeypatch.setattr(mod, "find_all_serial_ports", present())

    backend = PuquAq20SerialBackend({"port": "COM9", "timeout_seconds": 0.2})
    backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))

    workers = [t for t in threading.enumerate() if t.name == "tspl-print"]
    assert workers, "expected the worker to still be running"
    assert all(t.daemon for t in workers), "a non-daemon worker blocks interpreter exit"


def test_print_stays_under_the_windows_not_responding_threshold(monkeypatch):
    """Windows paints a window "Not Responding" after ~5 s of a blocked loop."""
    from app.services.printing.backends import puqu_aq20_serial as mod

    monkeypatch.setattr(mod.serial, "Serial", hanging_serial(30.0, []))
    monkeypatch.setattr(mod, "find_all_serial_ports", present())

    backend = PuquAq20SerialBackend({"port": "COM9"})  # shipped default timeout
    start = time.monotonic()
    backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    elapsed = time.monotonic() - start
    assert elapsed < 5.0, f"blocked {elapsed:.1f}s — Windows would mark the app hung"


def test_default_timeout_keeps_the_worst_case_under_five_seconds():
    budget = TsplSerialOptions().timeout_seconds * 2 + 1.0
    assert budget < 5.0


# --- Label correctness ------------------------------------------------------


def test_bitmap_x_is_not_snapped_to_a_byte_boundary():
    """BITMAP's X is a dot coordinate; only `width` is in bytes.

    Snapping it down shifted the QR up to 7 dots (0.88 mm) off-centre, and put
    this backend out of step with the ZPL one for the same LabelPlan.
    """
    backend = PuquAq20SerialBackend({"port": "COM9", "label_width_mm": 25.0})
    plan = plan_label(backend._metrics())
    job = backend.build_tspl(qr_image(), plan)

    after = job.split(b"BITMAP ", 1)[1]
    x = int(after.split(b",", 1)[0])
    assert x == round(plan.qr_rect[0]), "BITMAP X does not match the shared plan"
    assert x % 8 != 0, "this width should expose the snapping if it came back"


def test_invert_does_not_burn_the_padding_bits():
    """With invert on, the stride padding must still be blank.

    It was seeded with 1s unconditionally, so inverting burned a black stripe
    down the right-hand edge — straight through the QR's quiet zone.
    """
    data, width_bytes, _h = pack_tspl_bitmap(solid(17, 1, white=True), invert=True)
    assert width_bytes == 3
    # White + invert = blank = 0, and the 7 padding bits must be blank too.
    assert data == b"\x00\x00\x00"

    data, _w, _h = pack_tspl_bitmap(solid(17, 1, white=False), invert=True)
    # Black + invert = burn = 1; padding still blank.
    assert data == b"\xff\xff\x80"


def test_dpi_is_a_class_constant_not_an_operator_option():
    """TSPL SIZE is in mm, so the printer maps it with its OWN resolution.

    A configured dpi that disagreed with the hardware would rasterise the wrong
    number of dots with no guard able to see it.
    """
    assert PuquAq20SerialBackend.dpi == 203
    assert "dpi" not in TsplSerialOptions().model_dump()
    # A stray dpi key in a stored config is ignored rather than applied.
    backend = PuquAq20SerialBackend({"port": "COM9", "dpi": 600})
    assert backend._metrics().dpi == 203


def test_no_flush_call_in_the_write_path(monkeypatch):
    """pyserial's Windows flush() is an unbounded `while out_waiting: sleep()`.

    Closing the port drains it, so calling flush() only adds a way to hang on a
    printer that has stopped consuming (out of paper, flow-controlled off).
    """
    from app.services.printing.backends import puqu_aq20_serial as mod

    calls: list[str] = []

    class Recording:
        def __init__(self, *a, **k):
            self.port = k.get("port")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def write(self, data):
            calls.append("write")

        def flush(self):
            calls.append("flush")

    monkeypatch.setattr(mod.serial, "Serial", Recording)
    monkeypatch.setattr(mod, "find_all_serial_ports", present())

    backend = PuquAq20SerialBackend({"port": "COM9"})
    assert backend.print_label(
        LabelPrintRequest(image=qr_image(), ui=Ui())
    ).status is PrintStatus.OK
    assert calls == ["write"], f"expected write only, got {calls}"


# --- UI re-entrancy ---------------------------------------------------------


def test_print_button_is_disabled_while_a_job_is_in_flight(monkeypatch):
    """A second click must not be able to stack a second physical label."""
    from app.services.printing import DictStore, PrinterSelection, default_registry
    from app.services.printing.backends import puqu_aq20_serial as mod
    from app.ui.widgets.qr_preview import QrPreview

    from PyQt6.QtWidgets import QMessageBox

    seen: list[bool] = []

    class Recording:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def write(self, data):
            pass

    monkeypatch.setattr(mod.serial, "Serial", Recording)
    monkeypatch.setattr(mod, "find_all_serial_ports", present())
    # Any dialog would block this test forever on the offscreen platform.
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    backend = PuquAq20SerialBackend({"port": "COM9"})
    selection = PrinterSelection(registry=default_registry(), store=DictStore())
    widget = QrPreview(selection=selection)
    monkeypatch.setattr(selection, "current_backend", lambda: backend)

    original = backend.print_label

    def watching(request):
        seen.append(widget.print_btn.isEnabled())
        return original(request)

    monkeypatch.setattr(backend, "print_label", watching)
    widget._qr_image = qr_image()
    widget.print_btn.setVisible(True)

    widget._on_print()

    assert seen == [False], "Print was still clickable during the print"
    assert widget.print_btn.isEnabled(), "Print was left disabled afterwards"
