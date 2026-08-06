"""Pluggable label-printer backends.

The tool prints one thing — a 20 mm x 20 mm QR label — but the printer that
prints it varies by production line and changes over time. This package holds
the contract every printer implements, the shared geometry and safety guards
they all inherit, and the registry the operator's dropdown is built from.

Importing this package registers the shipped backends. See
docs/PRINTER_BACKENDS.md to add another.
"""

from __future__ import annotations

from .base import (
    Availability,
    BackendAction,
    BackendCapabilities,
    LabelPrinterBackend,
    LabelPrintRequest,
    PrintResult,
    PrintStatus,
)
from .geometry import (
    QR_LABEL_SIZE_MM,
    QR_MIN_PRINT_MM,
    GuardOutcome,
    GuardUi,
    LabelPlan,
    Margins,
    PrinterMetrics,
    is_undersized,
    mm_to_px,
    plan_label,
    px_to_mm,
    run_guards,
)
from .registry import (
    FALLBACK_BACKEND_ID,
    DuplicateBackendIdError,
    Registry,
    default_registry,
    describe,
    register_backend,
    validate_registry,
)
from .selection import (
    DictStore,
    PrinterSelection,
    QSettingsStore,
    SettingsStore,
    reset_shared_selection,
    shared_selection,
)

# Imported for its side effect: each backend module registers itself, so any
# importer of this package sees a populated registry. Last, so the names above
# are bound before the backends import them.
from . import backends  # noqa: E402,F401  isort:skip

__all__ = [
    "Availability",
    "BackendAction",
    "BackendCapabilities",
    "DictStore",
    "DuplicateBackendIdError",
    "FALLBACK_BACKEND_ID",
    "GuardOutcome",
    "GuardUi",
    "LabelPlan",
    "LabelPrintRequest",
    "LabelPrinterBackend",
    "Margins",
    "PrintResult",
    "PrintStatus",
    "PrinterMetrics",
    "PrinterSelection",
    "QR_LABEL_SIZE_MM",
    "QR_MIN_PRINT_MM",
    "QSettingsStore",
    "Registry",
    "SettingsStore",
    "backends",
    "default_registry",
    "describe",
    "is_undersized",
    "mm_to_px",
    "plan_label",
    "px_to_mm",
    "register_backend",
    "reset_shared_selection",
    "run_guards",
    "shared_selection",
    "validate_registry",
]
