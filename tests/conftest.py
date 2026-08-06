"""Shared pytest fixtures.

The suite is headless: QT_QPA_PLATFORM is forced to "offscreen" before any Qt
import so widget tests run without a desktop. This must happen at import time —
by the time a fixture runs, Qt has already chosen its platform plugin.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session.

    Qt allows only one per process and does not support recreating it, so this
    is session-scoped. Constructing any QWidget without it aborts the
    interpreter outright rather than raising, which would take down the run.
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        # Match main.py so anything reading QSettings resolves the same path.
        app.setApplicationName("eFloStop II Production Tool")
        app.setOrganizationName("eFloStop")
    yield app
