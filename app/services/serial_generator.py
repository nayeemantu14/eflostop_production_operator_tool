"""Serial number generator: YYWW-NNNNNN format, persisted in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class SerialGenerator:
    """Generates auto-incrementing serial numbers per device type per week."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS serial_counters (
                device_type TEXT NOT NULL,
                year_week TEXT NOT NULL,
                counter INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (device_type, year_week)
            )
        """)
        self._conn.commit()

    def _current_year_week(self) -> str:
        now = datetime.now(timezone.utc)
        iso = now.isocalendar()
        return f"{iso.year % 100:02d}{iso.week:02d}"

    def next(self, device_type: str) -> str:
        """Get the next serial number for a device type.

        Returns format: YYWW-NNNNNN (e.g., 2615-000001)
        """
        yw = self._current_year_week()

        cursor = self._conn.execute(
            "SELECT counter FROM serial_counters WHERE device_type = ? AND year_week = ?",
            (device_type, yw),
        )
        row = cursor.fetchone()

        if row is None:
            new_counter = 1
            self._conn.execute(
                "INSERT INTO serial_counters (device_type, year_week, counter) VALUES (?, ?, ?)",
                (device_type, yw, new_counter),
            )
        else:
            new_counter = row[0] + 1
            self._conn.execute(
                "UPDATE serial_counters SET counter = ? WHERE device_type = ? AND year_week = ?",
                (new_counter, device_type, yw),
            )

        self._conn.commit()
        return f"{yw}-{new_counter:06d}"

    def peek(self, device_type: str) -> str:
        """Preview the next serial number without incrementing."""
        yw = self._current_year_week()
        cursor = self._conn.execute(
            "SELECT counter FROM serial_counters WHERE device_type = ? AND year_week = ?",
            (device_type, yw),
        )
        row = cursor.fetchone()
        next_val = (row[0] + 1) if row else 1
        return f"{yw}-{next_val:06d}"

    def close(self) -> None:
        self._conn.close()
