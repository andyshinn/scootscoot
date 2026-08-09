"""Async BLE library for Segway-Ninebot vehicles (Encryption2 / authV2)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from scootscoot.exceptions import (
    AuthenticationFailed,
    ConnectionFailed,
    HandshakeFailed,
    PairingRequired,
    PairingTimeout,
    ProtocolError,
    ScootScootError,
    ServiceNotFound,
    UnknownBoard,
    UnknownRegister,
    VehicleBusy,
)

try:
    __version__ = version("scootscoot")
except PackageNotFoundError:  # pragma: no cover - only when running from a bare tree
    __version__ = "0.0.0.dev0"

__all__ = [
    "AuthenticationFailed",
    "ConnectionFailed",
    "HandshakeFailed",
    "PairingRequired",
    "PairingTimeout",
    "ProtocolError",
    "ScootScootError",
    "ServiceNotFound",
    "UnknownBoard",
    "UnknownRegister",
    "VehicleBusy",
    "__version__",
]
