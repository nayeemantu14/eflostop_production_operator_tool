"""Tests for the three shipped backends and the label-printer config schema."""

import socket
import threading

import pytest
import yaml

from app.config.settings import AppSettings, LabelPrinterSettings
from app.services.printing import PrintStatus
from app.services.printing.backends.puqu_aq20 import PuquOptions, PuquAq20Backend
from app.services.printing.backends.zpl_tcp import ZplOptions, ZplSocketBackend, pack_gfa
from app.services.printing.base import LabelPrintRequest


class Ui:
    def __init__(self, answer=True):
        self.answer = answer
        self.seen: list[tuple[str, str]] = []

    def confirm(self, title, message):
        self.seen.append((title, message))
        return self.answer

    def warn(self, title, message):
        self.seen.append((title, message))


def qr_image(size=410):
    from PyQt6.QtGui import QImage
    from PyQt6.QtGui import QPainter

    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFF)
    painter = QPainter(img)
    painter.fillRect(0, 0, size // 2, size // 2, 0xFF000000)
    painter.end()
    return img


# --- Config schema ----------------------------------------------------------


def test_new_config_keys_parse():
    raw = yaml.safe_load(
        """
        label_printer:
          backend: "puqu_aq20"
          backends:
            puqu_aq20:
              printer_name: "PQ00"
              resolution_dpi: 203
        """
    )
    settings = AppSettings(**raw)
    assert settings.label_printer.backend == "puqu_aq20"
    assert settings.label_printer.backends["puqu_aq20"]["printer_name"] == "PQ00"


def test_old_config_without_new_keys_still_loads():
    """An operator's pre-upgrade config must keep working.

    The seven dead ZPL fields that used to live here are gone; pydantic ignores
    unknown keys, so their presence must not fail the load, and the new keys
    must fall back to their defaults.
    """
    raw = yaml.safe_load(
        """
        label_printer:
          enabled: false
          connection: "usb"
          tcp_host: ""
          tcp_port: 9100
          label_width_mm: 50
          label_height_mm: 25
          qr_size_mm: 25
        """
    )
    settings = AppSettings(**raw)
    assert settings.label_printer.backend == "system"
    assert settings.label_printer.backends == {}


def test_config_with_no_label_printer_section_at_all():
    settings = AppSettings(**yaml.safe_load("hw_revision: C"))
    assert settings.label_printer.backend == "system"


def test_unknown_backend_id_in_config_is_accepted_by_the_schema():
    # Validation of the id belongs to the selection layer, which degrades to the
    # system printer. The schema must not hard-fail and kill the app at import.
    settings = LabelPrinterSettings(backend="a_printer_from_the_future")
    assert settings.backend == "a_printer_from_the_future"


def test_backends_dict_accepts_a_shape_nobody_anticipated():
    settings = LabelPrinterSettings(
        backends={"whatever": {"nested": {"deep": [1, 2]}, "flag": True}}
    )
    assert settings.backends["whatever"]["nested"]["deep"] == [1, 2]


# --- PUQU options -----------------------------------------------------------


def test_puqu_defaults_match_the_aq20_hardware():
    # 203 dpi is from the vendor guide (AQ20.pdf p4).
    assert PuquOptions().resolution_dpi == 203
    assert PuquOptions().printer_name == ""


def test_puqu_rejects_a_nonsense_dpi():
    with pytest.raises(ValueError):
        PuquOptions(resolution_dpi=0)
    with pytest.raises(ValueError):
        PuquOptions(resolution_dpi=100000)


def test_puqu_invalid_stored_options_fall_back_to_defaults_not_a_crash():
    backend = PuquAq20Backend({"resolution_dpi": "not a number"})
    assert backend.options()["resolution_dpi"] == 203


def test_puqu_options_round_trip():
    backend = PuquAq20Backend({"printer_name": "PQ00", "resolution_dpi": 203})
    assert backend.options()["printer_name"] == "PQ00"


def test_puqu_is_unavailable_until_a_queue_is_chosen(qapp):
    backend = PuquAq20Backend({})
    availability = backend.refresh_availability()
    assert not availability
    assert "Printer Setup" in availability.detail


def test_puqu_refuses_a_queue_that_is_not_installed(qapp):
    """The critical safety case.

    QPrinter.setPrinterName() with an unknown name is silently ignored, leaving
    the printer pointed at the Windows default. A stale pinned name must
    therefore refuse rather than quietly print the label to the office MFP.
    """
    backend = PuquAq20Backend({"printer_name": "NO_SUCH_QUEUE_XYZ"})
    availability = backend.refresh_availability()
    assert not availability
    assert "NO_SUCH_QUEUE_XYZ" in availability.detail

    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    assert result.status is PrintStatus.UNAVAILABLE
    assert result.message  # the operator is told, not left in silence


def test_puqu_name_hints_sort_but_never_filter(qapp):
    backend = PuquAq20Backend({"name_hints": ["ZZZ_NOTHING_MATCHES"]})
    # No installed queue matches the hint, but every queue is still offered —
    # an operator whose driver installed oddly must still find it.
    from app.services.printing.qt_driver import available_printer_names

    assert len(backend.candidate_printers()) == len(available_printer_names())


def test_puqu_recognises_the_generic_pq00_queue_name(qapp):
    # PUQU's driver installs one queue named PQ00 for the whole range, not one
    # named AQ20 — matching only on "AQ20" would find nothing.
    backend = PuquAq20Backend({})
    assert backend.is_likely_puqu("PQ00")
    assert backend.is_likely_puqu("PUQU AQ20")
    assert not backend.is_likely_puqu("FUJI XEROX ApeosPort C3070")


# --- ZPL backend ------------------------------------------------------------


def test_zpl_options_validate():
    with pytest.raises(ValueError):
        ZplOptions(port=0)
    with pytest.raises(ValueError):
        ZplOptions(timeout_seconds=600)
    assert ZplOptions().port == 9100


def test_zpl_timeout_is_bounded():
    # print_label runs on the GUI thread; an unbounded connect would freeze the
    # tool for the ~21 s Windows SYN retry.
    assert ZplOptions().timeout_seconds <= 5


def test_zpl_is_unavailable_with_no_host():
    backend = ZplSocketBackend({})
    assert not backend.refresh_availability()
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    assert result.status is PrintStatus.UNAVAILABLE


def test_zpl_availability_does_no_network_io():
    # A routable-but-dead host must not make the dropdown block.
    backend = ZplSocketBackend({"host": "10.255.255.1", "port": 9100})
    import time

    start = time.monotonic()
    assert backend.refresh_availability()
    assert time.monotonic() - start < 0.1


def test_gfa_row_stride_rounds_up_to_whole_bytes():
    """A `w // 8` stride is invisible at 160 dots and shears at other widths."""
    from PyQt6.QtGui import QImage

    img = QImage(20, 3, QImage.Format.Format_Mono)
    img.fill(0)
    _data, total, per_row, rows = pack_gfa(img)
    assert per_row == 3  # ceil(20 / 8), not 2
    assert rows == 3
    assert total == 9


def test_gfa_polarity_is_one_bit_per_burnt_dot(qapp):
    from PyQt6.QtGui import QImage

    img = QImage(8, 1, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF)  # all white
    data, _total, _per_row, _rows = pack_gfa(img)
    assert data == "00"

    img.fill(0xFF000000)  # all black
    data, _total, _per_row, _rows = pack_gfa(img)
    assert data == "FF"


def test_zpl_job_pins_orientation_and_polarity(qapp):
    """A printer's saved ^POI/^LRY/^FWB would mirror or rotate every label."""
    backend = ZplSocketBackend({"host": "printer.local"})
    from app.services.printing.geometry import plan_label

    plan = plan_label(backend._metrics())
    zpl = backend.build_zpl(qr_image(), plan)
    assert zpl.startswith("^XA")
    assert zpl.endswith("^XZ")
    for command in ("^LH0,0", "^LRN", "^PON", "^FWN"):
        assert command in zpl
    # 20 mm at 203 dpi = 160 dots.
    assert "^PW160" in zpl
    assert "^LL160" in zpl
    assert "^GFA," in zpl


def test_zpl_sends_the_job_to_a_listening_socket(qapp):
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
    assert received[0].endswith(b"^XZ")


def test_zpl_unreachable_host_reports_an_error_not_a_crash(qapp):
    # Port 1 on loopback refuses immediately — no waiting on a timeout.
    backend = ZplSocketBackend({"host": "127.0.0.1", "port": 1, "timeout_seconds": 0.5})
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    assert result.status is PrintStatus.ERROR
    assert result.needs_dialog
    assert "127.0.0.1:1" in result.message


def test_zpl_mismatched_media_warns_with_honest_wording(qapp):
    """Config-derived metrics must not masquerade as a hardware measurement."""
    backend = ZplSocketBackend(
        {"host": "127.0.0.1", "port": 1, "label_width_mm": 50, "label_height_mm": 25}
    )
    ui = Ui(answer=False)
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=ui))
    assert result.status is PrintStatus.CANCELLED
    assert ui.seen[0][0] == "Configured label size is not 20 mm"


# --- Request validation -----------------------------------------------------


def test_a_null_image_is_rejected_at_the_boundary(qapp):
    """A null QImage draws as a no-op and would print a blank label."""
    from PyQt6.QtGui import QImage

    with pytest.raises(ValueError):
        LabelPrintRequest(image=QImage(), ui=Ui())
