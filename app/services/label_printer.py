"""Zebra label printer driver — USB raw or TCP socket."""

from __future__ import annotations

import socket
from pathlib import Path


class LabelPrinter:
    """Send ZPL commands to a Zebra label printer."""

    def __init__(
        self,
        connection: str = "tcp",
        tcp_host: str = "",
        tcp_port: int = 9100,
    ):
        self.connection = connection
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port

    def print_zpl(self, zpl: str) -> bool:
        """Send ZPL string to the printer.

        Returns True on success, False on failure.
        """
        if self.connection == "tcp":
            return self._send_tcp(zpl)
        return False

    def _send_tcp(self, zpl: str) -> bool:
        if not self.tcp_host:
            return False
        try:
            with socket.create_connection((self.tcp_host, self.tcp_port), timeout=5) as sock:
                sock.sendall(zpl.encode("utf-8"))
            return True
        except (OSError, socket.timeout):
            return False

    def test_connection(self) -> bool:
        """Test if the printer is reachable."""
        if self.connection == "tcp" and self.tcp_host:
            try:
                with socket.create_connection(
                    (self.tcp_host, self.tcp_port), timeout=3
                ):
                    return True
            except (OSError, socket.timeout):
                return False
        return False
