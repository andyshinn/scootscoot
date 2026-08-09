from __future__ import annotations

import pytest

from scootscoot.crypto import (
    FW_DATA,
    ZERO16,
    CryptoStatus,
    JavaRandom,
    NbCrypto,
    build_nonce,
    derive_key,
    generate_password,
)

NAME = b"TESTDEVICE0001"
AUTH = bytes(range(16))
SERIAL = b"03GGG2527C0165"
PASSWORD = bytes.fromhex("000102030405060708090a0b0c0d0e0f")


def test_fw_data_is_the_documented_constant() -> None:
    assert FW_DATA.hex() == "97cfb802844143de56002b3b34780a5d"
    assert len(FW_DATA) == 16


def test_derive_key_vectors() -> None:
    assert derive_key(NAME, None).hex() == "4d631a0ea0d182f78b084f5d2d062ab3"
    assert derive_key(NAME, FW_DATA).hex() == "cefa338b052ba289c68a9bb59aa4f0da"
    assert derive_key(NAME, AUTH).hex() == "9a7d374d24a3e7005c971c2ff992ce75"


def test_derive_key_treats_none_and_zeros_identically() -> None:
    assert derive_key(NAME, None) == derive_key(NAME, ZERO16)


def test_build_nonce_layout() -> None:
    nonce = build_nonce(2, AUTH)
    assert len(nonce) == 13
    assert nonce[:4] == b"\x00\x00\x00\x02"  # counter, big-endian
    assert nonce[4:12] == AUTH[:8]
    assert nonce[12] == 0x00


def test_non_sn_pre_comm_gen2_vector() -> None:
    crypto = NbCrypto(ecb_input=FW_DATA)
    crypto.set_key(NAME, FW_DATA)
    plain = bytes.fromhex("5aa5003e045b00")
    assert crypto.encrypt(plain).hex() == "5aa500e1748ab4000062ff0000"


def test_non_sn_pre_comm_gen3_vector() -> None:
    crypto = NbCrypto(ecb_input=ZERO16)
    crypto.set_key(NAME, None)
    plain = bytes.fromhex("5ab5003e045b00")
    assert crypto.encrypt(plain).hex() == "5ab50051304030000062ff0000"


def test_gen2_and_gen3_differ_for_the_same_payload() -> None:
    # Same payload bytes, different suite -> different ciphertext. This is the
    # whole reason fw_data matters.
    gen2 = NbCrypto(ecb_input=FW_DATA)
    gen2.set_key(NAME, FW_DATA)
    gen3 = NbCrypto(ecb_input=ZERO16)
    gen3.set_key(NAME, None)
    payload = bytes.fromhex("3e045b00")
    gen2_frame = gen2.encrypt(b"\x5a\xa5\x00" + payload)
    gen3_frame = gen3.encrypt(b"\x5a\xb5\x00" + payload)
    assert gen2_frame[3:] != gen3_frame[3:]


def test_encrypted_frame_length_is_len_plus_thirteen() -> None:
    crypto = NbCrypto(ecb_input=FW_DATA)
    crypto.set_key(NAME, FW_DATA)
    frame = crypto.encrypt(bytes.fromhex("5aa5003e045b00"))
    assert len(frame) == frame[2] + 13


def test_sn_mode_auth_frame_vector() -> None:
    crypto = NbCrypto(ecb_input=FW_DATA)
    crypto.set_key(PASSWORD, AUTH)
    crypto.set_auth_param(AUTH)
    crypto.start_sn()
    plain = bytes.fromhex("5aa50e3e045d00") + SERIAL
    assert crypto.encrypt(plain).hex() == ("5aa50e61953a24af9d804adf4b6574c538dec052420eab3d9f0002")


def test_first_sn_frame_uses_counter_two() -> None:
    # start_sn sets 1 and the first encrypt increments to 2: the first
    # SN-mode frame sent on a fresh crypto context is always counter 2,
    # whatever command it carries. Which command that ends up being (SET_PWD
    # on a fresh pairing, AUTH on a reconnect) is a handshake-level decision,
    # not something this class needs to know about.
    crypto = NbCrypto(ecb_input=FW_DATA)
    crypto.set_key(PASSWORD, AUTH)
    crypto.set_auth_param(AUTH)
    crypto.start_sn()
    frame = crypto.encrypt(bytes.fromhex("5aa50e3e045d00") + SERIAL)
    assert frame[-2:] == b"\x00\x02"


def test_sn_mode_counter_increments_per_frame() -> None:
    crypto = NbCrypto(ecb_input=FW_DATA)
    crypto.set_key(PASSWORD, AUTH)
    crypto.set_auth_param(AUTH)
    crypto.start_sn()
    crypto.encrypt(bytes.fromhex("5aa50e3e045d00") + SERIAL)
    second = crypto.encrypt(bytes.fromhex("5aa5013e07018f02"))
    assert second.hex() == "5aa5015ce8cc32616e65c1a40003"
    assert second[-2:] == b"\x00\x03"


@pytest.mark.parametrize("ecb_input", [ZERO16, FW_DATA])
def test_non_sn_round_trip(ecb_input: bytes) -> None:
    plain = bytes.fromhex("5aa5003e045b00")
    sender = NbCrypto(ecb_input=ecb_input)
    sender.set_key(NAME, None)
    receiver = NbCrypto(ecb_input=ecb_input)
    receiver.set_key(NAME, None)
    decrypted, status = receiver.decrypt(sender.encrypt(plain))
    assert status is CryptoStatus.OK
    assert decrypted == plain


@pytest.mark.parametrize("ecb_input", [ZERO16, FW_DATA])
def test_sn_round_trip(ecb_input: bytes) -> None:
    plain = bytes.fromhex("5aa50e3e045d00") + SERIAL
    sender = NbCrypto(ecb_input=ecb_input)
    sender.set_key(PASSWORD, AUTH)
    sender.set_auth_param(AUTH)
    sender.start_sn()
    receiver = NbCrypto(ecb_input=ecb_input)
    receiver.set_key(PASSWORD, AUTH)
    receiver.set_auth_param(AUTH)
    receiver.start_sn()
    decrypted, status = receiver.decrypt(sender.encrypt(plain))
    assert status is CryptoStatus.OK
    assert decrypted == plain


def test_sn_decrypt_reports_mac_mismatch_on_a_tampered_body() -> None:
    sender = NbCrypto(ecb_input=FW_DATA)
    sender.set_key(PASSWORD, AUTH)
    sender.set_auth_param(AUTH)
    sender.start_sn()
    frame = bytearray(sender.encrypt(bytes.fromhex("5aa50e3e045d00") + SERIAL))
    frame[5] ^= 0xFF
    receiver = NbCrypto(ecb_input=FW_DATA)
    receiver.set_key(PASSWORD, AUTH)
    receiver.set_auth_param(AUTH)
    receiver.start_sn()
    _, status = receiver.decrypt(bytes(frame))
    assert status is CryptoStatus.MAC_MISMATCH


def test_non_sn_decrypt_reports_mismatch_on_a_bad_checksum() -> None:
    crypto = NbCrypto(ecb_input=FW_DATA)
    crypto.set_key(NAME, FW_DATA)
    frame = bytearray(crypto.encrypt(bytes.fromhex("5aa5003e045b00")))
    frame[-4] ^= 0xFF
    _, status = crypto.decrypt(bytes(frame))
    assert status is CryptoStatus.MAC_MISMATCH


def test_wrong_suite_fails_the_non_sn_checksum() -> None:
    # This is what lets the handshake detect a mis-declared generation and
    # retry under the other suite instead of timing out.
    sender = NbCrypto(ecb_input=FW_DATA)
    sender.set_key(NAME, FW_DATA)
    frame = sender.encrypt(bytes.fromhex("5aa5003e045b00"))
    wrong = NbCrypto(ecb_input=ZERO16)
    wrong.set_key(NAME, None)
    _, status = wrong.decrypt(frame)
    assert status is CryptoStatus.MAC_MISMATCH


def test_replay_is_accepted_with_a_warning_by_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender = NbCrypto(ecb_input=FW_DATA)
    sender.set_key(PASSWORD, AUTH)
    sender.set_auth_param(AUTH)
    sender.start_sn()
    frame = sender.encrypt(bytes.fromhex("5aa50e3e045d00") + SERIAL)
    receiver = NbCrypto(ecb_input=FW_DATA)
    receiver.set_key(PASSWORD, AUTH)
    receiver.set_auth_param(AUTH)
    receiver.start_sn()
    receiver.decrypt(frame)
    with caplog.at_level("WARNING"):
        _, status = receiver.decrypt(frame)
    assert status is CryptoStatus.OK
    assert "counter" in caplog.text


def test_replay_is_rejected_when_strict() -> None:
    sender = NbCrypto(ecb_input=FW_DATA)
    sender.set_key(PASSWORD, AUTH)
    sender.set_auth_param(AUTH)
    sender.start_sn()
    frame = sender.encrypt(bytes.fromhex("5aa50e3e045d00") + SERIAL)
    receiver = NbCrypto(ecb_input=FW_DATA, strict_replay=True)
    receiver.set_key(PASSWORD, AUTH)
    receiver.set_auth_param(AUTH)
    receiver.start_sn()
    receiver.decrypt(frame)
    _, status = receiver.decrypt(frame)
    assert status is CryptoStatus.REPLAY


def test_decrypt_rejects_a_frame_shorter_than_its_overhead() -> None:
    crypto = NbCrypto()
    crypto.set_key(NAME, None)
    with pytest.raises(ValueError, match="too short"):
        crypto.decrypt(b"\x5a\xa5\x00")


def test_java_random_matches_published_java_outputs() -> None:
    # java.util.Random(0).nextInt() == -1155484576 signed == 3139482720 unsigned
    assert JavaRandom(0).next_int() == 3139482720
    # java.util.Random(42).nextInt() == -1170105035 signed == 3124862261 unsigned
    assert JavaRandom(42).next_int() == 3124862261


def test_java_random_next_bytes_fills_little_endian_within_each_int() -> None:
    assert JavaRandom(0).next_bytes(4).hex() == "60b420bb"
    assert JavaRandom(12345).next_bytes(16).hex() == "d6209f5c31b3618322a9d8ee7807c8ea"


def test_generate_password_is_deterministic_for_a_fixed_clock() -> None:
    password = generate_password(AUTH, 1_700_000_000_000)
    assert password.hex() == "37f12643761c539457d89f709b3d3834"
    assert len(password) == 16


def test_generate_password_varies_with_the_clock() -> None:
    assert generate_password(AUTH, 1_700_000_000_000) != generate_password(AUTH, 1_700_000_000_001)
