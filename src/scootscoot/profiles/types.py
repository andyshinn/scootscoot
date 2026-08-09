"""Declarative device description. Frozen dataclasses, not data files.

Everything model-specific lives here and in the profile modules. The protocol,
transport, and session layers never name a vehicle.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property

from scootscoot.crypto import FW_DATA, ZERO16
from scootscoot.exceptions import ServiceNotFound, UnknownBoard, UnknownRegister
from scootscoot.framing import SYNC2_GEN2, SYNC2_GEN3


class BoardRole(StrEnum):
    """Logical function of a board. Addresses vary by model; roles do not."""

    VCU = "vcu"
    MCU = "mcu"
    BMS1 = "bms1"
    BMS2 = "bms2"
    BLE = "ble"
    DIS = "dis"
    ECU = "ecu"


class ValueKind(StrEnum):
    """How a register's raw bytes should be interpreted."""

    U16 = "u16"
    I16 = "i16"
    U32 = "u32"
    I32 = "i32"
    ASCII = "ascii"
    RAW = "raw"
    VERSION = "version"
    DATE = "date"
    U16_ARRAY = "u16_array"


@dataclass(frozen=True, slots=True)
class Board:
    """One addressable module inside a vehicle."""

    role: BoardRole
    address: int
    #: Whether this board answers with the vehicle switched off. On a parked
    #: vehicle only the BLE radio and the BMS respond; VCU and MCU sleep.
    awake_when_parked: bool


@dataclass(frozen=True, slots=True)
class Register:
    """One readable register on one board."""

    name: str
    board: BoardRole
    index: int
    kind: ValueKind
    #: Bytes requested on the wire. Explicit rather than derived, because the
    #: vendor command tables specify it and are occasionally wrong.
    length: int
    scale: float = 1.0
    unit: str | None = None
    #: Element count for U16_ARRAY.
    count: int = 1


@dataclass(frozen=True, slots=True)
class CryptoSuite:
    """Framing and key-seeding parameters for one protocol generation."""

    label: str
    sync2: int
    ecb_input: bytes
    initial_key2: bytes | None


ENC2_GEN2 = CryptoSuite(
    label="enc2-gen2",
    sync2=SYNC2_GEN2,
    ecb_input=FW_DATA,
    initial_key2=FW_DATA,
)

ENC2_GEN3 = CryptoSuite(
    label="enc2-gen3",
    sync2=SYNC2_GEN3,
    ecb_input=ZERO16,
    initial_key2=None,
)


@dataclass(frozen=True, slots=True)
class GattProfile:
    """A candidate GATT service and its write/notify characteristic pair."""

    label: str
    service: str
    write: str
    notify: str


NORDIC_UART = GattProfile(
    label="Nordic UART",
    service="6e400001-b5a3-f393-e0a9-e50e24dcca9e",
    write="6e400002-b5a3-f393-e0a9-e50e24dcca9e",
    notify="6e400003-b5a3-f393-e0a9-e50e24dcca9e",
)

NINEBOT_CUSTOM = GattProfile(
    label="Ninebot Custom",
    service="6e400001-0000-0000-006e-696e65626f74",
    write="6e400002-0000-0000-006e-696e65626f74",
    # 0004, not 0003 -- 0003 is the secondary RCTP write channel.
    notify="6e400004-0000-0000-006e-696e65626f74",
)


# No slots=True here, alone among the dataclasses in this module: the
# cached_property lookups below need a per-instance __dict__ to memoise into,
# and slots removes it. Adding it for consistency would break every profile at
# first use, not at import.
@dataclass(frozen=True)
class DeviceProfile:
    """Everything model-specific about one vehicle family."""

    key: str
    name: str
    hardware_id: int | None
    server_id: int | None
    crypto: CryptoSuite
    #: GATT candidates in preference order.
    transports: tuple[GattProfile, ...]
    boards: tuple[Board, ...]
    registers: tuple[Register, ...]
    #: Register names read by poll(), in declaration order.
    poll: tuple[str, ...]
    #: Register names read by identify(). Static data, not polled.
    identity: tuple[str, ...]

    @cached_property
    def _boards_by_role(self) -> dict[BoardRole, Board]:
        return {board.role: board for board in self.boards}

    @cached_property
    def _registers_by_name(self) -> dict[str, Register]:
        return {register.name: register for register in self.registers}

    def board(self, role: BoardRole) -> Board:
        try:
            return self._boards_by_role[role]
        except KeyError:
            msg = f"{self.key} declares no {role} board"
            raise UnknownBoard(msg) from None

    def register(self, name: str) -> Register:
        try:
            return self._registers_by_name[name]
        except KeyError:
            msg = f"{self.key} declares no register named {name!r}"
            raise UnknownRegister(msg) from None

    def has_register(self, name: str) -> bool:
        return name in self._registers_by_name

    def registers_for(self, role: BoardRole) -> tuple[Register, ...]:
        return tuple(register for register in self.registers if register.board is role)


def choose_gatt_profile(
    available: Collection[str],
    candidates: Sequence[GattProfile],
) -> GattProfile:
    """Pick the first candidate whose write *and* notify characteristics exist.

    Selecting on the service alone is a trap: a GT3 Pro exposes both Nordic UART
    and Ninebot Custom, the Ninebot service has more characteristics, and it is
    the dead one -- it accepts writes and never answers.
    """
    present = {uuid.lower() for uuid in available}
    for candidate in candidates:
        if candidate.write.lower() in present and candidate.notify.lower() in present:
            return candidate
    msg = (
        f"no candidate service had both a write and a notify characteristic; saw {sorted(present)}"
    )
    raise ServiceNotFound(msg)
