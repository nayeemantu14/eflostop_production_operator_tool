"""Shared pytest fixtures.

The suite is headless: QT_QPA_PLATFORM is forced to "offscreen" before any Qt
import so widget tests run without a desktop. This must happen at import time —
by the time a fixture runs, Qt has already chosen its platform plugin.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """One QApplication for the whole session.

    Qt allows only one per process and does not support recreating it, so this
    is session-scoped.

    `autouse` because forgetting it is not a normal test failure: constructing a
    QPrinter or a QWidget with no QApplication aborts the interpreter with
    0xC0000409, which pytest cannot catch or attribute. The run stops mid-file
    with a single dot and no summary, so the remaining tests are silently
    skipped rather than reported. Making it automatic removes the whole class of
    ordering-dependent failure — a suite that passes only because some earlier
    file happened to build the application is not passing.
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        # Match main.py so anything reading QSettings resolves the same path.
        app.setApplicationName("eFloStop II Production Tool")
        app.setOrganizationName("eFloStop")
    yield app
