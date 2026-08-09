from __future__ import annotations

from datetime import date

import pytest

from scootscoot import profiles
from scootscoot.decode import decode
from scootscoot.profiles.types import BoardRole, Register, ValueKind

GT3 = profiles.GT3_PRO


def test_u16_little_endian() -> None:
    assert decode(GT3.register("rBmsSOC"), bytes.fromhex("3600")) == 54


def test_i16_is_signed() -> None:
    # rBMSCur reads -6 raw at rest; regeneration makes it negative in use.
    assert decode(GT3.register("rBMSCur"), bytes.fromhex("faff")) == -0.06


def test_u32_little_endian_with_scale() -> None:
    # 5781 at 0.1 km = 578.1 km odometer (359.2 mi; the app showed 359.0).
    assert decode(GT3.register("rMileage"), bytes.fromhex("95160000")) == 578.1


def test_range_uses_a_hundredth_scale_not_a_tenth() -> None:
    # 7452 at 0.01 km = 74.52 km (46.30 mi; the app showed 46.26). Reading this
    # at the odometer's scale is what produced a bogus "745.2 km range".
    assert decode(GT3.register("rLeftMileage"), bytes.fromhex("1c1d")) == 74.52


def test_voltage_scale() -> None:
    # 0x1D97 = 7575 -> 75.75 V, matching the sum of the twenty cells.
    assert decode(GT3.register("rBMSVolt"), bytes.fromhex("971d")) == 75.75


def test_capacity_scale_is_ten_milliamp_hours() -> None:
    assert decode(GT3.register("rBmsCapFull"), bytes.fromhex("b80b")) == 30.0


def test_temperature_scale() -> None:
    # 0x015A = 346 -> 34.6 degrees.
    assert decode(GT3.register("rBodyTemp"), bytes.fromhex("5a01")) == 34.6


def test_unscaled_registers_stay_integers() -> None:
    value = decode(GT3.register("rBmsCycleCountLT"), bytes.fromhex("0200"))
    assert value == 2
    assert isinstance(value, int)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2201", "1.2.2"),
        ("1102", "2.1.1"),
        ("0701", "1.0.7"),
        ("2800", "0.2.8"),
    ],
)
def test_packed_version(raw: str, expected: str) -> None:
    assert decode(GT3.register("rCtrlV"), bytes.fromhex(raw)) == expected


def test_packed_date_activation() -> None:
    # 13114 -> 2025-09-26, exactly 317 days before the app's "317 days as owner".
    assert decode(GT3.register("rActDate"), bytes.fromhex("3a33")) == date(2025, 9, 26)


def test_packed_date_manufacture() -> None:
    assert decode(GT3.register("rBmsManufactureDateLT"), bytes.fromhex("d832")) == date(2025, 6, 24)


def test_impossible_packed_date_returns_none() -> None:
    assert decode(GT3.register("rActDate"), bytes.fromhex("0000")) is None


def test_ascii_strips_padding() -> None:
    raw = b"03GGG2527C0165"
    assert decode(GT3.register("rSN"), raw) == "03GGG2527C0165"


def test_ascii_strips_trailing_nulls() -> None:
    raw = b"Z03QB4G25FJ4\x00\x00\x00\x00"
    assert decode(GT3.register("rPN"), raw) == "Z03QB4G25FJ4"


def test_ascii_replaces_a_non_ascii_byte_rather_than_raising() -> None:
    # Pinned, not endorsed: a corrupt byte becomes U+FFFD and the read still
    # returns a string. Changing this to strict/ignore should be deliberate.
    register = Register("rText", BoardRole.BLE, 0x10, ValueKind.ASCII, 4)
    assert decode(register, b"AB\xffD") == "AB\ufffdD"


def test_ascii_strips_an_interior_null_and_joins_what_is_left() -> None:
    # Pinned, not endorsed: nulls are removed everywhere, not just at the end,
    # so a null-separated field pair silently concatenates.
    register = Register("rText", BoardRole.BLE, 0x10, ValueKind.ASCII, 4)
    assert decode(register, b"AB\x00D") == "ABD"


def test_u16_array_of_temperatures() -> None:
    raw = bytes.fromhex("22002200230023002200220023002200")
    assert decode(GT3.register("rBmsTemps"), raw) == (34, 34, 35, 35, 34, 34, 35, 34)


def test_u16_array_of_cell_voltages_sums_to_the_pack() -> None:
    # Twenty cells around 3.788 V summing to ~75.76 V against rBMSVolt's 75.75.
    cells = [3788] * 20
    raw = b"".join(cell.to_bytes(2, "little") for cell in cells)
    decoded = decode(GT3.register("rBmsCellVolFrequence"), raw)
    assert isinstance(decoded, tuple)
    assert len(decoded) == 20
    assert decoded[0] == 3.788
    assert round(sum(decoded), 2) == 75.76


def test_raw_kind_returns_bytes() -> None:
    register = Register("rBlob", BoardRole.BLE, 0x4D, ValueKind.RAW, 4)
    assert decode(register, bytes.fromhex("deadbeefcafe")) == bytes.fromhex("deadbeef")


def test_short_read_returns_none() -> None:
    assert decode(GT3.register("rMileage"), bytes.fromhex("9516")) is None


def test_empty_read_returns_none() -> None:
    assert decode(GT3.register("rBmsSOC"), b"") is None


def test_extra_bytes_are_ignored() -> None:
    assert decode(GT3.register("rBmsSOC"), bytes.fromhex("3600ffff")) == 54
