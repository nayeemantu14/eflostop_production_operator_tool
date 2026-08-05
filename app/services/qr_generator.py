"""QR code generator for eFloStop II production labels."""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from typing import Any

import qrcode
from PIL import Image


# Device-type tag prepended to the QR payload so the scanning app can identify
# the device from the code alone. The delimiter is "-" to match the WiFi Hub's
# existing Gateway ID convention ("GW-<hex>"); see docs/QR_PAYLOAD_SPEC.md.
DEVICE_QR_PREFIX = {
    "hub": "GW-",
    "valve": "VV-",
    "sensor": "LK-",
}


def prefixed_qr_payload(device_type: str, mac_id: str) -> str:
    """Prepend the device-type tag to a QR MAC/identifier payload.

    The mac_id is used verbatim — only the tag is prepended, so existing MAC
    formatting (colons, case) is preserved exactly. Idempotent: if mac_id
    already starts with the tag (the WiFi Hub's Gateway ID is already
    "GW-<hex>"), it is returned unchanged so the tag is never doubled.

    Args:
        device_type: Device type key — "hub", "valve", or "sensor".
        mac_id: The raw payload (BLE MAC for valve/sensor, Gateway ID for hub).

    Returns:
        Tagged payload, e.g. "VV-34:B7:DA:6A:AD:54". Unknown device types fall
        back to the untagged mac_id rather than raising.
    """
    prefix = DEVICE_QR_PREFIX.get(device_type, "")
    if not prefix or mac_id.startswith(prefix):
        return mac_id
    return f"{prefix}{mac_id}"


def build_device_qr(device_id: str, device_type: str, hw: str, fw: str) -> str:
    """Build the structured query-string QR payload scanned by the Watts app.

    Format: ``id=<device_id>&type=<device_type>&hw=<hw>&sw=v<fw>`` — e.g.
    ``id=LK-00:80:E1:2A:3F:59&type=sensor&hw=stm32wba-C&sw=v1.0.1``.

    `device_id` is the tagged id from `prefixed_qr_payload` (GW-/VV-/LK- + MAC,
    colons preserved). Plain text (not a URL) so a phone surfaces the fields and
    the app parses the query string; mirrors the sibling product's eui/type/hw/sw
    layout. `sw` gets a leading "v" when a version is present.
    """
    sw = f"v{fw}" if fw else ""
    return f"id={device_id}&type={device_type}&hw={hw}&sw={sw}"


def build_payload(data: dict[str, Any]) -> str:
    """Build a base64url-encoded JSON payload for QR code.

    Args:
        data: Dictionary with fields per QR_PAYLOAD_SPEC.md

    Returns:
        base64url-encoded string (no padding)
    """
    compact = json.dumps(data, separators=(",", ":"), default=str)
    encoded = base64.urlsafe_b64encode(compact.encode("utf-8"))
    return encoded.rstrip(b"=").decode("ascii")


def decode_payload(payload: str) -> dict[str, Any]:
    """Decode a base64url QR payload back to dict."""
    # Add padding
    padded = payload + "=" * (4 - len(payload) % 4)
    raw = base64.urlsafe_b64decode(padded)
    return json.loads(raw)


def generate_qr_image(
    payload: str,
    box_size: int = 10,
    border: int = 4,  # standard QR quiet zone (>=4 modules) for reliable scans
) -> Image.Image:
    """Generate a QR code PIL Image from a payload string."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").get_image()


def generate_qr_png(payload: str, output_path: Path, box_size: int = 10) -> Path:
    """Generate a QR code and save as PNG."""
    img = generate_qr_image(payload, box_size=box_size)
    img.save(str(output_path), format="PNG")
    return output_path


def generate_qr_bytes(payload: str, box_size: int = 10) -> bytes:
    """Generate a QR code and return PNG bytes."""
    img = generate_qr_image(payload, box_size=box_size)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_zpl_label(
    payload: str,
    serial_number: str,
    ble_mac: str,
    fw_version: str,
    date_str: str,
    device_name: str,
    label_width_dots: int = 406,  # 50mm at 203dpi
    label_height_dots: int = 203,  # 25mm at 203dpi
) -> str:
    """Build ZPL II label command string.

    Layout: QR left, human-readable text right.
    """
    ble_short = ble_mac[-5:] if len(ble_mac) >= 5 else ble_mac

    zpl = f"""^XA
^FO20,20^BQN,2,5^FDMA,{payload}^FS
^FO220,20^A0N,24,24^FDSN: {serial_number}^FS
^FO220,50^A0N,24,24^FDBLE: ...{ble_short}^FS
^FO220,80^A0N,24,24^FDFW: {fw_version}^FS
^FO220,110^A0N,24,24^FD{date_str}^FS
^FO220,145^A0N,28,28^FD{device_name}^FS
^XZ"""
    return zpl
