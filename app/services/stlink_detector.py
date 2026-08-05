"""ST-Link probe detection via STM32_Programmer_CLI."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StLinkProbe:
    index: int
    serial: str
    description: str


def find_stlink_probes(cli_path: Path) -> list[StLinkProbe]:
    """Enumerate connected ST-Link probes.

    Uses: STM32_Programmer_CLI -c port=swd --list
    """
    if not cli_path.exists():
        return []

    try:
        result = subprocess.run(
            [str(cli_path), "-c", "port=swd", "--list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout + result.stderr
    except (subprocess.TimeoutExpired, OSError):
        return []

    probes: list[StLinkProbe] = []
    # Parse output like:
    #   ST-LINK SN  : 0671FF535155878281153728
    #   ST-LINK FW  : V2J37M27
    current_serial = ""
    current_desc = ""
    idx = 0

    for line in output.splitlines():
        sn_match = re.search(r"ST-LINK SN\s*:\s*(\S+)", line)
        fw_match = re.search(r"ST-LINK FW\s*:\s*(.+)", line)

        if sn_match:
            current_serial = sn_match.group(1)
        if fw_match:
            current_desc = fw_match.group(1).strip()
            if current_serial:
                probes.append(StLinkProbe(
                    index=idx,
                    serial=current_serial,
                    description=current_desc,
                ))
                idx += 1
                current_serial = ""
                current_desc = ""

    return probes
