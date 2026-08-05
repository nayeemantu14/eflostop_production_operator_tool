"""STM32 flasher using STM32_Programmer_CLI subprocess."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .base_worker import BaseWorker


class STM32Flasher(BaseWorker):
    """Base flasher for STM32 devices via STM32_Programmer_CLI."""

    def __init__(self, cli_path: Path, parent=None):
        super().__init__(parent)
        self.cli_path = cli_path

    def _run_cli(self, args: list[str], timeout: int = 120) -> str:
        """Run STM32_Programmer_CLI with given arguments.

        Returns stdout+stderr combined output.
        Raises RuntimeError on non-zero exit or timeout.
        """
        cmd = [str(self.cli_path)] + args
        self.log(f"Running: {' '.join(cmd)}", "debug")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            output_lines: list[str] = []
            for line in iter(proc.stdout.readline, ""):  # type: ignore[union-attr]
                line = line.rstrip()
                if line:
                    output_lines.append(line)
                    self.log(line, "debug")
                    # Parse progress from CLI output
                    pct_match = re.search(r"(\d+)%", line)
                    if pct_match:
                        self.progress.emit(int(pct_match.group(1)))

                if self.is_aborted:
                    proc.kill()
                    raise RuntimeError("Aborted by user")

            proc.wait(timeout=timeout)
            output = "\n".join(output_lines)

            if proc.returncode != 0:
                raise RuntimeError(
                    f"STM32_Programmer_CLI exited with code {proc.returncode}:\n{output}"
                )

            return output

        except subprocess.TimeoutExpired:
            proc.kill()  # type: ignore[possibly-undefined]
            raise RuntimeError(f"STM32_Programmer_CLI timed out after {timeout}s")

    def read_mcu_id(self, address: int) -> int:
        """Read MCU DEV_ID at given address. Returns the ID value.

        Output format: "0xE0042000 : 20036495"
        DEV_ID is the lower 12 bits of the IDCODE register.
        """
        output = self._run_cli([
            "-c", "port=swd", "mode=UR",
            "-r32", hex(address), "4",
        ])
        for line in output.splitlines():
            match = re.search(r"0x[0-9A-Fa-f]+\s*:\s*([0-9A-Fa-f]+)", line)
            if match:
                raw = int(match.group(1), 16)
                return raw & 0xFFF
        raise RuntimeError(f"Could not parse MCU ID from address {hex(address)}")

    def read_uid(self, address: int) -> str:
        """Read 96-bit UID (3 x 32-bit words). Returns hex string.

        STM32_Programmer_CLI -r32 prints all requested words on a single line:
            0x1FFF7590 : 001A002D 4730500B 20373458
        We must extract every hex token after the colon, not just the first.
        """
        output = self._run_cli([
            "-c", "port=swd", "mode=UR",
            "-r32", hex(address), "12",  # 12 bytes = 3 x 32-bit words
        ])
        uid_words: list[str] = []
        for line in output.splitlines():
            # Match address prefix, then capture everything after the colon
            match = re.search(r"0x[0-9A-Fa-f]+\s*:\s*(.+)$", line)
            if match:
                for token in match.group(1).split():
                    if re.fullmatch(r"[0-9A-Fa-f]{1,8}", token):
                        uid_words.append(token.upper().zfill(8))

        if len(uid_words) < 3:
            raise RuntimeError(
                f"Could not read full UID from {hex(address)} "
                f"(got {len(uid_words)} words: {uid_words})"
            )

        return "".join(uid_words[:3])

    def flash_hex(
        self, hex_path: Path, erase_all: bool = True, verify: bool = True,
        start_address: int | None = None,
    ) -> str:
        """Flash a firmware file (.hex or .bin). Returns CLI output.

        For .bin files, start_address is required (e.g. 0x08000000).
        For .hex files, the address is embedded in the file.
        """
        if not hex_path.exists():
            raise FileNotFoundError(f"Firmware file not found: {hex_path}")

        # .bin files require an explicit start address
        if hex_path.suffix.lower() == ".bin" and start_address is None:
            start_address = 0x08000000  # Default STM32 flash base

        args = ["-c", "port=swd", "mode=UR"]
        if erase_all:
            args.extend(["-e", "all"])
        if start_address is not None:
            args.extend(["-d", str(hex_path), hex(start_address)])
        else:
            args.extend(["-d", str(hex_path)])
        if verify:
            args.append("-v")

        return self._run_cli(args)

    def reset_device(self) -> str:
        """Issue a hardware reset via SWD."""
        return self._run_cli(["-c", "port=swd", "mode=UR", "-hardRst"])


class STM32WBFlasher(STM32Flasher):
    """Valve flasher with FUS + BLE stack + app 3-step procedure."""

    def __init__(
        self,
        cli_path: Path,
        app_hex: Path,
        ble_stack_bin: Path | None = None,
        fus_bin: Path | None = None,
        fus_address: int = 0x080EC000,
        ble_stack_address: int = 0x080C7000,
        fus_min_version: str = "1.2.0",
        parent=None,
    ):
        super().__init__(cli_path, parent)
        self.app_hex = app_hex
        self.ble_stack_bin = ble_stack_bin
        self.fus_bin = fus_bin
        self.fus_address = fus_address
        self.ble_stack_address = ble_stack_address
        self.fus_min_version = fus_min_version

    def execute(self) -> dict[str, Any]:
        result: dict[str, Any] = {}

        # Step 1: Verify MCU
        self.set_step("check_mcu_id", "running", "Reading MCU ID...")
        dev_id = self.read_mcu_id(0xE0042000)
        if dev_id != 0x495:
            self.set_step("check_mcu_id", "fail", f"Expected 0x495, got {hex(dev_id)}")
            raise RuntimeError(
                f"Wrong MCU! Expected STM32WB (0x495), got {hex(dev_id)}. "
                "Check that you are using the Valve tab for a Valve device."
            )
        self.set_step("check_mcu_id", "pass", f"DEV_ID: {hex(dev_id)}")
        self.progress.emit(10)

        # Step 2: Check/upgrade FUS
        self.set_step("fus_check", "running", "Checking FUS version...")
        fus_status = self._check_fus()

        if fus_status == "stack_running":
            # Wireless stack already installed and running — skip FUS + BLE stack
            self.log("Wireless stack already running — skipping FUS and BLE stack steps")
            self.set_step("fus_check", "pass", "Stack already running")
            self.progress.emit(30)
            self.set_step("ble_stack_install", "pass", "Already installed (skipped)")
            self.progress.emit(60)
        else:
            if fus_status == "needs_upgrade":
                if self.fus_bin and self.fus_bin.exists():
                    self.log("FUS upgrade needed, installing...")
                    self._run_cli([
                        "-c", "port=swd", "mode=UR",
                        "-fwupgrade", str(self.fus_bin), hex(self.fus_address),
                        "firstinstall=0",
                    ], timeout=300)
                    self.set_step("fus_check", "pass", "FUS upgraded")
                else:
                    self.log("FUS upgrade needed but no FUS binary provided", "warn")
                    self.set_step("fus_check", "pass", "FUS binary not provided (skipped)")
            else:
                # fus_status == "ok"
                self.set_step("fus_check", "pass", "FUS version OK")
            self.progress.emit(30)

            # Step 3: Install BLE stack
            self.set_step("ble_stack_install", "running", "Installing BLE wireless stack...")
            if self.ble_stack_bin and self.ble_stack_bin.exists():
                # Start FUS first
                try:
                    self._run_cli(["-c", "port=swd", "-startfus"])
                except RuntimeError:
                    pass  # May fail if FUS already running

                self._run_cli([
                    "-c", "port=swd", "mode=UR",
                    "-fwupgrade", str(self.ble_stack_bin), hex(self.ble_stack_address),
                    "firstinstall=0",
                ], timeout=300)

                # Start wireless stack — required for app to use BLE
                self.log("Starting wireless stack...")
                try:
                    self._run_cli(["-c", "port=swd", "-startwirelessstack"])
                except RuntimeError:
                    pass  # May fail if stack auto-started
            self.set_step("ble_stack_install", "pass")
            self.progress.emit(60)

        # Step 4: Flash application
        self.set_step("flash_app", "running", "Flashing application...")
        self.flash_hex(self.app_hex)
        self.set_step("flash_app", "pass")
        self.progress.emit(80)

        # Step 5: Read UID
        self.set_step("read_uid", "running", "Reading UID...")
        uid = self.read_uid(0x1FFF7590)
        result["uid"] = uid
        self.set_step("read_uid", "pass", f"UID: {uid}")
        self.progress.emit(90)

        # Step 6: Reset
        self.set_step("reset_boot", "running", "Resetting device...")
        self.reset_device()
        self.set_step("reset_boot", "pass")
        self.progress.emit(100)

        return result

    def _check_fus(self) -> str:
        """Check FUS state and version.

        Returns:
            "ok" — FUS version meets minimum, proceed normally
            "needs_upgrade" — FUS version too old or unreadable, upgrade needed
            "stack_running" — wireless stack already running, skip FUS + BLE stack
        """
        try:
            output = self._run_cli([
                "-c", "port=swd", "mode=UR", "-fusgetstate",
            ])
        except RuntimeError as e:
            error_text = str(e)
            # "FUS_STATE_NOT_RUNNING" with "wireless stack is running" means
            # BLE stack is already installed and active — safe to skip
            if "FUS_STATE_NOT_RUNNING" in error_text or "wireless stack is running" in error_text.lower():
                self.log("FUS not running — wireless stack already installed", "info")
                return "stack_running"
            self.log(f"FUS state check failed: {error_text}", "warn")
            return "needs_upgrade"

        # Check for stack-running indication in successful output too
        if re.search(r"FUS_STATE_NOT_RUNNING|wireless stack is running", output, re.IGNORECASE):
            self.log("FUS not running — wireless stack already installed", "info")
            return "stack_running"

        # Parse FUS version from output
        match = re.search(r"FUS\s+version\s*:\s*(\d+\.\d+\.\d+)", output)
        if match:
            current = match.group(1)
            self.log(f"FUS version: {current}")
            if self._version_gte(current, self.fus_min_version):
                return "ok"
            else:
                self.log(f"FUS {current} < {self.fus_min_version}, upgrade needed", "warn")
                return "needs_upgrade"

        self.log("Could not parse FUS version", "warn")
        return "needs_upgrade"

    @staticmethod
    def _version_gte(current: str, minimum: str) -> bool:
        """Compare version strings (major.minor.patch)."""
        cur = tuple(int(x) for x in current.split("."))
        min_ = tuple(int(x) for x in minimum.split("."))
        return cur >= min_


class STM32WBAFlasher(STM32Flasher):
    """Leak Sensor flasher — single-step app flash."""

    def __init__(
        self,
        cli_path: Path,
        app_hex: Path,
        parent=None,
    ):
        super().__init__(cli_path, parent)
        self.app_hex = app_hex

    def execute(self) -> dict[str, Any]:
        result: dict[str, Any] = {}

        # Step 1: Verify MCU
        self.set_step("check_mcu_id", "running", "Reading MCU ID...")
        dev_id = self.read_mcu_id(0xE0044000)
        if dev_id != 0x492:
            self.set_step("check_mcu_id", "fail", f"Expected 0x492, got {hex(dev_id)}")
            raise RuntimeError(
                f"Wrong MCU! Expected STM32WBA (0x492), got {hex(dev_id)}. "
                "Check that you are using the Leak Sensor tab for a Leak Sensor device."
            )
        self.set_step("check_mcu_id", "pass", f"DEV_ID: {hex(dev_id)}")
        self.progress.emit(20)

        # Step 2: Flash application
        self.set_step("flash_app", "running", "Flashing application...")
        self.flash_hex(self.app_hex)
        self.set_step("flash_app", "pass")
        self.progress.emit(60)

        # Step 3: Read UID
        self.set_step("read_uid", "running", "Reading UID...")
        uid = self.read_uid(0x0BF90700)
        result["uid"] = uid
        self.set_step("read_uid", "pass", f"UID: {uid}")
        self.progress.emit(80)

        # Step 4: Reset
        self.set_step("capture_uart_log", "running", "Resetting device...")
        self.reset_device()
        self.progress.emit(100)

        return result


class STM32AppReFlasher(STM32Flasher):
    """Simple re-flasher: erase app region, flash new binary, reset.

    Used to re-flash production firmware after testing with debug firmware.
    Does not touch FUS or BLE wireless stack.
    """

    def __init__(self, cli_path: Path, app_bin: Path, parent=None):
        super().__init__(cli_path, parent)
        self.app_bin = app_bin

    def execute(self) -> dict[str, Any]:
        self.log("Flashing production firmware...")
        self.progress.emit(10)
        self.flash_hex(self.app_bin)
        self.progress.emit(80)
        self.log("Resetting device...")
        self.reset_device()
        self.progress.emit(100)
        return {}
