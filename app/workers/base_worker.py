"""Base QThread worker with standard signals for flash/test operations."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal


class BaseWorker(QThread):
    """Base worker thread with standardized signals.

    Signals:
        progress(int): 0-100 progress percentage
        log_message(str, str): (message, level) where level is info/warn/error/debug
        step_update(str, str, str): (step_id, status, detail)
        finished_ok(dict): Emitted on success with result payload
        finished_fail(str): Emitted on failure with error message
    """

    progress = pyqtSignal(int)
    log_message = pyqtSignal(str, str)
    step_update = pyqtSignal(str, str, str)
    finished_ok = pyqtSignal(dict)
    finished_fail = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._abort = False

    def abort(self) -> None:
        """Request graceful abort."""
        self._abort = True

    @property
    def is_aborted(self) -> bool:
        return self._abort

    def log(self, message: str, level: str = "info") -> None:
        self.log_message.emit(message, level)

    def set_step(self, step_id: str, status: str, detail: str = "") -> None:
        self.step_update.emit(step_id, status, detail)

    def run(self) -> None:
        try:
            result = self.execute()
            if self._abort:
                self.finished_fail.emit("Aborted by user")
            else:
                self.finished_ok.emit(result or {})
        except Exception as e:
            self.finished_fail.emit(str(e))

    def execute(self) -> dict[str, Any] | None:
        """Override in subclass. Return result dict or None."""
        raise NotImplementedError
