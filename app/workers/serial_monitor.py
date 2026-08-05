"""Serial port monitor thread for capturing boot logs."""

from __future__ import annotations

import time

from PyQt6.QtCore import QThread, pyqtSignal
import serial


class SerialMonitor(QThread):
    """Read serial port line-by-line and emit signals.

    Signals:
        line_received(str): Each line read from serial
        error(str): Error message if port fails
    """

    line_received = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        port: str,
        baud: int = 115200,
        timeout: float = 0.5,
        parent=None,
    ):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self._stop = False
        self._lines: list[str] = []

    def stop(self) -> None:
        self._stop = True

    @property
    def captured_lines(self) -> list[str]:
        return list(self._lines)

    @property
    def captured_text(self) -> str:
        return "\n".join(self._lines)

    def run(self) -> None:
        # Retry on port open — ST-Link CLI may still be releasing the COM
        # after the hard reset, and Windows serial ports are exclusive-access.
        ser = None
        last_err: Exception | None = None
        deadline = time.monotonic() + 3.0  # 3s budget for the port to free up
        while time.monotonic() < deadline and not self._stop:
            try:
                ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
                break
            except serial.SerialException as e:
                last_err = e
                time.sleep(0.25)
        if ser is None:
            msg = str(last_err) if last_err else "unknown"
            self.error.emit(f"Cannot open {self.port} after 3s retry: {msg}")
            return

        try:
            while not self._stop:
                try:
                    raw = ser.readline()
                    if raw:
                        line = raw.decode("utf-8", errors="replace").rstrip()
                        self._lines.append(line)
                        self.line_received.emit(line)
                except serial.SerialException as e:
                    self.error.emit(f"Serial read error: {e}")
                    break
        finally:
            ser.close()
