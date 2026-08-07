"""Tests for driving the AQ20 over an LPT port.

Windows does not bind this printer the same way on every machine. On the
production PC it came up as LPT1, which pyserial cannot open at all — it filters
LPT out of its own enumeration — so those bytes go to the DOS device directly.
"""

import time

from PyQt6.QtGui import QImage

from app.services.printing import PrintStatus
from app.services.printing.backends.puqu_aq20_serial import (
    PuquAq20SerialBackend,
    is_parallel_port,
)
from app.services.printing.base import LabelPrintRequest


class Ui:
    def confirm(self, title, message):
        return True

    def warn(self, title, message):
        pass


def qr_image() -> QImage:
    img = QImage(410, 410, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF)
    return img


def fake_port(name, description=""):
    return type("P", (), {"port": name, "description": description})()


class FakeRawPort:
    """Stands in for an opened LPT device."""

    def __init__(self, sink, delay=0.0):
        self.sink = sink
        time.sleep(delay)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def write(self, data):
        self.sink.append(data)


# --- Classification ---------------------------------------------------------


def test_lpt_names_are_recognised():
    for name in ("LPT1", "lpt1", "LPT9"):
        assert is_parallel_port(name)


def test_com_and_empty_names_are_not_parallel():
    for name in ("COM1", "COM30", "", "USB001"):
        assert not is_parallel_port(name)


def test_parallel_port_discovery_never_raises():
    """QueryDosDevice on Windows, an empty list everywhere else."""
    from app.services.port_detector import find_parallel_ports

    ports = find_parallel_ports()
    assert isinstance(ports, list)
    assert all(p.port.startswith("LPT") for p in ports)


# --- Enumeration ------------------------------------------------------------


def test_lpt_ports_are_offered_alongside_com_ports(monkeypatch):
    from app.services.printing.backends import puqu_aq20_serial as mod

    monkeypatch.setattr(mod, "find_all_serial_ports", lambda: [fake_port("COM30", "CP210x")])
    monkeypatch.setattr(mod, "find_parallel_ports", lambda: [fake_port("LPT1", "Parallel")])

    names = [p.port for p in mod.available_ports()]
    assert "LPT1" in names and "COM30" in names


def test_an_lpt_port_counts_as_available(monkeypatch):
    from app.services.printing.backends import puqu_aq20_serial as mod

    monkeypatch.setattr(mod, "find_all_serial_ports", lambda: [])
    monkeypatch.setattr(mod, "find_parallel_ports", lambda: [fake_port("LPT1")])

    backend = PuquAq20SerialBackend({"port": "LPT1"})
    availability = backend.refresh_availability()
    assert availability
    assert availability.detail == "LPT1"


def test_a_missing_lpt_port_is_refused_by_name(monkeypatch):
    from app.services.printing.backends import puqu_aq20_serial as mod

    monkeypatch.setattr(mod, "find_all_serial_ports", lambda: [])
    monkeypatch.setattr(mod, "find_parallel_ports", lambda: [])

    backend = PuquAq20SerialBackend({"port": "LPT1"})
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    assert result.status is PrintStatus.UNAVAILABLE
    assert "LPT1" in result.message


# --- The write path ---------------------------------------------------------


def test_lpt_bypasses_pyserial_entirely(monkeypatch):
    """pyserial cannot open an LPT port; using it would raise every time."""
    from app.services.printing.backends import puqu_aq20_serial as mod

    written: list = []

    def boom(*a, **k):
        raise AssertionError("pyserial must not be used for an LPT port")

    monkeypatch.setattr(mod.serial, "Serial", boom)
    monkeypatch.setattr(mod, "open_raw_port", lambda name: FakeRawPort(written))
    monkeypatch.setattr(mod, "find_all_serial_ports", lambda: [])
    monkeypatch.setattr(mod, "find_parallel_ports", lambda: [fake_port("LPT1")])

    backend = PuquAq20SerialBackend({"port": "LPT1"})
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))

    assert result.status is PrintStatus.OK
    assert len(written) == 1
    assert written[0].startswith(b"SIZE 20 mm,20 mm")
    assert written[0].endswith(b"PRINT 1,1\r\n")


def test_lpt_device_path_is_the_windows_dos_name():
    """`\\\\.\\LPT1` is the form that reaches the device rather than a file."""
    import inspect

    from app.services.printing.backends import puqu_aq20_serial as mod

    source = inspect.getsource(mod.open_raw_port)
    assert r"\\.\'" in source or r"\\." in source


def test_a_timed_out_lpt_job_must_never_print(monkeypatch):
    """The disown check has to cover the LPT path too, not just serial.

    An LPT open has no timeout of its own, so this is exactly where a slow
    printer could print a label after the operator was told it failed.
    """
    from app.services.printing.backends import puqu_aq20_serial as mod

    written: list = []
    monkeypatch.setattr(mod, "open_raw_port", lambda name: FakeRawPort(written, delay=1.5))
    monkeypatch.setattr(mod, "find_all_serial_ports", lambda: [])
    monkeypatch.setattr(mod, "find_parallel_ports", lambda: [fake_port("LPT1")])

    backend = PuquAq20SerialBackend({"port": "LPT1", "timeout_seconds": 0.2})
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    assert result.status is PrintStatus.ERROR

    time.sleep(2.5)
    assert written == [], "an abandoned LPT job printed after being reported failed"


def test_lpt_open_failure_is_reported_not_raised(monkeypatch):
    from app.services.printing.backends import puqu_aq20_serial as mod

    def denied(name):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(mod, "open_raw_port", denied)
    monkeypatch.setattr(mod, "find_all_serial_ports", lambda: [])
    monkeypatch.setattr(mod, "find_parallel_ports", lambda: [fake_port("LPT1")])

    backend = PuquAq20SerialBackend({"port": "LPT1"})
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=Ui()))
    assert result.status is PrintStatus.ERROR
    assert "Access is denied" in result.message
    assert result.needs_dialog


# --- Setup dialog -----------------------------------------------------------


def test_dialog_lists_lpt_and_disables_baud_for_it(monkeypatch):
    from app.services.printing.backends import puqu_aq20_serial as mod

    monkeypatch.setattr(mod, "find_all_serial_ports", lambda: [fake_port("COM30", "CP210x")])
    monkeypatch.setattr(mod, "find_parallel_ports", lambda: [fake_port("LPT1", "Parallel")])

    backend = PuquAq20SerialBackend({"port": "LPT1"})
    dialog = mod._TsplSerialSetupDialog(backend._opts, None)

    assert "LPT1" in [dialog._port.itemData(i) for i in range(dialog._port.count())]
    assert dialog.selected_port() == "LPT1"
    assert not dialog._baud.isEnabled(), "baud rate is meaningless on an LPT port"

    dialog._port.setCurrentIndex(dialog._port.findData("COM30"))
    assert dialog._baud.isEnabled(), "baud rate must come back for a COM port"
