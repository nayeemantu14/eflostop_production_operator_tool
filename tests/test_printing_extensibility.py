"""Proof that a new printer needs one module and one registration.

This is the load-bearing test for the whole design. It defines a printer backend
that the production code has never heard of, registers it through the public
mechanism, and drives it all the way to the operator's dropdown and back —
without importing anything private, monkeypatching anything, or mutating any
global. If this test ever needs a hack to pass, the abstraction has leaked and
the abstraction is what should change.
"""

from typing import Any

import pytest

from app.services.printing import (
    Availability,
    BackendAction,
    BackendCapabilities,
    DictStore,
    LabelPrintRequest,
    PrinterSelection,
    PrintResult,
    PrintStatus,
    Registry,
    plan_label,
    run_guards,
)
from app.services.printing.geometry import (
    GuardOutcome,
    Margins,
    PrinterMetrics,
    mm_to_px,
)


class FakePrinterBackend:
    """A complete printer backend written entirely inside the test suite."""

    id = "fake_printer"
    display_name = "Fake Label Printer"
    capabilities = BackendCapabilities(configurable=True)
    sort_order = 5

    def __init__(self, options: dict[str, Any] | None = None):
        # Nested and list-valued options on purpose: a real future printer will
        # have them, and the persistence layer must not care.
        self._opts: dict[str, Any] = {
            "enabled": True,
            "dpi": 203,
            "media": {"w": 20.0, "h": 20.0, "gap": 3},
            "hosts": ["a", "b"],
        }
        self._margin_mm = 0.0
        self.printed: list[LabelPrintRequest] = []
        self.configured = 0
        self.apply_options(options or {})

    def availability(self) -> Availability:
        return Availability(bool(self._opts.get("enabled")), "fake offline")

    def refresh_availability(self) -> Availability:
        return self.availability()

    def configure(self, parent) -> None:
        self.configured += 1

    def options(self):
        return dict(self._opts)

    def apply_options(self, options):
        self._opts.update(options or {})
        self._margin_mm = float(self._opts.get("margin_mm", 0.0))

    def actions(self):
        return (BackendAction(label="Fake action", callback=lambda _p: None),)

    def print_label(self, request: LabelPrintRequest) -> PrintResult:
        if not self.availability():
            return PrintResult(PrintStatus.UNAVAILABLE, "Fake offline", "not ready")
        # Uses the SAME shared geometry and guards the shipped backends use.
        dpi = int(self._opts["dpi"])
        plan = plan_label(
            PrinterMetrics(
                page_w_px=mm_to_px(20, dpi),
                page_h_px=mm_to_px(20, dpi),
                media_w_mm=20.0,
                media_h_mm=20.0,
                margins_mm=Margins(*([self._margin_mm] * 4)),
                dpi=dpi,
            )
        )
        if run_guards(plan, request.ui) is GuardOutcome.ABORTED:
            return PrintResult(PrintStatus.CANCELLED)
        self.printed.append(request)
        return PrintResult(PrintStatus.OK)


class NoDialogUi:
    def __init__(self, answer=True):
        self.answer = answer
        self.seen: list[tuple[str, str]] = []

    def confirm(self, title, message):
        self.seen.append((title, message))
        return self.answer

    def warn(self, title, message):
        self.seen.append((title, message))


@pytest.fixture
def registry():
    """A registry containing the real backends plus the fake one."""
    from app.services.printing.backends import puqu_aq20, system, zpl_tcp

    reg = Registry()
    reg.register(system.SystemPrinterBackend)
    reg.register(puqu_aq20.PuquAq20Backend)
    reg.register(zpl_tcp.ZplSocketBackend)
    reg.register(FakePrinterBackend)
    return reg


@pytest.fixture
def selection(registry):
    return PrinterSelection(registry=registry, store=DictStore())


def qr_image():
    from PyQt6.QtGui import QImage

    img = QImage(410, 410, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFF)
    return img


# --- Registration and discovery ---------------------------------------------


def test_fake_backend_is_registered_through_the_public_api(registry):
    assert "fake_printer" in registry
    assert registry.get("fake_printer") is FakePrinterBackend


def test_fake_backend_appears_in_the_selection_list(selection):
    ids = [row[0] for row in selection.visible_backends()]
    assert "fake_printer" in ids


def test_fake_backend_sorts_where_it_declared(selection):
    # sort_order 5 puts it between system (0) and puqu_aq20 (10).
    ids = [row[0] for row in selection.visible_backends()]
    assert ids == ["system", "fake_printer", "puqu_aq20", "zpl_tcp"]


def test_fake_backend_appears_in_the_real_dropdown_widget(qapp, selection):
    """The actual QComboBox the operator sees, not a stand-in."""
    from app.ui.widgets.printer_selector import PrinterSelectorCombo

    combo = PrinterSelectorCombo(selection)
    data = [combo.itemData(i) for i in range(combo.count())]
    assert "fake_printer" in data
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert any("Fake Label Printer" in text for text in labels)


def test_fake_backend_is_selectable_from_the_dropdown(qapp, selection):
    from app.ui.widgets.printer_selector import PrinterSelectorCombo

    combo = PrinterSelectorCombo(selection)
    combo.setCurrentIndex(combo.findData("fake_printer"))
    assert selection.current_id() == "fake_printer"


# --- Selection, dispatch, persistence ---------------------------------------


def test_fake_backend_is_selectable_and_instantiated(selection):
    selection.set_current_id("fake_printer")
    assert selection.current_id() == "fake_printer"
    assert isinstance(selection.current_backend(), FakePrinterBackend)


def test_selection_returns_the_same_instance_every_time(selection):
    # Backends are created once per process: the system backend's QPrinter holds
    # the operator's session page setup and must survive switching away and back.
    selection.set_current_id("fake_printer")
    first = selection.current_backend()
    selection.set_current_id("system")
    selection.set_current_id("fake_printer")
    assert selection.current_backend() is first


def test_print_and_configure_dispatch_to_the_selected_backend(selection):
    selection.set_current_id("fake_printer")
    backend = selection.current_backend()
    backend.configure(None)
    result = backend.print_label(
        LabelPrintRequest(image=qr_image(), ui=NoDialogUi())
    )
    assert result.status is PrintStatus.OK
    assert backend.configured == 1
    assert len(backend.printed) == 1


def test_switching_backend_changes_what_would_be_printed(selection):
    selection.set_current_id("fake_printer")
    fake = selection.current_backend()
    selection.set_current_id("system")
    assert selection.current_backend() is not fake
    assert not isinstance(selection.current_backend(), FakePrinterBackend)


def test_selection_persists_and_round_trips(registry):
    store = DictStore()
    first = PrinterSelection(registry=registry, store=store)
    first.set_current_id("fake_printer")

    # A fresh selection over the same storage — i.e. the next app launch.
    second = PrinterSelection(registry=registry, store=store)
    assert second.current_id() == "fake_printer"


def test_nested_and_list_options_survive_persistence(registry):
    """The persistence layer must not need changing for a new option shape.

    QSettings' own typing is lossy across processes — a stored bool reads back
    as the string 'true' — so options go through JSON. Nested dicts and lists
    have to come back exactly as they went in.
    """
    store = DictStore()
    first = PrinterSelection(registry=registry, store=store)
    first.set_current_id("fake_printer")
    backend = first.current_backend()
    backend.apply_options({"enabled": False, "media": {"w": 20.0, "h": 10.0, "gap": 3}})
    first.persist_current_options()

    second = PrinterSelection(registry=registry, store=store)
    loaded = second.load_options("fake_printer")
    assert loaded["enabled"] is False
    assert loaded["media"] == {"w": 20.0, "h": 10.0, "gap": 3}
    assert loaded["hosts"] == ["a", "b"]
    assert isinstance(loaded["dpi"], int)


def test_yaml_defaults_seed_a_backend_that_has_no_stored_options(registry):
    selection = PrinterSelection(
        registry=registry,
        store=DictStore(),
        defaults={"fake_printer": {"dpi": 300}},
    )
    selection.set_current_id("fake_printer")
    assert selection.current_backend().options()["dpi"] == 300


# --- Inherited safety -------------------------------------------------------


def test_fake_backend_inherits_the_20mm_guards(selection):
    """A backend gets the safety guards by using the shared geometry."""
    selection.set_current_id("fake_printer")
    backend = selection.current_backend()
    # A 3 mm hardware margin shrinks a 20 mm label to 14 mm — under the floor.
    backend.apply_options({"margin_mm": 3.0})
    ui = NoDialogUi(answer=False)
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=ui))
    assert result.status is PrintStatus.CANCELLED
    assert ui.seen and ui.seen[0][0] == "QR would print under 20 mm"
    assert not backend.printed


def test_fake_backend_prints_clean_when_full_bleed(selection):
    selection.set_current_id("fake_printer")
    backend = selection.current_backend()
    ui = NoDialogUi()
    assert backend.print_label(
        LabelPrintRequest(image=qr_image(), ui=ui)
    ).status is PrintStatus.OK
    assert ui.seen == []  # no dialog on a healthy printer


def test_unavailable_backend_reports_instead_of_silently_doing_nothing(selection):
    selection.set_current_id("fake_printer")
    backend = selection.current_backend()
    backend.apply_options({"enabled": False})
    result = backend.print_label(LabelPrintRequest(image=qr_image(), ui=NoDialogUi()))
    assert result.status is PrintStatus.UNAVAILABLE
    assert result.needs_dialog  # the operator gets told


def test_fewer_capabilities_do_not_break_the_dropdown(qapp, registry):
    """A minimal backend must not break the UI."""

    class Minimal(FakePrinterBackend):
        id = "minimal"
        display_name = "Minimal"
        capabilities = BackendCapabilities(configurable=False)
        sort_order = 99

        def actions(self):
            return ()

    registry.register(Minimal)
    selection = PrinterSelection(registry=registry, store=DictStore())
    from app.ui.widgets.printer_selector import PrinterSelectorCombo

    combo = PrinterSelectorCombo(selection)
    assert "minimal" in [combo.itemData(i) for i in range(combo.count())]
    selection.set_current_id("minimal")
    assert selection.current_backend().capabilities.configurable is False
