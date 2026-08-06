"""Tests for printer selection, persistence, and failure containment."""

import json

import pytest

from app.services.printing import (
    Availability,
    BackendCapabilities,
    DictStore,
    PrinterSelection,
    Registry,
)
from app.services.printing.selection import SELECTED_BACKEND_KEY


class Stub:
    id = "stub"
    display_name = "Stub"
    capabilities = BackendCapabilities()
    sort_order = 50

    def __init__(self, options=None):
        self.opts = dict(options or {})

    def availability(self):
        return Availability(True)

    def refresh_availability(self):
        return Availability(True)

    def configure(self, parent):
        pass

    def print_label(self, request):
        pass

    def options(self):
        return dict(self.opts)

    def apply_options(self, options):
        self.opts.update(options or {})

    def actions(self):
        return ()


class SystemLike(Stub):
    id = "system"
    display_name = "System printer (any)"
    sort_order = 0


@pytest.fixture
def registry():
    reg = Registry()
    reg.register(SystemLike)
    reg.register(Stub)
    return reg


# --- Fallback behaviour -----------------------------------------------------


def test_unknown_saved_backend_falls_back_to_system(registry):
    store = DictStore({SELECTED_BACKEND_KEY: "printer_that_was_removed"})
    selection = PrinterSelection(registry=registry, store=store)
    assert selection.current_id() == "system"


def test_setting_an_unknown_id_falls_back_rather_than_crashing(registry):
    selection = PrinterSelection(registry=registry, store=DictStore())
    selection.set_current_id("nope")
    assert selection.current_id() == "system"


def test_fallback_used_when_no_selection_is_stored(registry):
    selection = PrinterSelection(registry=registry, store=DictStore())
    assert selection.current_id() == "system"


def test_configured_default_backend_is_honoured(registry):
    selection = PrinterSelection(
        registry=registry, store=DictStore(), default_backend_id="stub"
    )
    assert selection.current_id() == "stub"


def test_registry_without_system_still_yields_something(registry):
    reg = Registry()
    reg.register(Stub)
    selection = PrinterSelection(registry=reg, store=DictStore())
    assert selection.current_id() == "stub"


# --- Signals ----------------------------------------------------------------


def test_changed_signal_fires_once_per_real_change(qapp, registry):
    selection = PrinterSelection(registry=registry, store=DictStore())
    seen: list[str] = []
    selection.changed.connect(seen.append)

    selection.set_current_id("stub")
    assert seen == ["stub"]

    # Setting the same id again must be a no-op. Three combos share this object
    # and each echoes the change back; without the early return they would
    # re-enter the setter and rewrite settings once per widget.
    selection.set_current_id("stub")
    assert seen == ["stub"]


def test_two_combos_over_one_selection_emit_exactly_one_change(qapp, registry):
    from app.ui.widgets.printer_selector import PrinterSelectorCombo

    selection = PrinterSelection(registry=registry, store=DictStore())
    first = PrinterSelectorCombo(selection)
    second = PrinterSelectorCombo(selection)

    seen: list[str] = []
    selection.changed.connect(seen.append)

    first.setCurrentIndex(first.findData("stub"))

    assert seen == ["stub"]
    assert second.currentData() == "stub"  # the sibling followed


def test_combo_repopulation_does_not_look_like_a_user_choice(qapp, registry):
    from app.ui.widgets.printer_selector import PrinterSelectorCombo

    selection = PrinterSelection(registry=registry, store=DictStore())
    selection.set_current_id("stub")
    combo = PrinterSelectorCombo(selection)

    seen: list[str] = []
    selection.changed.connect(seen.append)
    combo.reload()

    assert seen == []
    assert combo.currentData() == "stub"


# --- Persistence ------------------------------------------------------------


def test_selection_is_written_to_the_store(registry):
    store = DictStore()
    PrinterSelection(registry=registry, store=store).set_current_id("stub")
    assert store.data[SELECTED_BACKEND_KEY] == "stub"


def test_options_persist_as_one_json_blob_per_backend(registry):
    store = DictStore()
    selection = PrinterSelection(registry=registry, store=store)
    selection.set_current_id("stub")
    selection.current_backend().apply_options({"a": 1, "b": {"c": [1, 2]}})
    selection.persist_current_options()

    raw = store.data["label_printer/backends/stub"]
    assert json.loads(raw) == {"a": 1, "b": {"c": [1, 2]}}


def test_corrupt_stored_options_fall_back_to_defaults(registry):
    store = DictStore({"label_printer/backends/stub": "{not json"})
    selection = PrinterSelection(
        registry=registry, store=store, defaults={"stub": {"a": 7}}
    )
    assert selection.load_options("stub") == {"a": 7}


def test_non_object_stored_options_are_ignored(registry):
    store = DictStore({"label_printer/backends/stub": "[1, 2, 3]"})
    selection = PrinterSelection(registry=registry, store=store)
    assert selection.load_options("stub") == {}


def test_stored_options_win_over_yaml_defaults(registry):
    store = DictStore({"label_printer/backends/stub": json.dumps({"a": 2})})
    selection = PrinterSelection(
        registry=registry, store=store, defaults={"stub": {"a": 1}}
    )
    assert selection.load_options("stub") == {"a": 2}


# --- Failure containment ----------------------------------------------------


def test_a_backend_that_explodes_on_init_does_not_take_down_the_app(registry):
    class Exploding(Stub):
        id = "boom"
        display_name = "Boom"

        def __init__(self, options=None):
            raise RuntimeError("vendor SDK missing")

    registry.register(Exploding)
    selection = PrinterSelection(registry=registry, store=DictStore())
    selection.set_current_id("boom")
    assert selection.current_backend() is None
    # And it still renders in the list, marked unavailable.
    rows = dict((r[0], r[2]) for r in selection.visible_backends())
    assert not rows["boom"]


def test_a_backend_that_raises_in_availability_is_contained(registry):
    class Raising(Stub):
        id = "raiser"
        display_name = "Raiser"

        def refresh_availability(self):
            raise RuntimeError("probe blew up")

    registry.register(Raising)
    selection = PrinterSelection(registry=registry, store=DictStore())
    availability = selection.availability_of("raiser")
    assert not availability
    assert availability.detail


def test_visible_backends_survives_a_broken_backend(qapp, registry):
    class Raising(Stub):
        id = "raiser"
        display_name = "Raiser"

        def refresh_availability(self):
            raise RuntimeError("probe blew up")

    registry.register(Raising)
    selection = PrinterSelection(registry=registry, store=DictStore())
    rows = selection.visible_backends()
    assert len(rows) == 3

    from app.ui.widgets.printer_selector import PrinterSelectorCombo

    combo = PrinterSelectorCombo(selection)
    assert combo.count() == 3


def test_persisting_non_json_options_does_not_raise(registry):
    class Weird(Stub):
        id = "weird"
        display_name = "Weird"

        def options(self):
            return {"bad": object()}

    registry.register(Weird)
    selection = PrinterSelection(registry=registry, store=DictStore())
    selection.set_current_id("weird")
    selection.persist_current_options()  # must not raise
