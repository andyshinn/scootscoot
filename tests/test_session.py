from __future__ import annotations

import asyncio
from collections.abc import Callable

from scootscoot.crypto import CryptoStatus, NbCrypto
from scootscoot.framing import CMD_READ, CMD_READ_RESP, SYNC2_GEN2, parse_frame
from scootscoot.profiles import GT3_PRO
from scootscoot.profiles.types import BoardRole
from scootscoot.session import ScooterSession
from tests.vehicle_frames import AUTH_PARAM, SERIAL, STORED_PASSWORD, response_plaintext

VCU = GT3_PRO.board(BoardRole.VCU).address
BMS = GT3_PRO.board(BoardRole.BMS1).address
MCU = GT3_PRO.board(BoardRole.MCU).address

#: Given (board, index, length) from a decrypted request, the plaintext frames
#: the vehicle sends back. An empty list is silence.
Responder = Callable[[int, int, int], list[bytes]]


def _sn_crypto() -> NbCrypto:
    crypto = NbCrypto()
    crypto.set_key(STORED_PASSWORD, AUTH_PARAM)
    crypto.set_auth_param(AUTH_PARAM)
    crypto.start_sn()
    return crypto


class FakeVehicle:
    """A FrameChannel that decrypts each request and queues scripted replies."""

    def __init__(self, respond: Responder) -> None:
        self._respond = respond
        self._crypto = _sn_crypto()
        self._queue: list[bytes] = []

    async def send(self, data: bytes) -> None:
        plaintext, status = self._crypto.decrypt(data)
        assert status is CryptoStatus.OK
        assert plaintext[5] == CMD_READ
        board, index, length = plaintext[4], plaintext[6], plaintext[7]
        self._queue.extend(
            self._crypto.encrypt(reply) for reply in self._respond(board, index, length)
        )

    async def recv(self, timeout: float) -> bytes:
        if not self._queue:
            raise TimeoutError
        return self._queue.pop(0)

    def drain(self) -> None:
        self._queue.clear()


def session(respond: Responder) -> ScooterSession:
    return ScooterSession(
        FakeVehicle(respond),
        _sn_crypto(),
        GT3_PRO,
        sync2=SYNC2_GEN2,
        serial=SERIAL.decode(),
    )


def reply(board: int, index: int, data: bytes, *, cmd: int = CMD_READ_RESP) -> bytes:
    return response_plaintext(SYNC2_GEN2, board, cmd, index, data)


def read(respond: Responder, board: int = VCU, index: int = 0x55, length: int = 2) -> bytes | None:
    return asyncio.run(session(respond).read_raw(board, index, length))


def test_fake_vehicle_round_trips_a_frame() -> None:
    frame = parse_frame(reply(VCU, 0x55, b"\x50\x00"))
    assert frame is not None
    assert (frame.board_id, frame.cmd, frame.index) == (VCU, CMD_READ_RESP, 0x55)


def test_read_raw_returns_a_full_read_response() -> None:
    assert read(lambda b, i, n: [reply(b, i, b"\x50\x00")]) == b"\x50\x00"


def test_read_raw_returns_none_on_silence() -> None:
    assert read(lambda b, i, n: []) is None


def test_read_raw_rejects_an_empty_payload() -> None:
    assert read(lambda b, i, n: [reply(b, i, b"")]) is None


def test_read_raw_rejects_a_payload_shorter_than_requested() -> None:
    assert read(lambda b, i, n: [reply(b, i, b"\x50")]) is None


def test_read_raw_accepts_a_payload_longer_than_requested() -> None:
    assert read(lambda b, i, n: [reply(b, i, b"\x50\x00\x01")]) == b"\x50\x00\x01"


def test_read_raw_rejects_a_frame_that_is_not_a_read_response() -> None:
    assert read(lambda b, i, n: [reply(b, i, b"\x50\x00", cmd=CMD_READ)]) is None


def test_read_raw_rejects_a_reply_for_another_register() -> None:
    assert read(lambda b, i, n: [reply(b, i + 1, b"\x50\x00")]) is None


def test_read_raw_rejects_a_reply_from_another_board() -> None:
    assert read(lambda b, i, n: [reply(BMS, i, b"\x50\x00")]) is None


def test_poll_does_not_count_empty_vcu_replies_as_a_responding_board() -> None:
    # A parked scooter whose VCU address answers every read with an empty
    # payload must still read as parked, not powered on.
    def respond(board: int, index: int, length: int) -> list[bytes]:
        if board == BMS:
            return [reply(board, index, bytes(length))]
        return [reply(board, index, b"")]

    state = asyncio.run(session(respond).poll())
    assert state.responding == frozenset({BoardRole.BMS1})
    assert state.battery is not None
    assert state.vehicle is None
    assert state.motor is None


def test_poll_reports_every_board_on_a_switched_on_scooter() -> None:
    state = asyncio.run(session(lambda b, i, n: [reply(b, i, bytes(n))]).poll())
    assert state.responding == frozenset({BoardRole.BMS1, BoardRole.VCU, BoardRole.MCU})
    assert state.vehicle is not None


def test_poll_on_a_parked_gt3_reports_the_vcu_but_not_the_mcu() -> None:
    # What a switched-off GT3 actually does: the VCU still answers in full and
    # only the MCU is silent, so the MCU is what separates parked from on.
    def respond(board: int, index: int, length: int) -> list[bytes]:
        return [] if board == MCU else [reply(board, index, bytes(length))]

    state = asyncio.run(session(respond).poll())
    assert state.responding == frozenset({BoardRole.BMS1, BoardRole.VCU})
    assert state.vehicle is not None
    assert state.motor is None


def test_poll_retries_a_dropped_reply_once() -> None:
    requests: list[tuple[int, int]] = []

    def respond(board: int, index: int, length: int) -> list[bytes]:
        requests.append((board, index))
        if (board, index) == (BMS, 0x8F) and requests.count((BMS, 0x8F)) == 1:
            return []
        return [reply(board, index, bytes(length))]

    state = asyncio.run(session(respond).poll())
    assert requests.count((BMS, 0x8F)) == 2
    assert state.battery is not None
    assert state.battery.soc_percent == 0


def test_poll_gives_a_sleeping_board_one_retry_then_skips_it() -> None:
    requests: list[tuple[int, int]] = []

    def respond(board: int, index: int, length: int) -> list[bytes]:
        requests.append((board, index))
        return [] if board == MCU else [reply(board, index, bytes(length))]

    asyncio.run(session(respond).poll())
    assert [request for request in requests if request[0] == MCU] == [(MCU, 0x3E)] * 2


def test_poll_does_not_retry_a_reply_that_arrived() -> None:
    requests: list[tuple[int, int]] = []

    def respond(board: int, index: int, length: int) -> list[bytes]:
        requests.append((board, index))
        return [reply(board, index, bytes(length))]

    asyncio.run(session(respond).poll())
    assert len(requests) == len(GT3_PRO.poll)
