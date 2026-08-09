"""GATT plumbing: notification reassembly and MTU-aware fragmented writes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from bleak import BleakClient

from scootscoot.framing import FrameAssembler
from scootscoot.profiles.types import GattProfile, choose_gatt_profile

_LOGGER = logging.getLogger(__name__)

#: BLE 4.0 default. Used when a backend will not report the negotiated MTU.
_DEFAULT_MTU = 23
#: ATT write overhead: the payload limit is MTU - 3.
_ATT_OVERHEAD = 3
_MIN_CHUNK = 20
_FRAGMENT_DELAY = 0.01


def available_characteristics(client: BleakClient) -> frozenset[str]:
    """Every characteristic UUID the connected client can see, lowercased."""
    return frozenset(
        characteristic.uuid.lower()
        for service in client.services
        for characteristic in service.characteristics
    )


def select_transport(client: BleakClient, candidates: Sequence[GattProfile]) -> GattProfile:
    """Pick the GATT profile whose write and notify characteristics both exist."""
    chosen = choose_gatt_profile(available_characteristics(client), candidates)
    _LOGGER.debug("using the %s service", chosen.label)
    return chosen


class BleTransport:
    """A FrameChannel over a connected BleakClient."""

    def __init__(self, client: BleakClient, gatt: GattProfile) -> None:
        self._client = client
        self._gatt = gatt
        self._assembler = FrameAssembler()
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def start(self) -> None:
        await self._client.start_notify(self._gatt.notify, self._on_notify)

    async def stop(self) -> None:
        try:
            await self._client.stop_notify(self._gatt.notify)
        except Exception:
            # Teardown must never mask the error that caused it.
            _LOGGER.debug("stop_notify failed during teardown", exc_info=True)

    def _on_notify(self, _sender: object, data: bytearray) -> None:
        for frame in self._assembler.feed(bytes(data)):
            self._queue.put_nowait(frame)

    async def send(self, data: bytes) -> None:
        chunk_size = max(_MIN_CHUNK, self._mtu() - _ATT_OVERHEAD)
        _LOGGER.debug("TX (%d bytes, chunk %d) %s", len(data), chunk_size, data.hex())
        for offset in range(0, len(data), chunk_size):
            await self._client.write_gatt_char(
                self._gatt.write, data[offset : offset + chunk_size], response=False
            )
            if offset + chunk_size < len(data):
                # The stack silently truncates back-to-back oversized writes.
                await asyncio.sleep(_FRAGMENT_DELAY)

    async def recv(self, timeout: float) -> bytes:
        try:
            frame = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            msg = f"no frame within {timeout}s"
            raise TimeoutError(msg) from None
        _LOGGER.debug("RX (%d bytes) %s", len(frame), frame.hex())
        return frame

    def drain(self) -> None:
        self._assembler.clear()
        while not self._queue.empty():
            self._queue.get_nowait()

    def _mtu(self) -> int:
        try:
            return int(self._client.mtu_size)
        except Exception:
            # Not every backend reports the negotiated MTU.
            return _DEFAULT_MTU
