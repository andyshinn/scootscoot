"""An authenticated connection. Walks a read plan and does the I/O.

Deliberately thin: ordering lives in models.plan_poll and result assembly in
models.build_state, both pure and unit-tested.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

from scootscoot.channel import FrameChannel
from scootscoot.crypto import CryptoStatus, NbCrypto
from scootscoot.decode import DecodedValue, decode
from scootscoot.framing import CMD_READ_RESP, build_read, parse_frame
from scootscoot.models import (
    DeviceInfo,
    ScooterState,
    build_info,
    build_state,
    plan_poll,
)
from scootscoot.profiles.types import BoardRole, DeviceProfile, Register

_LOGGER = logging.getLogger(__name__)

DEFAULT_READ_TIMEOUT = 2.0
DEFAULT_PROBE_TIMEOUT = 0.5
#: Part number / serial. Present on most boards, so it makes a decent probe.
DEFAULT_PROBE_INDEX = 0x10


class ScooterSession:
    """Reads registers over an authenticated channel.

    Created by Scooter.session(); not constructed directly. The session ends
    when its connection does -- the crypto context cannot outlive it, because
    the vehicle regenerates its auth parameter on every PRE_COMM.
    """

    def __init__(
        self,
        channel: FrameChannel,
        crypto: NbCrypto,
        profile: DeviceProfile,
        *,
        sync2: int,
        serial: str,
        timeout: float = DEFAULT_READ_TIMEOUT,
    ) -> None:
        self._channel = channel
        self._crypto = crypto
        self._profile = profile
        self._sync2 = sync2
        self._serial = serial
        self._timeout = timeout

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def profile(self) -> DeviceProfile:
        return self._profile

    async def read_raw(
        self,
        board: int,
        index: int,
        length: int = 2,
        *,
        timeout: float | None = None,
    ) -> bytes | None:
        """Read one register by raw address.

        None on timeout, and on any reply that is not a full read response for
        this board and index.
        """
        self._channel.drain()
        request = build_read(board, index, length, sync2=self._sync2)
        await self._channel.send(self._crypto.encrypt(request))

        try:
            raw = await self._channel.recv(timeout if timeout is not None else self._timeout)
        except TimeoutError:
            _LOGGER.debug("read 0x%02X:0x%02X timed out", board, index)
            return None

        try:
            plaintext, status = self._crypto.decrypt(raw)
        except ValueError:
            _LOGGER.debug(
                "read 0x%02X:0x%02X frame too short to decrypt: %s", board, index, raw.hex()
            )
            return None
        if status is not CryptoStatus.OK:
            # Counter or key skew decrypts a well-formed frame into
            # plausible-but-wrong values, so this is not merely "garbage on the
            # air": parsing on would feed silently wrong telemetry to consumers.
            # A missing reading is recoverable; a wrong one is not. The
            # handshake treats the same condition as fatal.
            _LOGGER.debug("read 0x%02X:0x%02X failed verification (%s)", board, index, status.name)
            return None

        frame = parse_frame(plaintext)
        if frame is None:
            _LOGGER.debug("read 0x%02X:0x%02X unparseable: %s", board, index, plaintext.hex())
            return None
        if frame.board_id != board:
            # A slow board's reply landing on the next probe would otherwise
            # invent boards that do not exist.
            _LOGGER.debug(
                "board 0x%02X answered a request aimed at 0x%02X; discarding",
                frame.board_id,
                board,
            )
            return None
        if frame.cmd != CMD_READ_RESP or frame.index != index or len(frame.data) < length:
            # Anything else -- an error or status frame, a stale reply for an
            # earlier register, an empty payload -- is not a reading. Returning
            # it would mark the board as responding (models._responding counts
            # any non-None value), which is how a parked VCU looked powered on.
            _LOGGER.debug(
                "read 0x%02X:0x%02X got cmd 0x%02X index 0x%02X with %d of %d bytes; discarding",
                board,
                index,
                frame.cmd,
                frame.index,
                len(frame.data),
                length,
            )
            return None
        return frame.data

    async def read(self, name: str) -> DecodedValue | None:
        """Read one register by profile name and decode it."""
        register = self._profile.register(name)
        raw = await self._read_register(register)
        return decode(register, raw) if raw is not None else None

    async def poll(self) -> ScooterState:
        """Read the profile's poll set and assemble a state snapshot."""
        values = await self._read_many(plan_poll(self._profile))
        return build_state(self._profile, values, serial=self._serial)

    async def identify(self) -> DeviceInfo:
        """Read static identity. Call once at setup, not every poll."""
        registers = [self._profile.register(name) for name in self._profile.identity]
        values = await self._read_many(registers)
        return build_info(self._profile, values, serial=self._serial)

    async def probe_boards(
        self,
        addresses: Iterable[int] = range(256),
        *,
        index: int = DEFAULT_PROBE_INDEX,
        length: int = 2,
        timeout: float = DEFAULT_PROBE_TIMEOUT,
    ) -> tuple[int, ...]:
        """Return the board addresses that answer. For mapping new models."""
        found = []
        for address in addresses:
            if await self.read_raw(address, index, length, timeout=timeout) is not None:
                _LOGGER.debug("board 0x%02X answered", address)
                found.append(address)
        return tuple(found)

    async def scan_registers(
        self,
        board: int,
        indices: Iterable[int] = range(256),
        *,
        length: int = 2,
        timeout: float = DEFAULT_PROBE_TIMEOUT,
    ) -> dict[int, bytes]:
        """Walk every register index on one board. For mapping new models."""
        found: dict[int, bytes] = {}
        for index in indices:
            raw = await self.read_raw(board, index, length, timeout=timeout)
            if raw is not None:
                found[index] = raw
        return found

    async def _read_register(self, register: Register) -> bytes | None:
        board = self._profile.board(register.board)
        return await self.read_raw(board.address, register.index, register.length)

    async def _read_many(self, registers: Sequence[Register]) -> dict[str, bytes | None]:
        values: dict[str, bytes | None] = {}
        asleep: set[BoardRole] = set()

        for register in registers:
            if register.board in asleep:
                values[register.name] = None
                continue

            raw = await self._read_register(register)
            if raw is None:
                # Awake boards drop the odd reply -- one read in ten on a parked
                # GT3. One retry keeps a single drop from blanking a reading,
                # or from passing for a sleeping board.
                _LOGGER.debug("%s did not answer; retrying once", register.name)
                raw = await self._read_register(register)
            values[register.name] = raw

            if raw is None and not self._profile.board(register.board).awake_when_parked:
                _LOGGER.debug("%s did not answer; skipping its remaining registers", register.board)
                asleep.add(register.board)

        return values
