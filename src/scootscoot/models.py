"""Result dataclasses, poll planning, and state assembly.

plan_poll and build_state are pure by design: they hold the polling logic that
matters (board ordering, and what "the board was asleep" looks like in a
result), so ScooterSession can stay glue.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from scootscoot.decode import decode
from scootscoot.profiles.types import BoardRole, DeviceProfile, Register


@dataclass(frozen=True, slots=True)
class BatteryState:
    """Readings from the battery management system."""

    soc_percent: int | None = None
    voltage: float | None = None
    current: float | None = None
    cycles: int | None = None
    capacity_full_ah: float | None = None
    capacity_remaining_ah: float | None = None
    temperatures: tuple[int | float, ...] = ()
    charge_status: int | None = None


@dataclass(frozen=True, slots=True)
class VehicleState:
    """Ride telemetry from the vehicle control unit."""

    battery_percent: int | None = None
    speed_kmh: float | None = None
    odometer_km: float | None = None
    range_km: float | None = None
    body_temp_c: float | None = None
    error_code: int | None = None
    warning_code: int | None = None


@dataclass(frozen=True, slots=True)
class MotorState:
    """Readings from the motor controller."""

    body_temp_c: float | None = None


@dataclass(frozen=True, slots=True)
class ScooterState:
    """One poll's worth of readings.

    A group is None when its board did not answer -- on a parked vehicle that
    means `vehicle` and `motor` are None while `battery` is populated. Inspect
    `responding` to tell "asleep" from "broken".
    """

    serial: str
    profile_key: str
    responding: frozenset[BoardRole]
    battery: BatteryState | None = None
    vehicle: VehicleState | None = None
    motor: MotorState | None = None


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Static identity, read once rather than every poll."""

    serial: str
    part_number: str | None = None
    vcu_firmware: str | None = None
    mcu_firmware: str | None = None
    bms_firmware: str | None = None
    ble_firmware: str | None = None
    activated_on: date | None = None


# Vendor register names are stable across models, so these maps are shared by
# every profile. A profile that omits a register simply yields None.
_BATTERY_FIELDS = {
    "rBmsSOC": "soc_percent",
    "rBMSVolt": "voltage",
    "rBMSCur": "current",
    "rBmsCycleCountLT": "cycles",
    "rBmsCapFull": "capacity_full_ah",
    "rBmsRB": "capacity_remaining_ah",
    "rBmsTemps": "temperatures",
    "rChargeStatus": "charge_status",
}

_VEHICLE_FIELDS = {
    "rBattery": "battery_percent",
    "rSpeed": "speed_kmh",
    "rMileage": "odometer_km",
    "rLeftMileage": "range_km",
    "rBodyTemp": "body_temp_c",
    "rErrorCode": "error_code",
    "rWarnCode": "warning_code",
}

_MOTOR_FIELDS = {"rMCUBodyTemp": "body_temp_c"}

_INFO_FIELDS = {
    "rPN": "part_number",
    "rCtrlV": "vcu_firmware",
    "rMCUV": "mcu_firmware",
    "rBmsV": "bms_firmware",
    "rBleV": "ble_firmware",
    "rActDate": "activated_on",
}


def plan_poll(profile: DeviceProfile) -> tuple[Register, ...]:
    """Order the poll set so boards that answer when parked come first.

    Reading the battery before the sleeping boards means a parked vehicle
    returns real data before anything has a chance to time out.
    """
    position = {name: index for index, name in enumerate(profile.poll)}
    registers = [profile.register(name) for name in profile.poll]
    return tuple(
        sorted(
            registers,
            key=lambda register: (
                0 if profile.board(register.board).awake_when_parked else 1,
                position[register.name],
            ),
        )
    )


def build_state(
    profile: DeviceProfile,
    values: Mapping[str, bytes | None],
    *,
    serial: str,
) -> ScooterState:
    """Assemble a ScooterState from raw register responses."""
    responding = _responding(profile, values)
    return ScooterState(
        serial=serial,
        profile_key=profile.key,
        responding=responding,
        battery=_group(profile, values, BoardRole.BMS1, _BATTERY_FIELDS, BatteryState, responding),
        vehicle=_group(profile, values, BoardRole.VCU, _VEHICLE_FIELDS, VehicleState, responding),
        motor=_group(profile, values, BoardRole.MCU, _MOTOR_FIELDS, MotorState, responding),
    )


def build_info(
    profile: DeviceProfile,
    values: Mapping[str, bytes | None],
    *,
    serial: str,
) -> DeviceInfo:
    """Assemble a DeviceInfo from raw identity responses."""
    return DeviceInfo(serial=serial, **_decoded(profile, values, _INFO_FIELDS))


def _responding(
    profile: DeviceProfile,
    values: Mapping[str, bytes | None],
) -> frozenset[BoardRole]:
    return frozenset(
        profile.register(name).board
        for name, raw in values.items()
        if raw is not None and profile.has_register(name)
    )


def _group[T](
    profile: DeviceProfile,
    values: Mapping[str, bytes | None],
    role: BoardRole,
    fields: Mapping[str, str],
    factory: Callable[..., T],
    responding: frozenset[BoardRole],
) -> T | None:
    if role not in responding:
        return None
    return factory(**_decoded(profile, values, fields))


def _decoded(
    profile: DeviceProfile,
    values: Mapping[str, bytes | None],
    fields: Mapping[str, str],
) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for name, field in fields.items():
        if not profile.has_register(name):
            continue
        raw = values.get(name)
        if raw is None:
            continue
        value = decode(profile.register(name), raw)
        if value is not None:
            decoded[field] = value
    return decoded
