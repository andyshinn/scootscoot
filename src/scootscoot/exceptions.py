"""Error hierarchy. Every error scootscoot raises derives from ScootScootError."""

from __future__ import annotations


class ScootScootError(Exception):
    """Base class for every error raised by scootscoot."""


class ConnectionFailed(ScootScootError):
    """establish_connection exhausted its attempts."""


class ServiceNotFound(ScootScootError):
    """No candidate GATT service had both its write and notify characteristics."""


class ProtocolError(ScootScootError):
    """A frame was unparseable, or failed its MAC or checksum."""


class VehicleBusy(ScootScootError):
    """The vehicle echoed our frame, or another client holds its single BLE slot."""


class HandshakeFailed(ScootScootError):
    """The three-phase authentication handshake did not complete."""


class AuthenticationFailed(HandshakeFailed):
    """AUTH was rejected — the password is wrong or stale."""


class PairingRequired(HandshakeFailed):
    """A password is needed and none was supplied, or pairing was not allowed."""


class PairingTimeout(HandshakeFailed):
    """The vehicle asked for physical confirmation that never arrived."""


class UnknownBoard(ScootScootError):
    """The profile does not declare a board for the requested role."""


class UnknownRegister(ScootScootError):
    """The profile does not declare a register with the requested name."""
