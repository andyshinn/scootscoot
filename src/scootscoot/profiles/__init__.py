"""Device profiles. Adding a model means adding a module here, nothing else."""

from __future__ import annotations

from scootscoot.profiles.gt3_pro import GT3_PRO
from scootscoot.profiles.registry import ALL, get
from scootscoot.profiles.types import (
    ENC2_GEN2,
    ENC2_GEN3,
    NINEBOT_CUSTOM,
    NORDIC_UART,
    Board,
    BoardRole,
    CryptoSuite,
    DeviceProfile,
    GattProfile,
    Register,
    ValueKind,
    choose_gatt_profile,
)

__all__ = [
    "ALL",
    "ENC2_GEN2",
    "ENC2_GEN3",
    "GT3_PRO",
    "NINEBOT_CUSTOM",
    "NORDIC_UART",
    "Board",
    "BoardRole",
    "CryptoSuite",
    "DeviceProfile",
    "GattProfile",
    "Register",
    "ValueKind",
    "choose_gatt_profile",
    "get",
]
