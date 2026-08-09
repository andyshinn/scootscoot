from __future__ import annotations

import inspect
import pathlib
import re

import pytest

import scootscoot
from scootscoot import Credentials, Scooter

VALID = bytes(range(16))


def test_credentials_accept_sixteen_bytes() -> None:
    assert Credentials(password=VALID).password == VALID


def test_credentials_allow_no_password_for_pairing() -> None:
    assert Credentials().password is None


@pytest.mark.parametrize("bad", [b"", bytes(15), bytes(17)])
def test_credentials_reject_a_wrong_length_password(bad: bytes) -> None:
    with pytest.raises(ValueError, match="16 bytes"):
        Credentials(password=bad)


def test_scooter_defaults_meet_the_home_assistant_floor() -> None:
    signature = inspect.signature(Scooter.__init__)
    assert signature.parameters["connect_timeout"].default >= 10.0
    assert signature.parameters["allow_pairing"].default is False


def test_scooter_exposes_the_documented_operations() -> None:
    for name in ("session", "poll", "identify"):
        assert callable(getattr(Scooter, name))


def test_package_exports_the_public_surface() -> None:
    expected = {
        "BatteryState",
        "BoardRole",
        "Credentials",
        "DeviceInfo",
        "DeviceProfile",
        "MotorState",
        "Scooter",
        "ScooterSession",
        "ScooterState",
        "VehicleState",
    }
    assert expected <= set(scootscoot.__all__)
    for name in scootscoot.__all__:
        assert hasattr(scootscoot, name), name


def test_library_constructs_no_scanner() -> None:
    # Home Assistant owns discovery. Constructing a scanner here would fight it.
    for path in _sources():
        assert "BleakScanner" not in path.read_text(), path


def test_library_does_no_console_io_or_file_io() -> None:
    # Word boundaries matter: a method named _open must not trip the open( rule.
    banned = (r"\bprint\(", r"\bsys\.exit\b", r"\bargparse\b", r"\bopen\(")
    for path in _sources():
        source = path.read_text()
        for pattern in banned:
            assert re.search(pattern, source) is None, f"{path} matches {pattern}"


def _sources() -> list[pathlib.Path]:
    root = pathlib.Path(__file__).resolve().parent.parent / "src" / "scootscoot"
    paths = sorted(root.rglob("*.py"))
    assert paths, f"no sources found under {root}"
    return paths
