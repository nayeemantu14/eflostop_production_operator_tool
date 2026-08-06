"""Tests for the PuQu AQ20 serial (TSPL) backend.

The TSPL command semantics asserted here come from TSC's TSPL/TSPL2 Programming
Manual. The bitmap polarity is the one thing no document settles, so it is
pinned hard: getting it backwards prints a photographic negative that no scanner
will read, and it would be an easy thing to "tidy up".
"""

import time

import pytest
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


def solid(width: int, height: int, white: bool) -> QImage:
    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF if white else 0xFF000000)
    return img


def qr_image() -> QImage:
    return solid(410, 410, white=True)


# --- Bitmap packing ---------------------------------------------------------


def test_black_packs_to_zero_bits():
    """TSPL prints a dot where the bit is 0 — the inverse of ZPL's ^GFA.

    If this ever flips, every label prints as solid black with a white QR.
    """
    data, width_bytes, height = pack_tspl_bitmap(solid(8, 1, white=False))
    assert data == b"\x00"
    assert (width_bytes, height) == (1, 1)


def test_white_packs_to_one_bits():
    data, _w, _h = pack_tspl_bitmap(solid(8, 1, white=True))
    assert data == b"\xff"


def test_invert_flag_swaps_polarity():
    """The bench escape hatch, for firmware that disagrees with the manual."""
    assert pack_tspl_bitmap(solid(8, 1, white=False), invert=True) == (b"\xff", 1, 1)
    assert pack_tspl_bitmap(solid(8, 1, white=True), invert=True) == (b"\x00", 1, 1)


def test_row_stride_rounds_up_to_whole_bytes():
    """A floor division would shear the image diagonally at 17 dots wide."""
    data, width_bytes, height = pack_tspl_bitmap(solid(17, 3, white=True))
    assert width_bytes == 3  # ceil(17/8), not 2
    assert height == 3
    assert len(data) == 9


def test_padding_bits_are_left_unprinted():
    """The 7 bits past a 17-dot row must not burn a black stripe."""
    data, width_bytes, _h = pack_tspl_bitmap(solid(17, 1, white=False))
    # First two bytes fully black (0x00); third has one dark dot then padding.
    assert data[0] == 0x00 and data[1] == 0x00
    assert data[2] == 0b01111111  # only bit 7 cleared; padding stays 1 = blank


def test_twenty_mm_at_203dpi_is_twenty_bytes_per_row():
    data, width_bytes, height = pack_tspl_bitmap(solid(160, 160, white=True))
    assert (width_bytes, height) == (20, 160)
    assert len(data) == 20 * 160


# --- TSPL job structure -----------------------------------------------------


def build_job(**opts) -> bytes:
    backend = PuquAq20SerialBackend({"port": "COM9", **opts})
    plan = plan_label(backend._metrics())
    return backend.build_tspl(qr_image(), plan)


def test_job_has_the_required_commands_in_order():
    job = build_job()
    text = job.split(b"BITMAP")[0].decode("ascii")
    order = [text.index(c) for c in ("SIZE", "GAP", "DIRECTION", "REFERENCE",
                                     "DENSITY", "SPEED", "CLS")]
    assert order == sorted(order), "TSPL commands are out of order"
    # The manual is explicit: CLS must come after SIZE.
    assert text.index("SIZE") < text.index("CLS")


def test_size_command_has_the_space_before_mm():
    """TSPL requires a space between the value and the unit."""
    assert b"SIZE 20 mm,20 mm" in build_job()
    assert b"GAP 2 mm,0 mm" in build_job()


def test_direction_disables_mirroring():
    """DIRECTION's second argument is a mirror flag the printer remembers.

    A mirrored QR is unscannable and nothing in the tool could detect it, so it
    is set explicitly on every job rather than assumed.
    """
    assert b"DIRECTION 0,0" in build_job()


def test_reference_origin_is_pinned():
    assert b"REFERENCE 0,0" in build_job()


def test_density_and_speed_come_from_options():
    job = build_job(density=12, speed=4)
    assert b"DENSITY 12" in job
    assert b"SPEED 4" in job


def parse_bitmap(job: bytes) -> tuple[list[int], bytes]:
    """Split a job into the BITMAP header's 5 ints and the raw data after it.

    Parsed by counting commas rather than splitting on a literal, because the
    header's own coordinates contain the same byte sequences the data does.
    """
    after = job.split(b"BITMAP ", 1)[1]
    fields, rest, count = [], after, 0
    while count < 5:
        field, rest = rest.split(b",", 1)
        fields.append(int(field))
        count += 1
    return fields, rest


def test_bitmap_header_declares_bytes_and_dots():
    """BITMAP width is in BYTES and height in DOTS — mixing them up clips."""
    (x, y, width_bytes, height, mode), _data = parse_bitmap(build_job())
    assert width_bytes == 20  # 160 dots / 8
    assert height == 160  # dots
    assert x % 8 == 0  # byte-aligned column
    assert y >= 0
    assert mode == 0  # OVERWRITE


def test_job_ends_with_print_and_crlf():
    assert build_job().endswith(b"PRINT 1,1\r\n")


def test_job_payload_length_matches_the_declared_bitmap():
    """The declared width x height must be exactly the bytes that follow.

    A mismatch makes the printer read the trailing PRINT command as image data
    (or truncate the image), so nothing prints and nothing reports an error.
    """
    (_x, _y, width_bytes, height, _mode), rest = parse_bitmap(build_job())
    expected = width_bytes * height
    assert len(rest) == expected + len(b"\r\nPRINT 1,1\r\n")
    assert rest[expected:] == b"\r\nPRINT 1,1\r\n"


def test_label_size_flows_into_the_job():
    job = build_job(label_width_mm=40, label_height_mm=30)
    assert b"SIZE 40 mm,30 mm" in job


# --- Shared geometry and guards ---------------------------------------------


def test_uses_the_shared_20mm_geometry():
    backend = PuquAq20SerialBackend({"port": "COM9"})
    plan = plan_label(backend._metrics())
    assert plan.side == 160  # 20 mm at 203 dpi
    assert plan.media_ok
    assert not plan.undersized


def test_wrong_label_size_warns_with_honest_wording(monkeypatch):
    """Config-derived metrics must not masquerade as a hardware measurement."""
    from app.services.printing.backends import puqu_aq20_serial as mod

    # The port has to look present, or availability refuses before the guards.
    monkeypatch.setattr(
        mod, "find_all_serial_ports",
        lambda: [type("P", (), {"port": "COM9", "description": ""})()],
    )
    backend = PuquAq20SerialBackend(
        {"port": "COM9", "label_width_mm": 50, "label_height_mm": 25}
    )
    ui = Ui(answer=False)
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=ui))
    assert result.status is PrintStatus.CANCELLED
    assert ui.confirms[0][0] == "Configured label size is not 20 mm"


def test_availability_is_checked_before_the_guards():
    """A missing port must be reported before the operator answers a dialog."""
    backend = PuquAq20SerialBackend(
        {"port": "COM_GONE_42", "label_width_mm": 50, "label_height_mm": 25}
    )
    ui = Ui(answer=True)
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=ui))
    assert result.status is PrintStatus.UNAVAILABLE
    assert ui.confirms == []  # no pointless guard dialog for an absent printer


# --- Options validation -----------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"density": 16}, {"density": -1},
        {"speed": 0}, {"speed": 99},
        {"dpi": 0}, {"dpi": 99999},
        {"baudrate": 1}, {"gap_mm": -1}, {"gap_mm": 100},
        {"label_width_mm": 0}, {"label_height_mm": 500},
        {"timeout_seconds": 0}, {"timeout_seconds": 120},
    ],
)
def test_out_of_range_options_are_rejected(kwargs):
    with pytest.raises(ValueError):
        TsplSerialOptions(**kwargs)


def test_defaults_match_the_aq20_and_the_label_spec():
    o = TsplSerialOptions()
    assert o.dpi == 203  # AQ20 print head
    assert o.label_width_mm == 20 and o.label_height_mm == 20
    assert o.density == 8  # TSPL manual default
    assert o.invert is False


def test_invalid_stored_options_fall_back_instead_of_crashing():
    backend = PuquAq20SerialBackend({"density": "loud", "port": "COM9"})
    assert backend.options()["density"] == 8


def test_options_round_trip():
    backend = PuquAq20SerialBackend({"port": "COM7", "invert": True, "density": 11})
    opts = backend.options()
    assert opts["port"] == "COM7"
    assert opts["invert"] is True
    assert opts["density"] == 11


# --- Serial safety ----------------------------------------------------------


def test_availability_does_no_serial_io():
    """It runs while the dropdown is painted, so it must be instant."""
    backend = PuquAq20SerialBackend({"port": "COM9"})
    start = time.monotonic()
    backend.refresh_availability()
    assert time.monotonic() - start < 0.2


def test_unconfigured_port_reports_instead_of_silence():
    backend = PuquAq20SerialBackend({})
    assert not backend.refresh_availability()
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    assert result.status is PrintStatus.UNAVAILABLE
    assert "Printer Setup" in result.message


def test_absent_port_is_refused_by_name():
    backend = PuquAq20SerialBackend({"port": "COM_NOT_REAL_99"})
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    assert result.status is PrintStatus.UNAVAILABLE
    assert "COM_NOT_REAL_99" in result.message


def test_a_hung_port_cannot_freeze_the_ui(monkeypatch):
    """The point of the worker thread.

    pyserial's timeouts do not cover open(), and opening a Bluetooth COM port
    can block for seconds. A print must fail within a bounded time regardless.
    """
    from app.services.printing.backends import puqu_aq20_serial as mod

    class HangingSerial:
        def __init__(self, *a, **k):
            time.sleep(30)  # never returns within the budget

    monkeypatch.setattr(mod.serial, "Serial", HangingSerial)
    monkeypatch.setattr(
        mod, "find_all_serial_ports",
        lambda: [type("P", (), {"port": "COM9", "description": ""})()],
    )

    backend = PuquAq20SerialBackend({"port": "COM9", "timeout_seconds": 0.5})
    start = time.monotonic()
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    elapsed = time.monotonic() - start

    assert result.status is PrintStatus.ERROR
    assert elapsed < 5.0, f"blocked for {elapsed:.1f}s — the UI would have frozen"
    assert "did not respond" in result.message


def test_serial_exception_is_reported_not_raised(monkeypatch):
    from app.services.printing.backends import puqu_aq20_serial as mod

    def boom(*a, **k):
        raise mod.serial.SerialException("Access is denied")

    monkeypatch.setattr(mod.serial, "Serial", boom)
    monkeypatch.setattr(
        mod, "find_all_serial_ports",
        lambda: [type("P", (), {"port": "COM9", "description": ""})()],
    )

    backend = PuquAq20SerialBackend({"port": "COM9"})
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    assert result.status is PrintStatus.ERROR
    assert "Access is denied" in result.message
    assert result.needs_dialog


def test_the_full_job_reaches_the_port(monkeypatch):
    from app.services.printing.backends import puqu_aq20_serial as mod

    written: list[bytes] = []

    class FakeSerial:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def write(self, data):
            written.append(data)

        def flush(self):
            pass

    monkeypatch.setattr(mod.serial, "Serial", FakeSerial)
    monkeypatch.setattr(
        mod, "find_all_serial_ports",
        lambda: [type("P", (), {"port": "COM9", "description": ""})()],
    )

    backend = PuquAq20SerialBackend({"port": "COM9"})
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))

    assert result.status is PrintStatus.OK
    assert len(written) == 1
    job = written[0]
    assert job.startswith(b"SIZE 20 mm,20 mm")
    assert job.endswith(b"PRINT 1,1\r\n")
    assert b"DIRECTION 0,0" in job


# --- Registration -----------------------------------------------------------


def test_backend_is_registered_between_the_driver_aq20_and_zpl():
    from app.services.printing import default_registry

    assert default_registry().ids() == (
        "system", "puqu_aq20", "puqu_aq20_serial", "zpl_tcp",
    )


def test_the_driver_based_aq20_backend_still_exists():
    """The serial backend is added alongside it, not instead of it."""
    from app.services.printing import default_registry

    assert default_registry().get("puqu_aq20") is not None
    assert default_registry().get("puqu_aq20_serial") is not None


def test_port_enumeration_includes_ports_without_a_usb_vid():
    """A Bluetooth-paired printer has no VID and must still be selectable."""
    import serial.tools.list_ports

    from app.services.port_detector import find_all_serial_ports

    assert len(find_all_serial_ports()) == len(list(serial.tools.list_ports.comports()))
