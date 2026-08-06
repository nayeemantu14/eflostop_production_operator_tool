"""Dropdown for choosing which label printer to print to.

Knows nothing about any specific printer: it renders whatever
:meth:`PrinterSelection.visible_backends` returns and writes the chosen id back.
Adding a printer therefore needs no change here.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QWidget

from ...services.printing.selection import PrinterSelection


class PrinterSelectorCombo(QComboBox):
    """A view over the shared printer selection.

    Several of these exist at once — one per device tab — over a single
    selection object, and they stay in step through its ``changed`` signal.
    """

    def __init__(self, selection: PrinterSelection, parent: QWidget | None = None):
        super().__init__(parent)
        self._selection = selection
        self.setToolTip("Which printer the QR label is sent to")
        self.reload()
        self.currentIndexChanged.connect(self._on_user_choice)
        selection.changed.connect(self._on_selection_changed)
        # The backend instance is shared by every tab, so configuring the
        # printer on one tab has to refresh the annotation on the others —
        # otherwise they keep saying "no host configured" for a printer that is
        # now set up, for the rest of the session.
        selection.availability_changed.connect(self._on_availability_changed)

    def reload(self) -> None:
        """Rebuild the item list from the registry and current availability."""
        # Signals are blocked because clear()/addItem() move the current index
        # around; without this, repopulating would look like an operator choice
        # and write settings.
        blocked = self.blockSignals(True)
        try:
            self.clear()
            for backend_id, name, availability in self._selection.visible_backends():
                # Annotating the entry rather than adding a status line keeps the
                # QR panel from growing on all three tabs, and an operator never
                # gets to click Print on a printer that isn't there without
                # having been told.
                label = name if availability else f"{name} — {availability.detail}"
                self.addItem(label, backend_id)
                if not availability:
                    index = self.count() - 1
                    self.setItemData(
                        index,
                        f"{name} is not available: {availability.detail}",
                        Qt.ItemDataRole.ToolTipRole,
                    )
            self._sync_from_selection()
        finally:
            self.blockSignals(blocked)

    def _sync_from_selection(self) -> None:
        index = self.findData(self._selection.current_id())
        if index >= 0:
            self.setCurrentIndex(index)

    def _on_user_choice(self, _index: int) -> None:
        backend_id = self.currentData()
        if isinstance(backend_id, str) and backend_id:
            self._selection.set_current_id(backend_id)

    def _on_availability_changed(self, _backend_id: str) -> None:
        self.reload()

    def _on_selection_changed(self, _backend_id: str) -> None:
        """Follow a change made through another combo.

        Blocking signals here is what stops the three combos from ping-ponging:
        setCurrentIndex would otherwise emit currentIndexChanged and re-enter the
        setter once per sibling widget.
        """
        blocked = self.blockSignals(True)
        try:
            self._sync_from_selection()
        finally:
            self.blockSignals(blocked)
