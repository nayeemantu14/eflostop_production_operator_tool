"""Registration point for every label-printer backend.

ADDING A PRINTER: write one module in this package and add one import line
below. That is the whole procedure — see docs/PRINTER_BACKENDS.md.

Keep these as plain `from . import x` statements. Discovery via pkgutil or
importlib would look tidier here and break the shipped product: PyInstaller
resolves what to bundle by walking the static import graph, so a dynamically
imported backend works from source and is missing from the frozen .exe.
"""

from __future__ import annotations

from . import puqu_aq20  # noqa: F401
from . import system  # noqa: F401
from . import zpl_tcp  # noqa: F401

__all__ = ["puqu_aq20", "system", "zpl_tcp"]
