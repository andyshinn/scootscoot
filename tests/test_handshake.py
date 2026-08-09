from __future__ import annotations

import pytest

from scootscoot.crypto import NbCrypto, generate_password
from scootscoot.exceptions import (
    AuthenticationFailed,
    PairingRequired,
    PairingTimeout,
    ProtocolError,
    VehicleBusy,
)
from scootscoot.framing import CMD_PRE_COMM, SYNC2_GEN2, SYNC2_GEN3
from scootscoot.handshake import AwaitConfirmation, Established, Handshake, Send
from scootscoot.profiles.types import ENC2_GEN2, ENC2_GEN3, CryptoSuite
from tests.vehicle_frames import (
    AUTH_PARAM,
    BLE_ADDRESS,
    DEVICE_NAME,
    STORED_PASSWORD,
    _sn_frame,
    auth_response,
    pre_comm_response,
    response_plaintext,
    set_pwd_response,
)

FIXED_CLOCK = 1_700_000_000_000


def make(
    *,
    suite: CryptoSuite = ENC2_GEN2,
    password: bytes | None = STORED_PASSWORD,
    allow_pairing: bool = False,
) -> Handshake:
    return Handshake(
        device_name=DEVICE_NAME,
        suite=suite,
        ble_address=BLE_ADDRESS,
        password=password,
        allow_pairing=allow_pairing,
        clock_ms=lambda: FIXED_CLOCK,
    )


def test_start_emits_an_encrypted_pre_comm() -> None:
    step = make().start()
    assert isinstance(step, Send)
    assert step.attempts == 10
    # The header travels in the clear, so we can read the sync byte off the wire.
    assert step.payload[0] == 0x5A
    assert step.payload[1] == SYNC2_GEN2
    assert len(step.payload) == step.payload[2] + 13


def test_start_pre_comm_decrypts_to_the_documented_frame() -> None:
    step = make().start()
    assert isinstance(step, Send)
    crypto = NbCrypto(ecb_input=ENC2_GEN2.ecb_input)
    crypto.set_key(DEVICE_NAME.encode(), ENC2_GEN2.initial_key2)
    plaintext, _ = crypto.decrypt(step.payload)
    assert plaintext == bytes.fromhex("5aa5003e045b00")


def test_an_echoed_pre_comm_is_reported_as_a_busy_vehicle() -> None:
    handshake = make()
    step = handshake.start()
    assert isinstance(step, Send)
    with pytest.raises(VehicleBusy, match="echoed"):
        handshake.feed(step.payload)


def test_stored_password_path_skips_set_pwd_and_authenticates() -> None:
    handshake = make()
    handshake.start()

    step = handshake.feed(pre_comm_response(ENC2_GEN2, has_stored_password=True))
    assert isinstance(step, Send)
    # AUTH is the first SN-mode frame, so it must carry counter 2.
    assert step.payload[-2:] == b"\x00\x02"
    assert step.attempts == 3

    step = handshake.feed(auth_response(ENC2_GEN2, accepted=True, password=STORED_PASSWORD))
    assert isinstance(step, Established)
    assert step.serial == "03GGG2527C0165"
    assert step.password == STORED_PASSWORD
    assert step.sync2 == SYNC2_GEN2
    assert step.paired is False
    assert step.crypto.counter >= 2


def test_rejected_auth_raises() -> None:
    handshake = make()
    handshake.start()
    handshake.feed(pre_comm_response(ENC2_GEN2, has_stored_password=True))
    with pytest.raises(AuthenticationFailed, match="stale"):
        handshake.feed(auth_response(ENC2_GEN2, accepted=False, password=STORED_PASSWORD))


def test_a_stored_password_we_do_not_have_raises_rather_than_hanging() -> None:
    # SET_PWD would be silently dropped, producing a timeout rather than an
    # error. Fail immediately and say where the password lives.
    handshake = make(password=None, allow_pairing=True)
    handshake.start()
    with pytest.raises(PairingRequired, match="_decrypt"):
        handshake.feed(pre_comm_response(ENC2_GEN2, has_stored_password=True))


def test_pairing_is_refused_unless_explicitly_allowed() -> None:
    handshake = make(password=None, allow_pairing=False)
    handshake.start()
    with pytest.raises(PairingRequired, match="allow_pairing"):
        handshake.feed(pre_comm_response(ENC2_GEN2, has_stored_password=False))


def test_pairing_generates_a_password_and_authenticates() -> None:
    handshake = make(password=None, allow_pairing=True)
    handshake.start()

    step = handshake.feed(pre_comm_response(ENC2_GEN2, has_stored_password=False))
    assert isinstance(step, Send)
    assert step.payload[-2:] == b"\x00\x02"  # SET_PWD is the first SN frame

    step = handshake.feed(set_pwd_response(ENC2_GEN2, accepted=True))
    assert isinstance(step, Send)  # now AUTH

    expected = generate_password(AUTH_PARAM, FIXED_CLOCK)
    step = handshake.feed(auth_response(ENC2_GEN2, accepted=True, password=expected))
    assert isinstance(step, Established)
    assert step.password == expected
    assert step.paired is True


def test_pending_set_pwd_asks_the_caller_to_wait() -> None:
    handshake = make(password=None, allow_pairing=True)
    handshake.start()
    handshake.feed(pre_comm_response(ENC2_GEN2, has_stored_password=False))

    step = handshake.feed(set_pwd_response(ENC2_GEN2, accepted=False))
    assert isinstance(step, AwaitConfirmation)
    assert step.timeout == 60.0

    step = handshake.feed(set_pwd_response(ENC2_GEN2, accepted=True, counter=3))
    assert isinstance(step, Send)  # confirmed, moving to AUTH


def test_endless_pending_set_pwd_eventually_times_out() -> None:
    handshake = make(password=None, allow_pairing=True)
    handshake.start()
    handshake.feed(pre_comm_response(ENC2_GEN2, has_stored_password=False))
    with pytest.raises(PairingTimeout):
        for counter in range(2, 60):
            handshake.feed(set_pwd_response(ENC2_GEN2, accepted=False, counter=counter))


def test_a_mis_declared_generation_recovers_by_retrying_the_other_suite() -> None:
    # Profile says gen3; the vehicle is actually gen2.
    handshake = make(suite=ENC2_GEN3)
    step = handshake.start()
    assert isinstance(step, Send)
    assert step.payload[1] == SYNC2_GEN3

    step = handshake.feed(pre_comm_response(ENC2_GEN2, has_stored_password=True))
    assert isinstance(step, Send)
    # Every subsequent frame uses the sync byte the vehicle generated.
    assert step.payload[1] == SYNC2_GEN2

    step = handshake.feed(auth_response(ENC2_GEN2, accepted=True, password=STORED_PASSWORD))
    assert isinstance(step, Established)
    assert step.sync2 == SYNC2_GEN2


def test_a_response_that_decrypts_under_neither_suite_raises() -> None:
    handshake = make()
    handshake.start()
    with pytest.raises(ProtocolError):
        handshake.feed(bytes(26))


def test_a_short_pre_comm_payload_raises() -> None:
    handshake = make()
    handshake.start()
    truncated = _encrypt_non_sn(
        response_plaintext(SYNC2_GEN2, BLE_ADDRESS, CMD_PRE_COMM, 1, AUTH_PARAM)
    )
    with pytest.raises(ProtocolError, match="too short"):
        handshake.feed(truncated)


def test_an_unexpected_command_raises() -> None:
    handshake = make()
    handshake.start()
    handshake.feed(pre_comm_response(ENC2_GEN2, has_stored_password=True))
    wrong = auth_response(ENC2_GEN2, accepted=True, password=STORED_PASSWORD)
    # Rebuild the same reply under a different command byte.
    frame = _sn_frame(
        response_plaintext(SYNC2_GEN2, BLE_ADDRESS, CMD_PRE_COMM, 1),
        ENC2_GEN2,
        STORED_PASSWORD,
        AUTH_PARAM,
        AUTH_PARAM,
        3,
    )
    assert frame != wrong
    with pytest.raises(ProtocolError, match="cmd"):
        handshake.feed(frame)


def _encrypt_non_sn(plaintext: bytes) -> bytes:
    crypto = NbCrypto(ecb_input=ENC2_GEN2.ecb_input)
    crypto.set_key(DEVICE_NAME.encode(), ENC2_GEN2.initial_key2)
    return crypto.encrypt(plaintext)
