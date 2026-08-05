"""ESP32-S3 flasher using esptool Python library."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

from .base_worker import BaseWorker


class EspFlasher(BaseWorker):
    """Flash ESP32-S3 firmware using esptool library."""

    def __init__(
        self,
        port: str,
        firmware_files: list[tuple[int, Path]],
        baud: int = 460800,
        flash_size: str = "detect",
        parent=None,
    ):
        super().__init__(parent)
        self.port = port
        self.firmware_files = firmware_files  # [(offset, path), ...]
        self.baud = baud
        self.flash_size = flash_size

    def execute(self) -> dict[str, Any]:
        import esptool
        import esptool.cmds

        self.set_step("flash_firmware", "running", "Erasing & writing firmware...")
        self.log(f"Connecting to {self.port} at {self.baud} baud")
        self.log(f"Writing {len(self.firmware_files)} file(s) (full erase first)...")
        for offset, path in self.firmware_files:
            self.log(f"  {hex(offset)}: {path.name}")

        # Erase entire flash + write firmware in a single esptool invocation.
        # Using --erase-all avoids a disconnect/reconnect between erase and write.
        args = [
            "--port", self.port,
            "--baud", str(self.baud),
            "--chip", "esp32s3",
            "write_flash",
            "--erase-all",
            "--flash_mode", "dio",
            "--flash_freq", "80m",
            "--flash_size", self.flash_size,
        ]

        for offset, path in self.firmware_files:
            if not path.exists():
                raise FileNotFoundError(f"Firmware file not found: {path}")
            args.extend([hex(offset), str(path)])

        output = self._run_esptool(esptool, args)
        self.progress.emit(80)

        # Read MAC address
        self.log("Reading MAC address...")
        mac = self._read_mac()

        self.progress.emit(100)
        self.set_step("flash_firmware", "pass", f"MAC: {mac}")
        self.log(f"Flash complete. Base MAC: {mac}")

        return {"base_mac": mac, "esptool_output": output}

    def _run_esptool(self, esptool, args: list[str]) -> str:
        """Run an esptool command, capture and log output."""
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        capture = io.StringIO()
        sys.stdout = capture
        sys.stderr = capture
        try:
            esptool.main(args)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        output = capture.getvalue()
        for line in output.splitlines():
            line = line.strip()
            if line:
                self.log(line, "debug")
        return output

    def _read_mac(self) -> str:
        """Read the base MAC address using esptool."""
        import esptool
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        capture = io.StringIO()
        sys.stdout = capture
        sys.stderr = capture

        try:
            esptool.main([
                "--port", self.port,
                "--chip", "esp32s3",
                "read_mac",
            ])
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        output = capture.getvalue()
        # Parse: MAC: aa:bb:cc:dd:ee:ff
        for line in output.splitlines():
            if "MAC:" in line.upper():
                parts = line.split("MAC:")
                if len(parts) > 1:
                    mac = parts[-1].strip()
                    # Normalize format
                    mac = mac.upper().replace("-", ":")
                    return mac
        return "UNKNOWN"
