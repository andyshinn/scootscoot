"""The three-phase Encryption2 handshake, as a pure state machine.

    PRE_COMM  -> auth parameter + serial number
    SET_PWD   -> establish a session password (may need a button press)
    AUTH      -> prove the password, then normal encrypted communication

feed() takes encrypted bytes and decrypts internally, so the driver only moves
bytes between this object and the transport. No I/O happens here.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from scootscoot.crypto import CryptoStatus, NbCrypto, generate_password
from scootscoot.exceptions import (
    AuthenticationFailed,
    HandshakeFailed,
    PairingRequired,
    PairingTimeout,
    ProtocolError,
    VehicleBusy,
)
from scootscoot.framing import (
    CMD_AUTH,
    CMD_PRE_COMM,
    CMD_SET_PWD,
    SYNC2_GEN2,
    Frame,
    build_frame,
    parse_frame,
)
from scootscoot.profiles.types import ENC2_GEN2, ENC2_GEN3, CryptoSuite

_LOGGER = logging.getLogger(__name__)

PRE_COMM_TIMEOUT = 2.0
PRE_COMM_ATTEMPTS = 10
SET_PWD_TIMEOUT = 2.0
SET_PWD_ATTEMPTS = 1
AUTH_TIMEOUT = 2.0
AUTH_ATTEMPTS = 3
CONFIRM_TIMEOUT = 60.0
#: How many "still waiting for the button" SET_PWD frames the vehicle may send
#: before we give up with PairingTimeout. The driver waits passively on each one
#: rather than re-sending SET_PWD, so this is a bound on unsolicited frames, not
#: a poll count -- a vehicle that chatters forever must not wedge the handshake.
MAX_CONFIRMATIONS = 30

_PRE_COMM_PAYLOAD_LEN = 30
_SERIAL_LEN = 14


@dataclass(frozen=True, slots=True)
class Send:
    """Write `payload`, then feed the reply back in."""

    payload: bytes
    timeout: float
    attempts: int


@dataclass(frozen=True, slots=True)
class AwaitConfirmation:
    """The vehicle wants a physical button press. Wait, then feed the reply."""

    timeout: float


@dataclass(frozen=True, slots=True)
class Established:
    """The session is authenticated."""

    crypto: NbCrypto
    serial: str
    password: bytes
    sync2: int
    #: True when a new password was negotiated and the caller should persist it.
    paired: bool


Step = Send | AwaitConfirmation | Established


class _Phase(Enum):
    INITIAL = auto()
    PRE_COMM = auto()
    SET_PWD = auto()
    AUTH = auto()
    DONE = auto()


class Handshake:
    """Drives PRE_COMM -> SET_PWD -> AUTH. One instance per connection."""

    def __init__(
        self,
        *,
        device_name: str,
        suite: CryptoSuite,
        ble_address: int,
        password: bytes | None = None,
        allow_pairing: bool = False,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._name = device_name.encode()
        self._suite = suite
        self._ble = ble_address
        self._password = password
        self._allow_pairing = allow_pairing
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))

        self._phase = _Phase.INITIAL
        self._crypto = NbCrypto(ecb_input=suite.ecb_input)
        self._sync2 = suite.sync2
        self._auth = b""
        self._serial = b""
        self._request = b""
        self._paired = False
        self._suite_retried = False
        self._confirmations = 0

    def start(self) -> Step:
        """Build the PRE_COMM request."""
        self._crypto = NbCrypto(ecb_input=self._suite.ecb_input)
        self._crypto.set_key(self._name, self._suite.initial_key2)
        self._sync2 = self._suite.sync2
        self._request = self._crypto.encrypt(
            build_frame(self._ble, CMD_PRE_COMM, 0x00, sync2=self._sync2)
        )
        self._phase = _Phase.PRE_COMM
        return Send(self._request, PRE_COMM_TIMEOUT, PRE_COMM_ATTEMPTS)

    def feed(self, raw: bytes) -> Step:
        """Consume one encrypted response frame and return the next step."""
        if self._phase is _Phase.PRE_COMM:
            return self._feed_pre_comm(raw)
        if self._phase is _Phase.SET_PWD:
            return self._feed_set_pwd(raw)
        if self._phase is _Phase.AUTH:
            return self._feed_auth(raw)
        msg = f"handshake received a frame while in phase {self._phase.name}"
        raise HandshakeFailed(msg)

    def _feed_pre_comm(self, raw: bytes) -> Step:
        if raw == self._request:
            msg = (
                "the vehicle echoed our PRE_COMM frame instead of answering; "
                "another client (usually the phone app) most likely holds its "
                "single BLE slot"
            )
            raise VehicleBusy(msg)

        plaintext, status = self._decrypt_pre_comm(raw)

        frame = parse_frame(plaintext)
        if frame is None or frame.cmd != CMD_PRE_COMM:
            msg = f"unexpected PRE_COMM response (status={status.name}): {plaintext.hex()}"
            raise ProtocolError(msg)
        if len(frame.data) < _PRE_COMM_PAYLOAD_LEN:
            msg = f"PRE_COMM payload too short: {len(frame.data)} bytes"
            raise ProtocolError(msg)

        # The vehicle generates its own sync byte. Adopt it rather than trusting
        # the profile -- the header is copied verbatim through encryption, so it
        # is readable straight off the wire.
        self._sync2 = raw[1]
        self._auth = frame.data[:16]
        self._serial = frame.data[16:_PRE_COMM_PAYLOAD_LEN]
        has_stored_password = frame.index != 0

        self._crypto.set_auth_param(self._auth)
        self._crypto.start_sn()

        if self._password is not None:
            return self._begin_auth()

        if has_stored_password:
            msg = (
                "the vehicle holds a password from an earlier pairing and will "
                "silently ignore SET_PWD; supply that password instead. On iOS it "
                "is the NSUserDefaults key {serial}_decrypt in "
                "com.ninebot.segway.plist, holding 16 raw bytes"
            )
            raise PairingRequired(msg)

        if not self._allow_pairing:
            msg = "no password supplied and allow_pairing is False"
            raise PairingRequired(msg)

        return self._begin_set_pwd()

    def _decrypt_pre_comm(self, raw: bytes) -> tuple[bytes, CryptoStatus]:
        plaintext, status = self._crypto.decrypt(raw)
        if status is CryptoStatus.OK:
            return plaintext, status

        if self._suite_retried:
            msg = "PRE_COMM response did not decrypt under either Encryption2 suite"
            raise ProtocolError(msg)

        alternate = _alternate_suite(self._suite)
        _LOGGER.debug(
            "PRE_COMM failed under %s; retrying under %s", self._suite.label, alternate.label
        )
        self._suite_retried = True
        self._suite = alternate
        self._crypto = NbCrypto(ecb_input=alternate.ecb_input)
        self._crypto.set_key(self._name, alternate.initial_key2)

        plaintext, status = self._crypto.decrypt(raw)
        if status is not CryptoStatus.OK:
            msg = "PRE_COMM response did not decrypt under either Encryption2 suite"
            raise ProtocolError(msg)
        return plaintext, status

    def _begin_set_pwd(self) -> Step:
        self._crypto.set_key(self._name, self._auth)
        self._password = generate_password(self._auth, self._clock_ms())
        self._paired = True
        self._phase = _Phase.SET_PWD
        payload = self._crypto.encrypt(
            build_frame(self._ble, CMD_SET_PWD, 0x00, self._password, sync2=self._sync2)
        )
        return Send(payload, SET_PWD_TIMEOUT, SET_PWD_ATTEMPTS)

    def _feed_set_pwd(self, raw: bytes) -> Step:
        frame = self._expect(raw, CMD_SET_PWD)
        if frame.index == 1:
            return self._begin_auth()

        self._confirmations += 1
        if self._confirmations > MAX_CONFIRMATIONS:
            msg = "the vehicle never confirmed pairing; was its button pressed?"
            raise PairingTimeout(msg)
        return AwaitConfirmation(CONFIRM_TIMEOUT)

    def _begin_auth(self) -> Step:
        password = self._password
        if password is None:  # pragma: no cover - guarded by the callers
            msg = "internal error: AUTH requires a password"
            raise HandshakeFailed(msg)

        # The counter simply increments per encrypt; that is all the protocol
        # needs. The first SN-mode frame is always counter 2: on the pairing
        # path that is SET_PWD, and AUTH follows at 3; on reconnect SET_PWD is
        # skipped so AUTH itself is the first at 2. The vehicle tracks which
        # flow it is in via the stored-password flag, so no special-casing
        # belongs here.
        self._crypto.set_key(password, self._auth)
        self._phase = _Phase.AUTH
        payload = self._crypto.encrypt(
            build_frame(self._ble, CMD_AUTH, 0x00, self._serial[:_SERIAL_LEN], sync2=self._sync2)
        )
        return Send(payload, AUTH_TIMEOUT, AUTH_ATTEMPTS)

    def _feed_auth(self, raw: bytes) -> Step:
        frame = self._expect(raw, CMD_AUTH)
        if frame.index != 1:
            msg = (
                f"AUTH rejected (index={frame.index}); the password is wrong or "
                "stale for this vehicle"
            )
            raise AuthenticationFailed(msg)

        password = self._password
        if password is None:  # pragma: no cover - guarded by _begin_auth
            msg = "internal error: authenticated without a password"
            raise HandshakeFailed(msg)

        self._phase = _Phase.DONE
        return Established(
            crypto=self._crypto,
            serial=self._serial.decode("ascii", errors="replace").replace("\x00", "").strip(),
            password=password,
            sync2=self._sync2,
            paired=self._paired,
        )

    def _expect(self, raw: bytes, cmd: int) -> Frame:
        plaintext, status = self._crypto.decrypt(raw)
        if status is not CryptoStatus.OK:
            msg = f"handshake response failed verification ({status.name})"
            raise ProtocolError(msg)
        frame = parse_frame(plaintext)
        if frame is None:
            msg = f"unparseable handshake response: {plaintext.hex()}"
            raise ProtocolError(msg)
        if frame.cmd != cmd:
            msg = f"expected cmd 0x{cmd:02X}, got 0x{frame.cmd:02X}"
            raise ProtocolError(msg)
        return frame


def _alternate_suite(suite: CryptoSuite) -> CryptoSuite:
    return ENC2_GEN3 if suite.sync2 == SYNC2_GEN2 else ENC2_GEN2
