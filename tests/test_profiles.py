from __future__ import annotations

import pytest

from scootscoot import profiles
from scootscoot.crypto import FW_DATA
from scootscoot.exceptions import ServiceNotFound, UnknownBoard, UnknownRegister
from scootscoot.framing import SYNC2_GEN2
from scootscoot.profiles.types import (
    NINEBOT_CUSTOM,
    NORDIC_UART,
    BoardRole,
    DeviceProfile,
    ValueKind,
    choose_gatt_profile,
)


@pytest.mark.parametrize("profile", profiles.ALL, ids=lambda p: p.key)
def test_every_polled_register_is_declared(profile: DeviceProfile) -> None:
    for name in profile.poll:
        assert profile.register(name).name == name


@pytest.mark.parametrize("profile", profiles.ALL, ids=lambda p: p.key)
def test_every_identity_register_is_declared(profile: DeviceProfile) -> None:
    for name in profile.identity:
        assert profile.register(name).name == name


@pytest.mark.parametrize("profile", profiles.ALL, ids=lambda p: p.key)
def test_every_register_targets_a_declared_board(profile: DeviceProfile) -> None:
    declared = {board.role for board in profile.boards}
    for register in profile.registers:
        assert register.board in declared, f"{register.name} targets undeclared {register.board}"


@pytest.mark.parametrize("profile", profiles.ALL, ids=lambda p: p.key)
def test_register_names_are_unique(profile: DeviceProfile) -> None:
    names = [register.name for register in profile.registers]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("profile", profiles.ALL, ids=lambda p: p.key)
def test_board_roles_and_addresses_are_unique(profile: DeviceProfile) -> None:
    roles = [board.role for board in profile.boards]
    addresses = [board.address for board in profile.boards]
    assert len(roles) == len(set(roles))
    assert len(addresses) == len(set(addresses))


@pytest.mark.parametrize("profile", profiles.ALL, ids=lambda p: p.key)
def test_array_registers_request_two_bytes_per_element(profile: DeviceProfile) -> None:
    for register in profile.registers:
        if register.kind is ValueKind.U16_ARRAY:
            assert register.length == register.count * 2, register.name


@pytest.mark.parametrize("profile", profiles.ALL, ids=lambda p: p.key)
def test_at_least_one_board_answers_when_parked(profile: DeviceProfile) -> None:
    assert any(board.awake_when_parked for board in profile.boards)


def test_registry_keys_are_unique() -> None:
    keys = [profile.key for profile in profiles.ALL]
    assert len(keys) == len(set(keys))


def test_get_returns_a_profile_by_key() -> None:
    assert profiles.get("gt3_pro") is profiles.GT3_PRO


def test_get_raises_for_an_unknown_key() -> None:
    with pytest.raises(KeyError):
        profiles.get("no_such_scooter")


def test_gt3_board_addresses_match_the_hardware_sweep() -> None:
    gt3 = profiles.GT3_PRO
    assert gt3.board(BoardRole.VCU).address == 0x16
    assert gt3.board(BoardRole.MCU).address == 0x02
    assert gt3.board(BoardRole.BMS1).address == 0x07
    assert gt3.board(BoardRole.BLE).address == 0x04


def test_gt3_has_no_dashboard_board() -> None:
    # The GT3 Pro has no DIS board, which is why upstream's set-* commands
    # (which target 0x01) do not apply to it.
    with pytest.raises(UnknownBoard):
        profiles.GT3_PRO.board(BoardRole.DIS)


def test_gt3_sleeps_only_the_mcu_when_parked() -> None:
    # Measured: a switched-off GT3 answers every VCU read in full, and no MCU
    # read at all.
    gt3 = profiles.GT3_PRO
    assert gt3.board(BoardRole.BMS1).awake_when_parked
    assert gt3.board(BoardRole.BLE).awake_when_parked
    assert gt3.board(BoardRole.VCU).awake_when_parked
    assert not gt3.board(BoardRole.MCU).awake_when_parked


def test_gt3_uses_the_gen2_crypto_suite() -> None:
    suite = profiles.GT3_PRO.crypto
    assert suite.sync2 == SYNC2_GEN2
    assert suite.ecb_input == FW_DATA
    assert suite.initial_key2 == FW_DATA


def test_gt3_prefers_nordic_uart() -> None:
    assert profiles.GT3_PRO.transports[0] is NORDIC_UART


def test_gt3_range_and_odometer_use_different_scales() -> None:
    # Conflating these produced a "745.2 km range" and a "5.781 km odometer".
    gt3 = profiles.GT3_PRO
    assert gt3.register("rLeftMileage").scale == 0.01
    assert gt3.register("rMileage").scale == 0.1


def test_gt3_pack_has_twenty_cells() -> None:
    # The generated command table says 0x1A bytes; the 72 V pack has 20 cells.
    cells = profiles.GT3_PRO.register("rBmsCellVolFrequence")
    assert cells.count == 20
    assert cells.length == 40


def test_unknown_register_raises() -> None:
    with pytest.raises(UnknownRegister):
        profiles.GT3_PRO.register("rNotAThing")


def test_has_register_is_true_for_a_declared_register() -> None:
    # has_register gates models._decoded and models._responding: a False here
    # silently drops every field of a state group rather than failing loudly.
    assert profiles.GT3_PRO.has_register("rBmsSOC")


def test_has_register_is_false_for_an_undeclared_register() -> None:
    assert not profiles.GT3_PRO.has_register("rNotAThing")


@pytest.mark.parametrize("profile", profiles.ALL, ids=lambda p: p.key)
def test_has_register_agrees_with_register(profile: DeviceProfile) -> None:
    for register in profile.registers:
        assert profile.has_register(register.name)
        assert profile.register(register.name) is register


def test_registers_for_filters_by_board() -> None:
    for register in profiles.GT3_PRO.registers_for(BoardRole.BMS1):
        assert register.board is BoardRole.BMS1


def test_choose_gatt_prefers_the_first_candidate_when_both_are_present() -> None:
    # A GT3 exposes both services. Only Nordic UART answers.
    available = {
        NORDIC_UART.write,
        NORDIC_UART.notify,
        NINEBOT_CUSTOM.write,
        NINEBOT_CUSTOM.notify,
    }
    assert choose_gatt_profile(available, profiles.GT3_PRO.transports) is NORDIC_UART


def test_choose_gatt_falls_through_to_the_second_candidate() -> None:
    available = {NINEBOT_CUSTOM.write, NINEBOT_CUSTOM.notify}
    assert choose_gatt_profile(available, profiles.GT3_PRO.transports) is NINEBOT_CUSTOM


def test_choose_gatt_skips_a_candidate_missing_its_notify_characteristic() -> None:
    # The whole point: selecting on the service alone picks a pair that accepts
    # writes and answers nothing.
    available = {NORDIC_UART.write, NINEBOT_CUSTOM.write, NINEBOT_CUSTOM.notify}
    assert choose_gatt_profile(available, profiles.GT3_PRO.transports) is NINEBOT_CUSTOM


def test_choose_gatt_is_case_insensitive() -> None:
    available = {NORDIC_UART.write.upper(), NORDIC_UART.notify.upper()}
    assert choose_gatt_profile(available, profiles.GT3_PRO.transports) is NORDIC_UART


def test_choose_gatt_raises_when_nothing_matches() -> None:
    with pytest.raises(ServiceNotFound):
        choose_gatt_profile({"0000180a-0000-1000-8000-00805f9b34fb"}, profiles.GT3_PRO.transports)
