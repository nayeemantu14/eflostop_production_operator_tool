"""Tests for QR payload encoding/decoding."""

import pytest

from app.services.qr_generator import (
    build_device_qr,
    build_payload,
    decode_payload,
    generate_qr_bytes,
    prefixed_qr_payload,
)


def test_roundtrip():
    data = {
        "v": 1,
        "t": "hub",
        "sku": "EFS2-HUB-NA",
        "hw_rev": "C",
        "fw": "1.4.2",
        "sn": "2615-000123",
        "uid": "AABBCCDDEEFF",
        "ble": "AA:BB:CC:DD:EE:FF",
        "wifi": "11:22:33:44:55:66",
        "mfg": "2026-04-09T03:12:44Z",
        "op": "OP-0412",
        "wo": "WO-2026-00881",
    }
    payload = build_payload(data)
    decoded = decode_payload(payload)

    assert decoded["v"] == 1
    assert decoded["t"] == "hub"
    assert decoded["sn"] == "2615-000123"
    assert decoded["ble"] == "AA:BB:CC:DD:EE:FF"


def test_payload_is_base64url():
    data = {"v": 1, "t": "sensor", "sn": "2615-000001"}
    payload = build_payload(data)
    # base64url uses - and _ instead of + and /
    assert "+" not in payload
    assert "/" not in payload
    assert "=" not in payload  # no padding


def test_generate_qr_bytes():
    data = {"v": 1, "t": "valve", "sn": "2615-000001"}
    payload = build_payload(data)
    png = generate_qr_bytes(payload)
    assert len(png) > 100
    # PNG magic bytes
    assert png[:4] == b"\x89PNG"


def test_qr_prefix_valve():
    assert prefixed_qr_payload("valve", "34:B7:DA:6A:AD:54") == "VV-34:B7:DA:6A:AD:54"


def test_qr_prefix_sensor():
    assert prefixed_qr_payload("sensor", "00:80:E1:2A:48:70") == "LK-00:80:E1:2A:48:70"


def test_qr_prefix_hub_not_doubled():
    # The hub's Gateway ID already starts with "GW-" — the tag must not double.
    assert prefixed_qr_payload("hub", "GW-34B7DA6AAD54") == "GW-34B7DA6AAD54"


def test_qr_prefix_preserves_mac_formatting():
    # Only the prefix is prepended; colons and case are left untouched.
    mac = "AA:BB:CC:DD:EE:FF"
    assert prefixed_qr_payload("valve", mac) == "VV-" + mac


def test_qr_prefix_unknown_type_is_untagged():
    # Unknown device types fall back to the raw payload rather than raising.
    assert prefixed_qr_payload("mystery", "AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"


def test_build_device_qr():
    # id keeps the prefix + colons; query string carries type/hw/sw.
    p = build_device_qr("LK-00:80:E1:2A:3F:59", "sensor", "stm32wba-C", "1.0.1")
    assert p == "id=LK-00:80:E1:2A:3F:59&type=sensor&hw=stm32wba-C&sw=v1.0.1"


def test_build_device_qr_empty_fw():
    # No firmware version -> empty sw (no stray "v").
    p = build_device_qr("VV-AA:BB:CC:DD:EE:FF", "valve", "stm32wb-C", "")
    assert p == "id=VV-AA:BB:CC:DD:EE:FF&type=valve&hw=stm32wb-C&sw="
