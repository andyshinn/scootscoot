"""The public entry point.

Home Assistant owns discovery and hands over a resolved BLEDevice; this module
owns the connection. Every operation opens its own connection and closes it, so
the vehicle's single BLE slot is free for the phone app between polls.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from scootscoot.exceptions import ConnectionFailed, HandshakeFailed, PairingTimeout, VehicleBusy
from scootscoot.handshake import Established, Handshake, Send
from scootscoot.models import DeviceInfo, ScooterState
from scootscoot.profiles.types import BoardRole, DeviceProfile
from scootscoot.session import DEFAULT_READ_TIMEOUT, ScooterSession
from scootscoot.transport import BleTransport, select_transport

_LOGGER = logging.getLogger(__name__)

#: Home Assistant requires at least 10s; 20s is comfortable over a proxy.
DEFAULT_CONNECT_TIMEOUT = 20.0
#: Discard notifications cached by the stack from a previous session.
_DRAIN_DELAY = 0.25
#: Backoff before each connect attempt. An echoed PRE_COMM needs a real
#: disconnect to reset the vehicle's BLE stack.
_ATTEMPT_DELAYS = (0.0, 1.0, 2.0)
_GATT_DEVICE_NAME = "00002a00-0000-1000-8000-00805f9b34fb"
_PASSWORD_LEN = 16


@dataclass(frozen=True, slots=True)
class Credentials:
    """Caller-owned secrets. Never read from or written to disk by this library.

    On iOS the password is the NSUserDefaults key ``{SERIAL}_decrypt`` in
    ``Library/Preferences/com.ninebot.segway.plist`` -- 16 raw bytes. It is a
    preferences key, not a file.
    """

    #: repr=False so the password cannot escape through a logged Credentials or
    #: through the locals of a rendered traceback.
    password: bytes | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.password is not None and len(self.password) != _PASSWORD_LEN:
            msg = f"password must be exactly {_PASSWORD_LEN} bytes, got {len(self.password)}"
            raise ValueError(msg)


class Scooter:
    """A Segway-Ninebot vehicle reachable over BLE."""

    def __init__(
        self,
        device: BLEDevice,
        profile: DeviceProfile,
        credentials: Credentials,
        *,
        device_name: str | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
    ) -> None:
        self._device = device
        self._profile = profile
        self._credentials = credentials
        self._device_name = device_name
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout

    @property
    def profile(self) -> DeviceProfile:
        return self._profile

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ScooterSession]:
        """Open one authenticated connection for the duration of the block.

        Never pairs: a vehicle with no password for these credentials raises
        PairingRequired. Call pair() first, deliberately.
        """
        async with self._connection(allow_pairing=False) as (transport, established):
            yield ScooterSession(
                transport,
                established.crypto,
                self._profile,
                sync2=established.sync2,
                serial=established.serial,
                timeout=self._read_timeout,
            )

    async def poll(self) -> ScooterState:
        """Open a connection, read the profile's poll set, close it."""
        async with self.session() as session:
            return await session.poll()

    async def identify(self) -> DeviceInfo:
        """Open a connection, read static identity, close it."""
        async with self.session() as session:
            return await session.identify()

    async def pair(self) -> bytes:
        """Negotiate a new password with an unpaired vehicle and return it.

        This is the only operation that writes to the vehicle, and it is
        deliberately explicit rather than a constructor flag, because the
        password it establishes exists nowhere else:

        * **The vehicle may demand a physical button press** before it accepts
          the new password, and will keep the connection waiting up to 60 s for
          it. Have the vehicle to hand when calling this.
        * **The returned 16 bytes are yours to persist.** This library never
          writes to disk. Store them and pass them back as
          ``Credentials(password=...)`` on every later connection.
        * **Losing them means losing access.** The vehicle then holds a
          password no one can produce, it will silently ignore any attempt to
          set another, and this library can no longer talk to it. Recovery
          means re-pairing with the phone app and extracting *its* password.

        A vehicle that already holds a password -- one paired with the phone
        app, or with a previous call to this method -- raises PairingRequired
        rather than overwriting it.
        """
        async with self._connection(allow_pairing=True) as (_transport, established):
            return established.password

    @asynccontextmanager
    async def _connection(
        self, *, allow_pairing: bool
    ) -> AsyncIterator[tuple[BleTransport, Established]]:
        """Connect and handshake, tearing the connection down on the way out."""
        client, transport, established = await self._open(allow_pairing=allow_pairing)
        try:
            yield transport, established
        finally:
            await self._close(client, transport)

    async def _open(self, *, allow_pairing: bool) -> tuple[BleakClient, BleTransport, Established]:
        """Connect and handshake, retrying only on a busy vehicle."""
        last_busy: VehicleBusy | None = None

        for delay in _ATTEMPT_DELAYS:
            if delay:
                await asyncio.sleep(delay)

            client = await self._establish()
            transport: BleTransport | None = None
            try:
                gatt = select_transport(client, self._profile.transports)
                transport = BleTransport(client, gatt)
                await transport.start()
                await asyncio.sleep(_DRAIN_DELAY)
                transport.drain()
                established = await self._handshake(client, transport, allow_pairing=allow_pairing)
                return client, transport, established
            except VehicleBusy as err:
                # An echoed frame needs a real disconnect to reset the
                # vehicle's BLE stack; reconnecting is the only recovery.
                last_busy = err
                _LOGGER.debug("vehicle busy; disconnecting before retrying")
                await self._close(client, transport)
            except BaseException:
                await self._close(client, transport)
                raise

        msg = (
            "the vehicle would not start a session after three attempts; it "
            "accepts one BLE client at a time, so close the phone app and retry"
        )
        raise VehicleBusy(msg) from last_busy

    async def _establish(self) -> BleakClient:
        try:
            return await establish_connection(
                BleakClientWithServiceCache,
                self._device,
                self._device_name or self._device.name or self._device.address,
                timeout=self._connect_timeout,
            )
        except (BleakError, TimeoutError) as err:
            msg = f"could not connect to {self._device.address}: {err}"
            raise ConnectionFailed(msg) from err

    async def _close(self, client: BleakClient, transport: BleTransport | None) -> None:
        # disconnect() must run even if stop() raises (or is cancelled) -- an
        # abandoned client holds the vehicle's single BLE slot until GC.
        try:
            if transport is not None:
                await transport.stop()
        finally:
            await client.disconnect()

    async def _handshake(
        self, client: BleakClient, transport: BleTransport, *, allow_pairing: bool
    ) -> Established:
        handshake = Handshake(
            device_name=await self._key_material(client),
            suite=self._profile.crypto,
            ble_address=self._profile.board(BoardRole.BLE).address,
            password=self._credentials.password,
            allow_pairing=allow_pairing,
        )

        step = handshake.start()
        while True:
            if isinstance(step, Established):
                if step.paired:
                    _LOGGER.info(
                        "paired with %s; pair() is returning the negotiated password, "
                        "which only the caller can store",
                        step.serial,
                    )
                return step
            if isinstance(step, Send):
                step = handshake.feed(await self._exchange(transport, step))
                continue
            try:
                raw = await transport.recv(step.timeout)
            except TimeoutError as err:
                msg = "the vehicle never confirmed pairing; was its button pressed?"
                raise PairingTimeout(msg) from err
            step = handshake.feed(raw)

    async def _exchange(self, transport: BleTransport, step: Send) -> bytes:
        # Resending an identical frame is safe: its counter was fixed at
        # encryption time, and a vehicle that never received the first copy has
        # an unchanged replay window.
        last: TimeoutError | None = None
        for _ in range(step.attempts):
            transport.drain()
            await transport.send(step.payload)
            try:
                return await transport.recv(step.timeout)
            except TimeoutError as err:
                last = err
        msg = "the vehicle did not answer a handshake frame"
        raise HandshakeFailed(msg) from last

    async def _key_material(self, client: BleakClient) -> str:
        """The BLE name, which is phase-1 key material and must be exact.

        On a GT3 Pro this is the bare serial, with no vendor token.
        """
        if self._device_name:
            return self._device_name
        if self._device.name:
            return self._device.name

        raw = await client.read_gatt_char(_GATT_DEVICE_NAME)
        name = bytes(raw).decode("ascii", errors="ignore").replace("\x00", "").strip()
        if not name:
            msg = (
                "could not determine the BLE device name, which is required as "
                "handshake key material; pass device_name explicitly"
            )
            raise HandshakeFailed(msg)
        return name
