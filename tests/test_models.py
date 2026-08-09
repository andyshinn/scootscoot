from __future__ import annotations

from datetime import date

from scootscoot import profiles
from scootscoot.models import build_info, build_state, plan_poll
from scootscoot.profiles.types import BoardRole

GT3 = profiles.GT3_PRO

BMS_VALUES: dict[str, bytes | None] = {
    "rBmsSOC": bytes.fromhex("3600"),
    "rBMSVolt": bytes.fromhex("971d"),
    "rBMSCur": bytes.fromhex("faff"),
    "rBmsCycleCountLT": bytes.fromhex("0200"),
    "rBmsCapFull": bytes.fromhex("b80b"),
    "rBmsRB": bytes.fromhex("5406"),
    "rBmsTemps": bytes.fromhex("22002200230023002200220023002200"),
    "rChargeStatus": bytes.fromhex("0000"),
}

VCU_VALUES: dict[str, bytes | None] = {
    "rBattery": bytes.fromhex("3600"),
    "rSpeed": bytes.fromhex("0000"),
    "rMileage": bytes.fromhex("95160000"),
    "rLeftMileage": bytes.fromhex("1c1d"),
    "rBodyTemp": bytes.fromhex("5a01"),
    "rErrorCode": bytes.fromhex("0000"),
    "rWarnCode": bytes.fromhex("0000"),
}

MCU_VALUES: dict[str, bytes | None] = {"rMCUBodyTemp": bytes.fromhex("4a01")}


def test_plan_poll_covers_every_polled_register() -> None:
    planned = plan_poll(GT3)
    assert {register.name for register in planned} == set(GT3.poll)


def test_plan_poll_puts_parked_awake_boards_first() -> None:
    planned = plan_poll(GT3)
    awake = [GT3.board(register.board).awake_when_parked for register in planned]
    # All True values come before any False value.
    assert awake == sorted(awake, reverse=True)


def test_plan_poll_starts_with_the_battery() -> None:
    assert plan_poll(GT3)[0].board is BoardRole.BMS1


def test_plan_poll_preserves_declaration_order_within_a_board() -> None:
    planned = [register.name for register in plan_poll(GT3)]
    assert planned.index("rBmsSOC") < planned.index("rBMSVolt")
    assert planned.index("rBattery") < planned.index("rSpeed")


def test_build_state_with_everything_answering() -> None:
    values = {**BMS_VALUES, **VCU_VALUES, **MCU_VALUES}
    state = build_state(GT3, values, serial="03GGG2527C0165")

    assert state.serial == "03GGG2527C0165"
    assert state.profile_key == "gt3_pro"
    assert state.responding == frozenset({BoardRole.BMS1, BoardRole.VCU, BoardRole.MCU})

    assert state.battery is not None
    assert state.battery.soc_percent == 54
    assert state.battery.voltage == 75.75
    assert state.battery.current == -0.06
    assert state.battery.capacity_full_ah == 30.0
    assert state.battery.temperatures == (34, 34, 35, 35, 34, 34, 35, 34)

    assert state.vehicle is not None
    assert state.vehicle.odometer_km == 578.1
    assert state.vehicle.range_km == 74.52
    assert state.vehicle.body_temp_c == 34.6

    assert state.motor is not None
    assert state.motor.body_temp_c == 33.0


def test_build_state_on_a_parked_vehicle() -> None:
    # Only the BLE radio and the BMS answer with the vehicle switched off.
    values: dict[str, bytes | None] = dict(BMS_VALUES)
    values.update(dict.fromkeys(VCU_VALUES))
    values.update(dict.fromkeys(MCU_VALUES))

    state = build_state(GT3, values, serial="03GGG2527C0165")

    assert state.battery is not None
    assert state.battery.soc_percent == 54
    assert state.vehicle is None
    assert state.motor is None
    assert state.responding == frozenset({BoardRole.BMS1})


def test_build_state_keeps_a_group_when_only_some_registers_answered() -> None:
    values: dict[str, bytes | None] = {**BMS_VALUES, **VCU_VALUES}
    values["rBodyTemp"] = None
    values["rSpeed"] = None

    state = build_state(GT3, values, serial="03GGG2527C0165")

    assert state.vehicle is not None
    assert state.vehicle.odometer_km == 578.1
    assert state.vehicle.body_temp_c is None
    assert state.vehicle.speed_kmh is None


def test_a_truncated_read_yields_a_none_field_not_a_missing_group() -> None:
    # The board answered, so the group exists; the short value decodes to None.
    values: dict[str, bytes | None] = {**BMS_VALUES, "rMCUBodyTemp": b"\x01"}
    state = build_state(GT3, values, serial="03GGG2527C0165")
    assert state.motor is not None
    assert state.motor.body_temp_c is None


def test_build_state_with_nothing_answering() -> None:
    values: dict[str, bytes | None] = dict.fromkeys(GT3.poll)
    state = build_state(GT3, values, serial="03GGG2527C0165")
    assert state.battery is None
    assert state.vehicle is None
    assert state.motor is None
    assert state.responding == frozenset()


def test_state_is_immutable() -> None:
    state = build_state(GT3, dict(BMS_VALUES), serial="03GGG2527C0165")
    assert isinstance(state.responding, frozenset)


def test_build_info_assembles_identity() -> None:
    values: dict[str, bytes | None] = {
        "rPN": b"Z03QB4G25FJ40046",
        "rCtrlV": bytes.fromhex("2201"),
        "rMCUV": bytes.fromhex("1102"),
        "rBmsV": bytes.fromhex("0701"),
        "rBleV": bytes.fromhex("2800"),
        "rActDate": bytes.fromhex("3a33"),
        "rMCUPN": b"Z07ABTW25CUH0991",
    }
    info = build_info(GT3, values, serial="03GGG2527C0165")

    assert info.serial == "03GGG2527C0165"
    assert info.part_number == "Z03QB4G25FJ40046"
    assert info.vcu_firmware == "1.2.2"
    assert info.mcu_firmware == "2.1.1"
    assert info.bms_firmware == "1.0.7"
    assert info.ble_firmware == "0.2.8"
    assert info.activated_on == date(2025, 9, 26)


def test_build_info_tolerates_a_sleeping_vcu() -> None:
    values: dict[str, bytes | None] = {
        "rPN": None,
        "rCtrlV": None,
        "rMCUV": None,
        "rBmsV": None,
        "rActDate": None,
        "rBleV": bytes.fromhex("2800"),
        "rMCUPN": None,
    }
    info = build_info(GT3, values, serial="03GGG2527C0165")
    assert info.serial == "03GGG2527C0165"
    assert info.ble_firmware == "0.2.8"
    assert info.part_number is None
    assert info.vcu_firmware is None
