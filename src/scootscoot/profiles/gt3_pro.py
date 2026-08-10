"""Segway SuperScooter GT3 Pro.

Board addresses and register scales come from a full 256-address sweep and
per-register calibration against the Segway app on serial 03GGG2527C0165
(VCU 1.2.2 / MCU 2.1.1 / BMS 1.0.7 / BLE 0.2.8). Register names come from the
app's generated command table (server id 10257), by way of the device pages in
segway-ninebot-ble (Copyright 2026 NootNooot, Apache-2.0).

Where the two disagree, the hardware wins -- see rBmsCellVolFrequence.
"""

from __future__ import annotations

from scootscoot.profiles.types import (
    ENC2_GEN2,
    NINEBOT_CUSTOM,
    NORDIC_UART,
    Board,
    BoardRole,
    DeviceProfile,
    Register,
    ValueKind,
)

_BOARDS = (
    # vcu 0x16 is absent from upstream board_ids.json, whose own header notes
    # that board IDs are the one thing not present in the app config packages.
    Board(BoardRole.VCU, 0x16, awake_when_parked=False),
    Board(BoardRole.MCU, 0x02, awake_when_parked=False),
    Board(BoardRole.BMS1, 0x07, awake_when_parked=True),
    Board(BoardRole.BLE, 0x04, awake_when_parked=True),
)

_REGISTERS = (
    # --- BMS1 (0x07) -- answers with the vehicle switched off ---
    Register("rBmsSOC", BoardRole.BMS1, 0x8F, ValueKind.U16, 2, unit="%"),
    Register("rBMSVolt", BoardRole.BMS1, 0x8C, ValueKind.U16, 2, scale=0.01, unit="V"),
    Register("rBMSCur", BoardRole.BMS1, 0x8D, ValueKind.I16, 2, scale=0.01, unit="A"),
    Register("rBmsCycleCountLT", BoardRole.BMS1, 0x59, ValueKind.U16, 2),
    Register("rBmsCapFull", BoardRole.BMS1, 0x5A, ValueKind.U16, 2, scale=0.01, unit="Ah"),
    Register("rBmsRB", BoardRole.BMS1, 0x5B, ValueKind.U16, 2, scale=0.01, unit="Ah"),
    # Plain degrees Celsius -- not the -20 offset some implementations assume.
    Register("rBmsTemps", BoardRole.BMS1, 0x96, ValueKind.U16_ARRAY, 16, count=8, unit="°C"),
    Register("rChargeStatus", BoardRole.BMS1, 0x92, ValueKind.U16, 2),
    Register("rBmsVer", BoardRole.BMS1, 0x0E, ValueKind.VERSION, 2),
    Register("rBmsCapacity", BoardRole.BMS1, 0x13, ValueKind.U16, 2, scale=0.01, unit="Ah"),
    Register("rBmsManufactureDateLT", BoardRole.BMS1, 0x0A, ValueKind.DATE, 2),
    # 20 cells on a 72 V pack, summing to within 20 mV of rBMSVolt. The
    # generated command table specifies 0x1A bytes, which is wrong here.
    Register(
        "rBmsCellVolFrequence",
        BoardRole.BMS1,
        0xA0,
        ValueKind.U16_ARRAY,
        40,
        count=20,
        scale=0.001,
        unit="V",
    ),
    Register("rTimeFull", BoardRole.BMS1, 0x94, ValueKind.U16, 2, unit="min"),
    # --- VCU (0x16) -- asleep when parked ---
    Register("rSN", BoardRole.VCU, 0x10, ValueKind.ASCII, 14),
    Register("rPN", BoardRole.VCU, 0x20, ValueKind.ASCII, 16),
    Register("rCtrlV", BoardRole.VCU, 0x17, ValueKind.VERSION, 2),
    Register("rMCUV", BoardRole.VCU, 0x18, ValueKind.VERSION, 2),
    Register("rBmsV", BoardRole.VCU, 0x19, ValueKind.VERSION, 2),
    Register("rActDate", BoardRole.VCU, 0x40, ValueKind.DATE, 2),
    Register("rBattery", BoardRole.VCU, 0x55, ValueKind.U16, 2, unit="%"),
    Register("rSpeed", BoardRole.VCU, 0x57, ValueKind.U16, 2, scale=0.1, unit="km/h"),
    Register("rErrorCode", BoardRole.VCU, 0x58, ValueKind.U16, 2),
    Register("rWarnCode", BoardRole.VCU, 0x59, ValueKind.U16, 2),
    Register("rGearMode", BoardRole.VCU, 0x5A, ValueKind.U16, 2),
    # Range is 0.01 km; the odometer below is 0.1 km. They are NOT the same.
    Register("rLeftMileage", BoardRole.VCU, 0x5F, ValueKind.U16, 2, scale=0.01, unit="km"),
    Register("rMileage", BoardRole.VCU, 0x62, ValueKind.U32, 4, scale=0.1, unit="km"),
    Register("rRuntime", BoardRole.VCU, 0x64, ValueKind.U32, 4, unit="s"),
    Register("rRideTime", BoardRole.VCU, 0x66, ValueKind.U32, 4, unit="s"),
    Register("rBodyTemp", BoardRole.VCU, 0x6B, ValueKind.U16, 2, scale=0.1, unit="°C"),
    # --- MCU (0x02) -- asleep when parked ---
    Register("rMCUPN", BoardRole.MCU, 0x10, ValueKind.ASCII, 16),
    Register("rMCUBodyTemp", BoardRole.MCU, 0x3E, ValueKind.U16, 2, scale=0.1, unit="°C"),
    # --- BLE (0x04) -- always awake, and the handshake target ---
    Register("rBleV", BoardRole.BLE, 0x01, ValueKind.VERSION, 2),
)

GT3_PRO = DeviceProfile(
    key="gt3_pro",
    name="Segway SuperScooter GT3 Pro",
    hardware_id=257,
    server_id=10257,
    crypto=ENC2_GEN2,
    # Both services are present. Only Nordic UART answers.
    transports=(NORDIC_UART, NINEBOT_CUSTOM),
    boards=_BOARDS,
    registers=_REGISTERS,
    poll=(
        "rBmsSOC",
        "rBMSVolt",
        "rBMSCur",
        "rBmsCycleCountLT",
        "rBmsCapFull",
        "rBmsRB",
        "rBmsTemps",
        "rChargeStatus",
        "rBattery",
        "rSpeed",
        "rMileage",
        "rLeftMileage",
        "rBodyTemp",
        "rErrorCode",
        "rWarnCode",
        "rMCUBodyTemp",
    ),
    identity=(
        "rPN",
        "rCtrlV",
        "rMCUV",
        "rBmsV",
        "rActDate",
        "rBleV",
        "rMCUPN",
    ),
)
