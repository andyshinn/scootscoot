from __future__ import annotations

from scootscoot.framing import (
    BT_ID,
    CMD_AUTH,
    CMD_PRE_COMM,
    SYNC2_GEN2,
    SYNC2_GEN3,
    FrameAssembler,
    build_frame,
    build_read,
    parse_frame,
)


def test_build_frame_lays_out_a_request() -> None:
    assert build_frame(0x04, CMD_PRE_COMM, 0x00).hex() == "5aa5003e045b00"


def test_build_frame_honours_the_gen3_sync_byte() -> None:
    assert build_frame(0x04, CMD_PRE_COMM, 0x00, sync2=SYNC2_GEN3).hex() == "5ab5003e045b00"


def test_build_frame_sets_length_from_the_payload() -> None:
    frame = build_frame(0x04, CMD_AUTH, 0x00, b"03GGG2527C0165")
    assert frame[2] == 14
    assert frame[7:] == b"03GGG2527C0165"


def test_build_read_requests_a_length() -> None:
    # A read carries the requested byte count as its single payload byte.
    assert build_read(0x07, 0x8F, 2).hex() == "5aa5013e07018f02"


def test_parse_frame_reads_a_response() -> None:
    frame = parse_frame(bytes.fromhex("5aa502073e048f3600"))
    assert frame is not None
    assert frame.length == 2
    assert frame.board_id == 0x07
    assert frame.cmd == 0x04
    assert frame.index == 0x8F
    assert frame.data == bytes.fromhex("3600")


def test_parse_frame_accepts_either_sync_byte() -> None:
    for sync2 in (SYNC2_GEN2, SYNC2_GEN3):
        raw = bytes([0x5A, sync2, 0x00, 0x04, BT_ID, CMD_PRE_COMM, 0x01])
        assert parse_frame(raw) is not None


def test_parse_frame_rejects_a_bad_sync() -> None:
    assert parse_frame(bytes([0x5A, 0x99, 0x00, 0x04, BT_ID, CMD_PRE_COMM, 0x01])) is None


def test_parse_frame_rejects_a_wrong_bt_id() -> None:
    # Byte 4 of a response must be 0x3E or the vehicle is not talking to us.
    assert parse_frame(bytes([0x5A, 0xA5, 0x00, 0x04, 0x99, CMD_PRE_COMM, 0x01])) is None


def test_parse_frame_rejects_a_runt() -> None:
    assert parse_frame(b"\x5a\xa5\x00") is None


def test_assembler_yields_a_whole_frame() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(frame) == [frame]


def test_assembler_waits_for_a_frame_split_across_chunks() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(frame[:5]) == []
    assert assembler.feed(frame[5:]) == [frame]


def test_assembler_survives_a_sync_split_across_chunks() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(frame[:1]) == []
    assert assembler.feed(frame[1:]) == [frame]


def test_assembler_skips_a_garbage_prefix() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(b"\xde\xad\xbe\xef" + frame) == [frame]


def test_assembler_returns_two_back_to_back_frames() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(frame + frame) == [frame, frame]


def test_assembler_holds_a_truncated_tail() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(frame + frame[:4]) == [frame]
    assert assembler.feed(frame[4:]) == [frame]


def test_assembler_discards_pure_garbage_without_growing() -> None:
    assembler = FrameAssembler()
    for _ in range(100):
        assert assembler.feed(b"\xde\xad\xbe\xef") == []
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(frame) == [frame]


def test_clear_drops_buffered_bytes() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assembler.feed(frame[:5])
    assembler.clear()
    assert assembler.feed(frame[5:]) == []
