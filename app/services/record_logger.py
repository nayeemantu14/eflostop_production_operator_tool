"""Production record logger — JSONL file + SQLite database."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RecordLogger:
    """Logs per-unit production records to both JSONL and SQLite."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = data_dir / "production_records.jsonl"
        self.db_path = data_dir / "production.db"
        self._conn = sqlite3.connect(str(self.db_path))
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                device_type TEXT NOT NULL,
                serial_number TEXT NOT NULL,
                uid TEXT,
                ble_mac TEXT,
                wifi_mac TEXT,
                fw_version TEXT,
                hw_revision TEXT,
                sku TEXT,
                operator TEXT,
                work_order TEXT,
                result TEXT NOT NULL,
                steps_json TEXT,
                qr_payload TEXT,
                notes TEXT
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_records_serial
            ON records(serial_number)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_records_device_type
            ON records(device_type)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_records_timestamp
            ON records(timestamp)
        """)
        self._conn.commit()

    def log(self, record: dict[str, Any]) -> int:
        """Log a production record. Returns the SQLite row ID."""
        timestamp = record.get("timestamp") or datetime.now(timezone.utc).isoformat()
        record["timestamp"] = timestamp

        # Append to JSONL
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

        # Insert into SQLite
        steps_json = json.dumps(record.get("steps", []), default=str)
        cursor = self._conn.execute(
            """INSERT INTO records
               (timestamp, device_type, serial_number, uid, ble_mac, wifi_mac,
                fw_version, hw_revision, sku, operator, work_order,
                result, steps_json, qr_payload, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                timestamp,
                record.get("device_type", ""),
                record.get("serial_number", ""),
                record.get("uid", ""),
                record.get("ble_mac", ""),
                record.get("wifi_mac", ""),
                record.get("fw_version", ""),
                record.get("hw_revision", ""),
                record.get("sku", ""),
                record.get("operator", ""),
                record.get("work_order", ""),
                record.get("result", "UNKNOWN"),
                steps_json,
                record.get("qr_payload", ""),
                record.get("notes", ""),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def query(
        self,
        device_type: str | None = None,
        result: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query production records with optional filters."""
        where_clauses = []
        params: list[Any] = []

        if device_type:
            where_clauses.append("device_type = ?")
            params.append(device_type)
        if result:
            where_clauses.append("result = ?")
            params.append(result)

        where_sql = " AND ".join(where_clauses)
        if where_sql:
            where_sql = "WHERE " + where_sql

        query = f"""
            SELECT * FROM records {where_sql}
            ORDER BY id DESC LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor = self._conn.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def count(self, device_type: str | None = None, result: str | None = None) -> int:
        """Count records matching filters."""
        where_clauses = []
        params: list[Any] = []
        if device_type:
            where_clauses.append("device_type = ?")
            params.append(device_type)
        if result:
            where_clauses.append("result = ?")
            params.append(result)

        where_sql = " AND ".join(where_clauses)
        if where_sql:
            where_sql = "WHERE " + where_sql

        cursor = self._conn.execute(f"SELECT COUNT(*) FROM records {where_sql}", params)
        return cursor.fetchone()[0]

    def export_csv(self, output_path: Path, device_type: str | None = None) -> int:
        """Export records to CSV. Returns number of rows exported."""
        import csv

        records = self.query(device_type=device_type, limit=999999)
        if not records:
            return 0

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)

        return len(records)

    def close(self) -> None:
        self._conn.close()
