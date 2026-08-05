"""Tests for serial number generator."""

import tempfile
from pathlib import Path

import pytest

from app.services.serial_generator import SerialGenerator


@pytest.fixture
def gen(tmp_path):
    g = SerialGenerator(tmp_path / "test_serials.db")
    yield g
    g.close()


def test_first_serial(gen):
    sn = gen.next("hub")
    assert sn.endswith("-000001")
    assert len(sn) == 11  # YYWW-NNNNNN


def test_increments(gen):
    sn1 = gen.next("hub")
    sn2 = gen.next("hub")
    assert sn1.endswith("-000001")
    assert sn2.endswith("-000002")


def test_device_types_independent(gen):
    gen.next("hub")
    gen.next("hub")
    sn_valve = gen.next("valve")
    assert sn_valve.endswith("-000001")


def test_peek_does_not_increment(gen):
    peeked = gen.peek("hub")
    actual = gen.next("hub")
    assert peeked == actual


def test_persistence(tmp_path):
    db_path = tmp_path / "serials.db"
    g1 = SerialGenerator(db_path)
    g1.next("hub")
    g1.next("hub")
    g1.close()

    g2 = SerialGenerator(db_path)
    sn = g2.next("hub")
    assert sn.endswith("-000003")
    g2.close()
