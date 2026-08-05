# QR Code Payload Specification — eFloStop II

## Format

Compact JSON, base64url-encoded (no padding). ECC level M, 25mm x 25mm label.

## Schema (v1)

```json
{
  "v": 1,
  "t": "hub|valve|sensor",
  "sku": "EFS2-HUB-NA|EFS2-VLV-1IN|EFS2-LKS-BLE",
  "hw_rev": "C",
  "fw": "1.4.2",
  "sn": "2615-000123",
  "uid": "AABBCCDDEEFF00112233",
  "ble": "AA:BB:CC:DD:EE:FF",
  "wifi": "AA:BB:CC:DD:EE:FF",
  "mfg": "2026-04-09T03:12:44Z",
  "op": "OP-0412",
  "wo": "WO-2026-00881"
}
```

## Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `v` | int | Yes | Schema version (currently 1) |
| `t` | string | Yes | Device type: `hub`, `valve`, or `sensor` |
| `sku` | string | Yes | Product SKU |
| `hw_rev` | string | Yes | Hardware revision letter |
| `fw` | string | Yes | Firmware version (semver) |
| `sn` | string | Yes | Serial number (YYWW-NNNNNN) |
| `uid` | string | Yes | MCU unique ID (hex, no separators) |
| `ble` | string | Conditional | BLE MAC address (colon-separated). Required for all devices. |
| `wifi` | string | Conditional | WiFi MAC address. Hub only. |
| `mfg` | string | Yes | Manufacturing timestamp (ISO 8601 UTC) |
| `op` | string | Yes | Operator ID |
| `wo` | string | No | Work order number |

## Serial Number Format

`YYWW-NNNNNN`

- `YY`: 2-digit year (e.g., 26)
- `WW`: ISO week number (01-53)
- `NNNNNN`: 6-digit zero-padded sequence, auto-incremented per device type per week
- Persisted in SQLite to survive app restarts

Examples: `2615-000001`, `2615-000002`, `2650-000001`

## Encoding

1. Build JSON object (compact, no whitespace)
2. UTF-8 encode
3. base64url encode (RFC 4648 §5, no `=` padding)
4. Result is the QR payload string

## Label Layout

```
┌─────────────────────────────────┐
│  ┌─────────┐  SN: 2615-000123  │
│  │         │  BLE: ..DD:EE:FF  │
│  │   QR    │  FW: 1.4.2        │
│  │         │  Date: 2026-04-09  │
│  └─────────┘  eFloStop II Hub  │
└─────────────────────────────────┘
```

QR: left side, 25mm x 25mm.
Human-readable: right side — SN, BLE last 4 octets, FW version, date, device name.

## Decoding (Verification)

```python
import base64, json
payload = "eyJ2IjoxLCJ0IjoiaHViIiwi..."
data = json.loads(base64.urlsafe_b64decode(payload + "=="))
```
