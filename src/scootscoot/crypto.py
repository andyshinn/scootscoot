"""Encryption2 (authV2) crypto primitives.

Ported from the reference implementation, which was verified against a Ghidra
decompilation of libnbcrypto.so: nb_encrypt @ 0x169f80, the CBC-MAC routine
@ 0x16a35c, and nb_decrypt @ 0x16a55c.

The construction resembles AES-CCM but is not CCM: the CTR nonce format is
custom and the MAC is truncated to four bytes. Do not substitute a standard
mode -- the vehicle will reject the frames.
"""

from __future__ import annotations

import hashlib
import logging
import struct
import time
from enum import IntEnum

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

#: Fixed protocol parameter from libnbcrypto.so @ 0x45A80. Shared by every
#: device and app version; used as the gen2 ECB input and initial key2.
FW_DATA = bytes.fromhex("97cfb802844143de56002b3b34780a5d")
ZERO16 = b"\x00" * 16

_HEADER_LEN = 3
_TAIL_LEN = 6
_TAG_LEN = 4


class CryptoStatus(IntEnum):
    """Outcome of a decrypt attempt."""

    OK = 0
    MAC_MISMATCH = 1
    REPLAY = 2


def aes_ecb_block(key: bytes, block: bytes) -> bytes:
    """Encrypt exactly one 16-byte block with AES-128-ECB."""
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(block) + encryptor.finalize()


def derive_key(key1: bytes, key2: bytes | None) -> bytes:
    """SHA-1(key1_pad16 || key2_pad16)[0:16] -> AES-128 key."""
    k1 = (key1 + ZERO16)[:16]
    k2 = (key2 + ZERO16)[:16] if key2 else ZERO16
    return hashlib.sha1(k1 + k2, usedforsecurity=False).digest()[:16]


def build_nonce(counter: int, auth: bytes) -> bytes:
    """13-byte nonce: counter_BE32 || auth[0:8] || 0x00."""
    return struct.pack(">I", counter) + auth[:8] + b"\x00"


def _a_block(nonce13: bytes, index: int) -> bytes:
    """CTR keystream block A_i = 0x01 || nonce || 0x00 || i."""
    return b"\x01" + nonce13 + bytes([0x00, index & 0xFF])


def _b0(nonce13: bytes, payload_len: int) -> bytes:
    """CBC-MAC seed block B_0 = 0x59 || nonce || 0x00 || payload_len."""
    return b"\x59" + nonce13 + bytes([0x00, payload_len & 0xFF])


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right, strict=False))


def cbc_mac(key: bytes, plaintext: bytes, nonce13: bytes) -> bytes:
    """Four-byte CBC-MAC over a plaintext frame.

    The three-byte frame header is folded in as associated data, zero-padded to
    a full block, before the payload blocks.
    """
    state = aes_ecb_block(key, _b0(nonce13, len(plaintext) - _HEADER_LEN))
    state = aes_ecb_block(key, _xor(state, plaintext[:_HEADER_LEN] + b"\x00" * 13))
    payload = plaintext[_HEADER_LEN:]
    for offset in range(0, len(payload), 16):
        block = payload[offset : offset + 16].ljust(16, b"\x00")
        state = aes_ecb_block(key, _xor(state, block))
    return state[:_TAG_LEN]


def ctr_xor(key: bytes, data: bytes, nonce13: bytes, start: int = 1) -> bytes:
    """CTR-mode XOR. Symmetric, so this both encrypts and decrypts."""
    out = bytearray()
    index = start
    for offset in range(0, len(data), 16):
        keystream = aes_ecb_block(key, _a_block(nonce13, index))
        out += _xor(data[offset : offset + 16], keystream)
        index += 1
    return bytes(out)


class NbCrypto:
    """Stateful Encryption2 context: keys, auth parameter, packet counter.

    Performs no I/O. One instance corresponds to one connection; the counter and
    derived key cannot outlive it, because the vehicle regenerates its auth
    parameter on every PRE_COMM.
    """

    def __init__(self, ecb_input: bytes = ZERO16, *, strict_replay: bool = False) -> None:
        self.key1: bytes = b""
        self.key2: bytes | None = None
        self.auth: bytes = ZERO16
        self.counter: int = 0
        self.ecb_input: bytes = ecb_input[:16]
        self.strict_replay = strict_replay
        self.last_received: int = 0

    def set_key(self, key1: bytes, key2: bytes | None) -> None:
        self.key1 = key1
        self.key2 = key2

    def set_auth_param(self, auth: bytes) -> None:
        self.auth = bytes(auth[:16])

    def start_sn(self) -> None:
        """Enter SN mode. The next encrypt uses counter 2."""
        self.counter = 1

    def reset_sn(self) -> None:
        self.counter = 0
        self.last_received = 0

    def _aes_key(self) -> bytes:
        return derive_key(self.key1, self.key2)

    def encrypt(self, plaintext: bytes) -> bytes:
        key = self._aes_key()
        header = plaintext[:_HEADER_LEN]
        if self.counter > 0:
            self.counter += 1
            nonce = build_nonce(self.counter, self.auth)
            tag = cbc_mac(key, plaintext, nonce)
            body = ctr_xor(key, plaintext[_HEADER_LEN:], nonce)
            enc_tag = _xor(tag, aes_ecb_block(key, _a_block(nonce, 0))[:_TAG_LEN])
            return header + body + enc_tag + struct.pack(">H", self.counter & 0xFFFF)

        payload = plaintext[_HEADER_LEN:]
        checksum = (~sum(payload)) & 0xFFFF
        keystream = aes_ecb_block(key, self.ecb_input)
        body_buf = bytearray()
        for offset in range(0, len(payload), 16):
            body_buf += _xor(payload[offset : offset + 16], keystream)
        tail = bytes([0x00, 0x00, checksum & 0xFF, (checksum >> 8) & 0xFF, 0x00, 0x00])
        return header + bytes(body_buf) + tail

    def decrypt(self, frame: bytes) -> tuple[bytes, CryptoStatus]:
        if len(frame) < _HEADER_LEN + _TAIL_LEN:
            msg = f"frame too short to decrypt: {len(frame)} bytes"
            raise ValueError(msg)

        key = self._aes_key()
        header = frame[:_HEADER_LEN]
        tail = frame[-_TAIL_LEN:]
        body = frame[_HEADER_LEN:-_TAIL_LEN]
        counter = (tail[4] << 8) | tail[5]

        if counter > 0:
            if counter <= self.last_received:
                if self.strict_replay:
                    return b"", CryptoStatus.REPLAY
                _LOGGER.warning(
                    "non-increasing receive counter %d (last seen %d); accepting anyway",
                    counter,
                    self.last_received,
                )
            nonce = build_nonce(counter, self.auth)
            plaintext = header + ctr_xor(key, body, nonce)
            recv_tag = _xor(tail[:_TAG_LEN], aes_ecb_block(key, _a_block(nonce, 0))[:_TAG_LEN])
            if recv_tag != cbc_mac(key, plaintext, nonce):
                return plaintext, CryptoStatus.MAC_MISMATCH
            self.last_received = counter
            return plaintext, CryptoStatus.OK

        keystream = aes_ecb_block(key, self.ecb_input)
        out = bytearray()
        for offset in range(0, len(body), 16):
            out += _xor(body[offset : offset + 16], keystream)
        plaintext = header + bytes(out)
        expected = (~sum(plaintext[_HEADER_LEN:])) & 0xFFFF
        if expected != (tail[2] | (tail[3] << 8)):
            return plaintext, CryptoStatus.MAC_MISMATCH
        return plaintext, CryptoStatus.OK


_JAVA_MASK = (1 << 48) - 1
_JAVA_MULT = 0x5DEECE66D
_JAVA_ADD = 0xB


class JavaRandom:
    """java.util.Random -- a 48-bit LCG. Needed to reproduce app passwords."""

    def __init__(self, seed: int) -> None:
        self._seed = (seed ^ _JAVA_MULT) & _JAVA_MASK

    def _next(self, bits: int) -> int:
        self._seed = (self._seed * _JAVA_MULT + _JAVA_ADD) & _JAVA_MASK
        return self._seed >> (48 - bits)

    def next_int(self) -> int:
        """One nextInt(), as an unsigned 32-bit value."""
        return self._next(32)

    def next_bytes(self, count: int) -> bytes:
        """Fill `count` bytes, four per nextInt(), low byte first."""
        out = bytearray(count)
        i = 0
        while i < count:
            value = self.next_int()
            for shift in range(min(4, count - i)):
                out[i] = (value >> (8 * shift)) & 0xFF
                i += 1
        return bytes(out)


def _java_int(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def _java_long(value: int) -> int:
    value &= 0xFFFFFFFFFFFFFFFF
    return value - 0x10000000000000000 if value >= 0x8000000000000000 else value


def generate_password(auth: bytes, time_ms: int | None = None) -> bytes:
    """Generate a 16-byte session password, matching the app's provider.

    seed = currentTimeMillis + sum(signed(auth[i]) << ((i % 8) * 8)), where the
    shift is a Java int shift and therefore masked with 31.
    """
    if time_ms is None:
        time_ms = int(time.time() * 1000)

    accumulated = 0
    for i, byte in enumerate(auth):
        signed = byte if byte < 128 else byte - 256
        accumulated = _java_long(accumulated + _java_int(signed << (((i % 8) * 8) & 31)))

    random_bytes = JavaRandom(_java_long(time_ms + accumulated)).next_bytes(16)
    return hashlib.sha256(random_bytes).digest()[:16]
