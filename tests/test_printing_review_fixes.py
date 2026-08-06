"""Regression tests for defects found by the adversarial review.

Each test names the failure it locks out. They live together so the next person
can see what has already gone wrong here.
"""

import socket
import threading
import time

import pytest

from app.services.printing import (
    DictStore,
    PrinterSelection,
    PrintStatus,
    Registry,
    default_registry,
    plan_label,
)
from app.services.printing.backends.puqu_aq20 import PuquAq20Backend
from app.services.printing.backends.system import SystemPrinterBackend
from app.services.printing.backends.zpl_tcp import ZplOptions, ZplSocketBackend
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


def qr_image():
    from PyQt6.QtGui import QImage

    img = QImage(410, 410, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFF)
    return img


# --- Startup cost -----------------------------------------------------------


def test_system_availability_does_not_construct_a_qprinter():
    """Populating the dropdown must not build a QPrinter.

    It happens during MainWindow construction, before the window is shown, and
    constructing a QPrinter costs ~1.5 s when the default printer is a network
    queue — a blank window on every launch of a windowed build.
    """
    backend = SystemPrinterBackend({})
    assert backend._printer is None
    backend.refresh_availability()
    assert backend._printer is None, "refresh_availability built a QPrinter"


def test_populating_the_dropdown_is_fast():
    selection = PrinterSelection(registry=default_registry(), store=DictStore())
    start = time.monotonic()
    selection.visible_backends()
    assert time.monotonic() - start < 0.5


# --- PUQU setup dialog ------------------------------------------------------


def test_puqu_filter_never_drops_the_currently_pinned_queue(monkeypatch):
    """The filter must not silently re-pin the label printer.

    "Show only likely PUQU queues" is on by default and is not persisted. When
    it filtered out a pinned queue whose name matches no hint — the case this
    backend exists to support, since PUQU's driver may install under a generic
    name — the combo fell to another queue and OK wrote that one back. The
    operator saw no diff and no confirmation, and every later label went to a
    different printer.
    """
    from app.services.printing.backends import puqu_aq20 as mod

    installed = ["PQ00", "Brother Label Printer", "FUJI XEROX ApeosPort"]
    monkeypatch.setattr(mod, "available_printer_names", lambda: installed)

    backend = PuquAq20Backend({"printer_name": "Brother Label Printer"})
    dialog = mod._PuquSetupDialog(backend, None)
    dialog._only_likely.setChecked(True)
    dialog._reload()

    items = [dialog._combo.itemText(i) for i in range(dialog._combo.count())]
    assert "Brother Label Printer" in items, "pinned queue was filtered out"
    assert dialog.selected_printer() == "Brother Label Printer"


def test_puqu_setup_does_not_clear_a_saved_queue_when_no_printers_exist(monkeypatch):
    from app.services.printing.backends import puqu_aq20 as mod
    from PyQt6.QtWidgets import QDialog

    monkeypatch.setattr(mod, "available_printer_names", lambda: [])
    backend = PuquAq20Backend({"printer_name": "PQ00"})
    monkeypatch.setattr(mod._PuquSetupDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

    backend.configure(None)
    assert backend.options()["printer_name"] == "PQ00"


# --- One dialog per failure -------------------------------------------------


def test_painter_failure_reports_through_one_channel_only():
    """draw() must not both warn and return a dialog-worthy result.

    Doing both showed the operator two byte-identical "Print Error" modals for
    one failed print, where the tool has always shown one.
    """
    from app.services.printing import qt_geometry
    from app.services.printing.geometry import Margins, PrinterMetrics

    plan = plan_label(
        PrinterMetrics(
            page_w_px=0, page_h_px=0, media_w_mm=20, media_h_mm=20,
            margins_mm=Margins(), dpi=203,
        )
    )
    result = qt_geometry.draw(None, qr_image(), plan)
    assert result.status is PrintStatus.ERROR
    assert result.needs_dialog  # the caller raises exactly one dialog
    # draw() takes no GuardUi at all now, so it cannot raise a second one.
    import inspect

    assert "ui" not in inspect.signature(qt_geometry.draw).parameters


# --- Cross-tab refresh ------------------------------------------------------


def test_configuring_on_one_tab_refreshes_the_other_tabs_dropdowns():
    """The backend instance is shared, so its label must not go stale.

    Configuring the ZPL host on one tab used to leave the other two tabs saying
    "no host configured" for the rest of the session.
    """
    from app.ui.widgets.printer_selector import PrinterSelectorCombo

    selection = PrinterSelection(registry=default_registry(), store=DictStore())
    selection.set_current_id("zpl_tcp")
    tab_a = PrinterSelectorCombo(selection)
    tab_b = PrinterSelectorCombo(selection)

    def text_for(combo):
        return combo.itemText(combo.findData("zpl_tcp"))

    assert "no host configured" in text_for(tab_b)

    selection.current_backend().apply_options({"host": "10.0.0.5"})
    selection.persist_current_options()

    assert "no host configured" not in text_for(tab_a)
    assert "no host configured" not in text_for(tab_b), "sibling tab stayed stale"


def test_availability_notification_reaches_every_view():
    from app.ui.widgets.printer_selector import PrinterSelectorCombo

    selection = PrinterSelection(registry=default_registry(), store=DictStore())
    combo = PrinterSelectorCombo(selection)
    seen: list[str] = []
    selection.availability_changed.connect(seen.append)
    selection.notify_availability_changed()
    assert seen == [selection.current_id()]
    assert combo.count() == len(default_registry())


# --- ZPL robustness ---------------------------------------------------------


def test_malformed_hostname_is_reported_not_raised():
    """UnicodeError subclasses ValueError, so an OSError-only handler misses it.

    A doubled dot is the most ordinary typo available in an IP address.
    """
    backend = ZplSocketBackend({"host": "192.168..50", "timeout_seconds": 0.5})
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    assert result.status is PrintStatus.ERROR
    assert "192.168..50" in result.message

    ok, detail = backend._probe()
    assert not ok and detail


def test_connect_timeout_is_a_total_budget_not_per_address(monkeypatch):
    """create_connection applies the timeout to EACH resolved address.

    A dual-stack hostname therefore took twice the configured timeout, with the
    GUI thread blocked for all of it.
    """
    from app.services.printing.backends import zpl_tcp as mod

    # Three addresses that all black-hole: each connect() burns the remaining
    # budget. With a per-address timeout this would take 3 x 0.4 s.
    fake = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.255.255.1", 9100)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.255.255.2", 9100)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.255.255.3", 9100)),
    ]
    monkeypatch.setattr(mod.socket, "getaddrinfo", lambda *a, **k: fake)

    backend = ZplSocketBackend({"host": "printer.lab", "timeout_seconds": 0.4})
    start = time.monotonic()
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    elapsed = time.monotonic() - start

    assert result.status is PrintStatus.ERROR
    assert elapsed < 0.4 * 2, f"took {elapsed:.2f}s — budget was not shared"


def test_connect_still_succeeds_against_a_real_listener():
    received: list[bytes] = []
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def accept():
        conn, _ = server.accept()
        with conn:
            chunks = []
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                chunks.append(data)
            received.append(b"".join(chunks))

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    backend = ZplSocketBackend({"host": "127.0.0.1", "port": port})
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    thread.join(timeout=5)
    server.close()

    assert result.status is PrintStatus.OK
    assert received and received[0].startswith(b"^XA")


def test_negative_margin_is_rejected():
    """A negative margin would enlarge the printable area past the label."""
    with pytest.raises(ValueError):
        ZplOptions(margins_mm=-5.0)
    with pytest.raises(ValueError):
        ZplOptions(margins_mm=15.0)  # more than half a 20 mm label
    assert ZplOptions(margins_mm=0.0).margins_mm == 0.0


def test_absurd_label_dimensions_are_rejected():
    with pytest.raises(ValueError):
        ZplOptions(label_width_mm=0.0)
    with pytest.raises(ValueError):
        ZplOptions(label_height_mm=5000.0)


def test_invalid_stored_margin_falls_back_rather_than_printing_wrong():
    backend = ZplSocketBackend({"host": "h", "margins_mm": -5.0})
    assert backend.options()["margins_mm"] == 0.0


# --- Base-class footgun -----------------------------------------------------


def test_driver_base_defaults_to_not_configurable():
    """A subclass that forgets configure() must grey out Setup, not error.

    QtDriverBackend.configure() raises NotImplementedError; defaulting the
    capability to True meant the inherited behaviour was an error dialog.
    """
    from app.services.printing.qt_driver import QtDriverBackend

    assert QtDriverBackend.capabilities.configurable is False
    # ...and the shipped backends opt in explicitly.
    for cls in default_registry().classes():
        assert cls.capabilities.configurable is True


def test_not_implemented_configure_says_which_backend():
    from app.services.printing.qt_driver import QtDriverBackend

    class Forgot(QtDriverBackend):
        id = "forgot"
        display_name = "Forgot"

    with pytest.raises(NotImplementedError) as exc:
        Forgot({}).configure(None)
    assert "Forgot" in str(exc.value)


# --- Test-suite integrity ---------------------------------------------------


def test_no_test_constructs_qt_without_the_session_application():
    """The qapp fixture is autouse, so this must always hold.

    Without it, a test that touches Qt first aborts the interpreter with
    0xC0000409 — pytest reports one dot and silently never runs the rest.
    """
    from PyQt6.QtWidgets import QApplication

    assert QApplication.instance() is not None


def test_registry_is_not_mutated_by_the_test_suite():
    """Tests register fakes into their own Registry, never the global one."""
    assert set(default_registry().ids()) == {
        "system",
        "puqu_aq20",
        "puqu_aq20_serial",
        "zpl_tcp",
    }
    assert isinstance(Registry(), Registry)
