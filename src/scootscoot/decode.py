"""Turn a register's raw bytes into a typed value.

All multi-byte integers on this protocol are little-endian. Scales come from the
profile, not from here -- getting range and odometer scales confused is a real
bug that shipped in an earlier client.
"""

from __future__ import annotations

from datetime import date

from scootscoot.profiles.types import Register, ValueKind

DecodedValue = int | float | str | date | bytes | tuple[int | float, ...]

_SIGNED_KINDS = frozenset({ValueKind.I16, ValueKind.I32})
#: Round after scaling so 7452 * 0.01 reads 74.52 rather than 74.52000000000001.
_SCALE_PRECISION = 6


def decode(register: Register, raw: bytes) -> DecodedValue | None:
    """Decode `raw` per `register`, or None if it is unusable.

    Returns None when the response is shorter than the register's declared
    length (a truncated or absent read) or when a packed date is not a real
    calendar date.
    """
    if len(raw) < register.length:
        return None

    kind = register.kind
    payload = raw[: register.length]

    if kind is ValueKind.RAW:
        return payload

    if kind is ValueKind.ASCII:
        return payload.decode("ascii", errors="replace").replace("\x00", "").strip()

    if kind is ValueKind.U16_ARRAY:
        return tuple(
            _scaled(int.from_bytes(payload[i * 2 : i * 2 + 2], "little"), register.scale)
            for i in range(register.count)
        )

    value = int.from_bytes(payload, "little", signed=kind in _SIGNED_KINDS)

    if kind is ValueKind.VERSION:
        return f"{(value >> 8) & 0xFF}.{(value >> 4) & 0x0F}.{value & 0x0F}"

    if kind is ValueKind.DATE:
        return _decode_date(value)

    return _scaled(value, register.scale)


def _scaled(value: int, scale: float) -> int | float:
    if scale == 1.0:
        return value
    return round(value * scale, _SCALE_PRECISION)


def _decode_date(value: int) -> date | None:
    """Unpack (year - 2000) << 9 | month << 5 | day."""
    try:
        return date(2000 + (value >> 9), (value >> 5) & 0x0F, value & 0x1F)
    except ValueError:
        return None
