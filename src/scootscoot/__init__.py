"""Async BLE library for Segway-Ninebot vehicles (Encryption2 / authV2)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from scootscoot.client import Credentials, Scooter
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
from scootscoot.models import (
    BatteryState,
    DeviceInfo,
    MotorState,
    ScooterState,
    VehicleState,
)
from scootscoot.profiles.types import BoardRole, DeviceProfile, Register, ValueKind
from scootscoot.session import ScooterSession

try:
    __version__ = version("scootscoot")
except PackageNotFoundError:  # pragma: no cover - only when running from a bare tree
    __version__ = "0.0.0.dev0"

__all__ = [
    "AuthenticationFailed",
    "BatteryState",
    "BoardRole",
    "ConnectionFailed",
    "Credentials",
    "DeviceInfo",
    "DeviceProfile",
    "HandshakeFailed",
    "MotorState",
    "PairingRequired",
    "PairingTimeout",
    "ProtocolError",
    "Register",
    "ScootScootError",
    "Scooter",
    "ScooterSession",
    "ScooterState",
    "ServiceNotFound",
    "UnknownBoard",
    "UnknownRegister",
    "ValueKind",
    "VehicleBusy",
    "VehicleState",
    "__version__",
]
