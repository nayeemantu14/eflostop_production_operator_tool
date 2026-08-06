"""Tests for the backend registry and the shipped backends' contract."""

import subprocess
import sys
from pathlib import Path

import pytest

from app.services.printing import (
    BackendCapabilities,
    DuplicateBackendIdError,
    Registry,
    default_registry,
    describe,
    validate_registry,
)

ROOT = Path(__file__).resolve().parent.parent


class Dummy:
    id = "dummy"
    display_name = "Dummy"
    capabilities = BackendCapabilities()
    sort_order = 50

    def __init__(self, options=None):
        pass

    def availability(self):
        pass

    def refresh_availability(self):
        pass

    def configure(self, parent):
        pass

    def print_label(self, request):
        pass

    def options(self):
        return {}

    def apply_options(self, options):
        pass

    def actions(self):
        return ()


# --- Shipped backends -------------------------------------------------------


def test_shipped_backends_satisfy_the_contract():
    assert validate_registry() == []


def test_backend_ids_are_pinned():
    # Backend ids are written into the operator's saved settings. Renaming one
    # silently resets every machine that had it selected, so a rename must
    # break this test and be a deliberate, documented decision.
    assert set(default_registry().ids()) == {"system", "puqu_aq20", "zpl_tcp"}


def test_system_backend_exists_as_the_fallback():
    assert default_registry().get("system") is not None


def test_dropdown_order_is_declared_not_import_order():
    # sort_order, then display name — never wherever someone pasted the import.
    assert default_registry().ids() == ("system", "puqu_aq20", "zpl_tcp")


def test_registry_order_is_stable_across_calls():
    assert default_registry().ids() == default_registry().ids()


def test_every_backend_has_a_distinct_nonempty_display_name():
    rows = describe()
    names = [r["display_name"] for r in rows]
    assert all(names)
    assert len(set(names)) == len(names)


# --- Registry mechanics -----------------------------------------------------


def test_duplicate_id_is_rejected_loudly():
    # A contributor copy-pasting a backend must get an error, not a silently
    # shadowed printer that quietly steals the operator's selection.
    registry = Registry()
    registry.register(Dummy)
    with pytest.raises(DuplicateBackendIdError) as exc:
        registry.register(Dummy)
    assert "dummy" in str(exc.value)


def test_duplicate_id_message_names_both_classes():
    class OtherDummy(Dummy):
        pass

    registry = Registry()
    registry.register(Dummy)
    with pytest.raises(DuplicateBackendIdError) as exc:
        registry.register(OtherDummy)
    assert "Dummy" in str(exc.value)
    assert "OtherDummy" in str(exc.value)


def test_registry_rejects_a_backend_with_no_id():
    class NoId(Dummy):
        id = ""

    with pytest.raises(ValueError):
        Registry().register(NoId)


def test_registry_rejects_a_backend_with_no_display_name():
    class NoName(Dummy):
        id = "no_name"
        display_name = ""

    with pytest.raises(ValueError):
        Registry().register(NoName)


def test_registry_sorts_by_sort_order_then_name():
    class Late(Dummy):
        id = "late"
        display_name = "Late"
        sort_order = 90

    class Early(Dummy):
        id = "early"
        display_name = "Early"
        sort_order = 1

    registry = Registry()
    registry.register(Late)
    registry.register(Early)
    assert registry.ids() == ("early", "late")


def test_validate_registry_flags_a_missing_fallback():
    registry = Registry()
    registry.register(Dummy)
    problems = validate_registry(registry)
    assert any("system" in p for p in problems)


def test_validate_registry_flags_a_missing_method():
    class Broken(Dummy):
        id = "broken"
        print_label = None

    registry = Registry()
    registry.register(Broken)
    assert any("print_label" in p for p in validate_registry(registry))


# --- Import safety ----------------------------------------------------------


def test_package_imports_without_a_qapplication():
    """Importing the printing package must not construct a Qt object.

    Run in a subprocess because the failure mode is not an exception: creating a
    QPrinter or a QWidget before a QApplication exists fast-fails the whole
    interpreter, which an in-process test cannot catch — it would just take the
    pytest run down with it.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import app.services.printing.backends"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"importing the backends package crashed (exit {result.returncode}).\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_registry_is_populated_by_import_alone():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.services.printing as p; print(','.join(p.default_registry().ids()))",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "system,puqu_aq20,zpl_tcp"
