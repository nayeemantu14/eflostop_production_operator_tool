"""Tests for production record logger."""

import pytest

from app.services.record_logger import RecordLogger


@pytest.fixture
def logger(tmp_path):
    rl = RecordLogger(tmp_path / "data")
    yield rl
    rl.close()


def test_log_and_query(logger):
    row_id = logger.log({
        "device_type": "hub",
        "serial_number": "2615-000001",
        "uid": "AABBCCDD",
        "result": "PASS",
    })
    assert row_id >= 1

    records = logger.query()
    assert len(records) == 1
    assert records[0]["serial_number"] == "2615-000001"


def test_filter_by_device(logger):
    logger.log({"device_type": "hub", "serial_number": "H-001", "result": "PASS"})
    logger.log({"device_type": "valve", "serial_number": "V-001", "result": "PASS"})
    logger.log({"device_type": "hub", "serial_number": "H-002", "result": "FAIL"})

    hubs = logger.query(device_type="hub")
    assert len(hubs) == 2

    valves = logger.query(device_type="valve")
    assert len(valves) == 1


def test_filter_by_result(logger):
    logger.log({"device_type": "hub", "serial_number": "H-001", "result": "PASS"})
    logger.log({"device_type": "hub", "serial_number": "H-002", "result": "FAIL"})

    passes = logger.query(result="PASS")
    assert len(passes) == 1

    fails = logger.query(result="FAIL")
    assert len(fails) == 1


def test_count(logger):
    logger.log({"device_type": "hub", "serial_number": "H-001", "result": "PASS"})
    logger.log({"device_type": "hub", "serial_number": "H-002", "result": "PASS"})
    logger.log({"device_type": "valve", "serial_number": "V-001", "result": "FAIL"})

    assert logger.count() == 3
    assert logger.count(device_type="hub") == 2
    assert logger.count(result="FAIL") == 1


def test_jsonl_created(logger):
    logger.log({"device_type": "hub", "serial_number": "H-001", "result": "PASS"})
    assert logger.jsonl_path.exists()
    lines = logger.jsonl_path.read_text().strip().split("\n")
    assert len(lines) == 1


def test_export_csv(logger, tmp_path):
    logger.log({"device_type": "hub", "serial_number": "H-001", "result": "PASS"})
    logger.log({"device_type": "valve", "serial_number": "V-001", "result": "FAIL"})

    csv_path = tmp_path / "export.csv"
    count = logger.export_csv(csv_path)
    assert count == 2
    assert csv_path.exists()
