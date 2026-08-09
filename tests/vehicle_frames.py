"""Synthesise vehicle-side frames for handshake tests.

The vehicle encrypts with the same algorithm we do, just with the roles of the
key material swapped per phase. Nothing here simulates a device -- these are
frame builders.
"""

from __future__ import annotations

from scootscoot.crypto import NbCrypto
from scootscoot.framing import BT_ID, CMD_AUTH, CMD_PRE_COMM, CMD_SET_PWD, SYNC1
from scootscoot.profiles.types import CryptoSuite

DEVICE_NAME = "TESTDEVICE0001"
SERIAL = b"03GGG2527C0165"
AUTH_PARAM = bytes(range(16))
BLE_ADDRESS = 0x04
STORED_PASSWORD = bytes.fromhex("000102030405060708090a0b0c0d0e0f")


def response_plaintext(sync2: int, board: int, cmd: int, index: int, data: bytes = b"") -> bytes:
    """A decrypted response: [5A, sync2, LEN, source_board, 3E, cmd, index, *data]."""
    return bytes([SYNC1, sync2, len(data), board, BT_ID, cmd, index]) + data


def pre_comm_response(
    suite: CryptoSuite,
    *,
    has_stored_password: bool,
    auth: bytes = AUTH_PARAM,
    serial: bytes = SERIAL,
    device_name: str = DEVICE_NAME,
) -> bytes:
    """Phase 1 reply. Non-SN mode, keyed on the BLE name and the suite's key2."""
    plaintext = response_plaintext(
        suite.sync2,
        BLE_ADDRESS,
        CMD_PRE_COMM,
        1 if has_stored_password else 0,
        auth + serial,
    )
    crypto = NbCrypto(ecb_input=suite.ecb_input)
    crypto.set_key(device_name.encode(), suite.initial_key2)
    return crypto.encrypt(plaintext)


def set_pwd_response(
    suite: CryptoSuite,
    *,
    accepted: bool,
    auth: bytes = AUTH_PARAM,
    device_name: str = DEVICE_NAME,
    counter: int = 2,
) -> bytes:
    """Phase 2 reply. SN mode, keyed on the BLE name and the auth parameter."""
    plaintext = response_plaintext(suite.sync2, BLE_ADDRESS, CMD_SET_PWD, 1 if accepted else 0)
    return _sn_frame(plaintext, suite, device_name.encode(), auth, auth, counter)


def auth_response(
    suite: CryptoSuite,
    *,
    accepted: bool,
    password: bytes,
    auth: bytes = AUTH_PARAM,
    counter: int = 3,
) -> bytes:
    """Phase 3 reply. SN mode, keyed on the session password and the auth parameter."""
    plaintext = response_plaintext(suite.sync2, BLE_ADDRESS, CMD_AUTH, 1 if accepted else 0)
    return _sn_frame(plaintext, suite, password, auth, auth, counter)


def _sn_frame(
    plaintext: bytes,
    suite: CryptoSuite,
    key1: bytes,
    key2: bytes,
    auth: bytes,
    counter: int,
) -> bytes:
    crypto = NbCrypto(ecb_input=suite.ecb_input)
    crypto.set_key(key1, key2)
    crypto.set_auth_param(auth)
    crypto.counter = counter - 1  # encrypt() increments before use
    return crypto.encrypt(plaintext)
