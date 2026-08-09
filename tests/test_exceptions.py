from __future__ import annotations

import pytest

import scootscoot
from scootscoot import exceptions as exc


def test_version_is_a_non_empty_string() -> None:
    assert isinstance(scootscoot.__version__, str)
    assert scootscoot.__version__


@pytest.mark.parametrize(
    "error",
    [
        exc.ConnectionFailed,
        exc.ServiceNotFound,
        exc.HandshakeFailed,
        exc.AuthenticationFailed,
        exc.PairingRequired,
        exc.PairingTimeout,
        exc.ProtocolError,
        exc.VehicleBusy,
        exc.UnknownBoard,
        exc.UnknownRegister,
    ],
)
def test_every_error_derives_from_the_base(error: type[Exception]) -> None:
    assert issubclass(error, exc.ScootScootError)


def test_handshake_failures_are_catchable_as_one_group() -> None:
    for error in (exc.AuthenticationFailed, exc.PairingRequired, exc.PairingTimeout):
        assert issubclass(error, exc.HandshakeFailed)


def test_vehicle_busy_is_not_a_handshake_failure() -> None:
    # Echo and phone-app contention are retryable connection conditions,
    # not a rejection of our credentials.
    assert not issubclass(exc.VehicleBusy, exc.HandshakeFailed)
