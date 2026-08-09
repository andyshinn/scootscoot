"""Encryption2 frame construction, parsing, and stream reassembly.

Request  (app -> vehicle):  [0x5A, sync2, LEN, 0x3E, target, cmd, index, *data]
Response (vehicle -> app):  [0x5A, sync2, LEN, source_board, 0x3E, cmd, index, *data]

Note the 0x3E moves between the two layouts. On the wire, after encryption, a
frame is always LEN + 13 bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

SYNC1 = 0x5A
SYNC2_GEN2 = 0xA5
SYNC2_GEN3 = 0xB5
VALID_SYNC2 = frozenset({SYNC2_GEN2, SYNC2_GEN3})

#: Protocol-layer identifier. Not a board address. Frames without it are dropped.
BT_ID = 0x3E

#: Encrypted frame length = LEN + header(3) + tag(4) + counter(2) + ... = LEN + 13.
FRAME_OVERHEAD = 13

_MIN_FRAME_LEN = 7
_MAX_PAYLOAD = 255

CMD_READ = 0x01
CMD_WRITE = 0x02
CMD_WRITE_NR = 0x03
CMD_READ_RESP = 0x04
CMD_WRITE_RESP = 0x05

CMD_PRE_COMM = 0x5B
CMD_SET_PWD = 0x5C
CMD_AUTH = 0x5D


@dataclass(frozen=True, slots=True)
class Frame:
    """A decrypted response frame."""

    length: int
    board_id: int
    cmd: int
    index: int
    data: bytes


def build_frame(
    target: int,
    cmd: int,
    index: int,
    data: bytes = b"",
    *,
    sync2: int = SYNC2_GEN2,
) -> bytes:
    """Build a plaintext request frame."""
    if len(data) > _MAX_PAYLOAD:
        msg = f"payload too long: {len(data)} > {_MAX_PAYLOAD}"
        raise ValueError(msg)
    return bytes([SYNC1, sync2, len(data), BT_ID, target, cmd, index]) + data


def build_read(target: int, index: int, length: int, *, sync2: int = SYNC2_GEN2) -> bytes:
    """Build a register read. The payload is the requested byte count."""
    return build_frame(target, CMD_READ, index, bytes([length]), sync2=sync2)


def parse_frame(plaintext: bytes) -> Frame | None:
    """Parse a decrypted response frame, or None if it is not one."""
    if len(plaintext) < _MIN_FRAME_LEN:
        return None
    if plaintext[0] != SYNC1 or plaintext[1] not in VALID_SYNC2:
        return None
    if plaintext[4] != BT_ID:
        return None
    length = plaintext[2]
    return Frame(
        length=length,
        board_id=plaintext[3],
        cmd=plaintext[5],
        index=plaintext[6],
        data=plaintext[7 : 7 + length],
    )


class FrameAssembler:
    """Reassembles encrypted frames from a stream of GATT notification chunks."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def clear(self) -> None:
        self._buf.clear()

    def feed(self, chunk: bytes) -> list[bytes]:
        """Add a chunk and return every complete frame it completed."""
        self._buf.extend(chunk)
        frames: list[bytes] = []
        while True:
            start = self._find_sync()
            if start is None:
                break
            if start:
                del self._buf[:start]
            if len(self._buf) < 3:
                break
            total = self._buf[2] + FRAME_OVERHEAD
            if len(self._buf) < total:
                break
            frames.append(bytes(self._buf[:total]))
            del self._buf[:total]
        return frames

    def _find_sync(self) -> int | None:
        """Offset of the next sync pair, trimming the buffer when there is none."""
        for i in range(len(self._buf) - 1):
            if self._buf[i] == SYNC1 and self._buf[i + 1] in VALID_SYNC2:
                return i
        # Keep a trailing lone 0x5A: the sync pair may straddle two chunks.
        if self._buf and self._buf[-1] == SYNC1:
            del self._buf[:-1]
        else:
            self._buf.clear()
        return None
