# scootscoot — Segway-Ninebot BLE library

**Date:** 2026-08-09
**Status:** Approved for planning

An async Python library for talking to Segway-Ninebot vehicles over BLE using
Encryption2 (authV2). Published to PyPI. The first consumer is a Home Assistant
integration, built separately and later; HA's constraints therefore shape the
API from day one. Validation hardware is a Segway SuperScooter GT3 Pro, but GT3
is the first *profile*, not the shape of the API.

## Reference material

Authoritative sources, already read. Do not re-derive from scratch.

| Source | Role |
|---|---|
| `~/GitHub/andyshinn/scooter-query/segway-ninebot-ble/` | Protocol documentation (MkDocs). Framing, Enc2 crypto, auth phases, per-device command tables, `board_ids.json`. |
| `~/GitHub/andyshinn/scooter-query/segway-ninebot-ble-cli/` | Reference implementation. `nb_crypto.py` and `nb_protocol.py` are clean and I/O-free. `segway_ble_client.py` is CLI-shaped — reference only, not a base. |
| `~/GitHub/andyshinn/scooter-query/README.md` | Verified GT3 Pro board map, register map with calibrated scales, known-unknowns. The GT3 profile source. |

---

## 1. Scope

### In scope for v0.1

- Enc2/authV2 protocol core: crypto, framing, frame reassembly, 3-phase handshake.
- Declarative device profiles; GT3 Pro as the first.
- Read-only telemetry returning typed dataclasses.
- A raw escape hatch — register reads, board probing, register scanning — so
  others can map new models with this package rather than around it.
- Home Assistant-compatible connection handling.

### Explicitly out of scope for v0.1

- Register writes and typed settings (`setLedMode`, `setMaxSpeed`, …).
- Vehicle actions (`openAcc`, `closeAcc`, trunk) and the `$ident` credential
  they require.
- Encryption3 / V3Auth.
- Any CLI. Any scanning. Any file I/O.

Writes are deferred deliberately: `writeNR` is unacknowledged, and a wrong
register on a model nobody has validated is a real-world side effect on a
vehicle. The profile schema does not preclude adding them later.

---

## 2. Constraints

### Home Assistant

Per `developers.home-assistant.io/docs/bluetooth`:

- Never construct a `BleakScanner`. Accept an already-resolved `BLEDevice`.
- Connect via `bleak_retry_connector.establish_connection`, fresh client per
  connection, minimum 10 s connect timeout.
- No `print()`, no `sys.exit`, no `argparse`. `logging` only.
- No file I/O for credentials or session state — the caller owns persistence.
- Return dataclasses, not formatted strings.
- Ship type hints and a `py.typed` marker.

### Packaging

- Version derived solely from the git tag. No hand-edited version strings.
- GitHub Actions: build on push, publish to PyPI on tag via Trusted Publishing
  (OIDC). No API tokens in secrets.

---

## 3. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| v0.1 scope | Read-only + raw escape hatch | Smallest surface that unblocks HA; escape hatch serves the device-agnostic goal. |
| Connection lifetime | On-demand only; never held between polls | The vehicle accepts one BLE client at a time. Holding it starves the phone app. At a 10–20 min poll interval the handshake cost is irrelevant. |
| Session handle | Public | Callers batching many reads under one auth need it; a 256-board sweep must not be 256 handshakes. |
| Profile selection | Explicit only | Deterministic. No silent mis-identification. A GT3 advertises only its bare serial, so any matcher would be prefix-heuristic. The registry gives consumers a list to render. |
| Crypto backend | `cryptography` | Already an HA core dependency, so the integration adds no new wheel. Only one primitive is needed: single-block AES-128-ECB encrypt. |
| Python floor | 3.12 | |
| Build backend | hatchling + hatch-vcs | Version from git tag; clean `py.typed` handling. |
| Testing | Unit tests on pure functions only | See §10 — the handshake is designed as a pure state machine so this strategy still covers it. |
| Connection seam | `FrameChannel` protocol internally; `BLEDevice` is the public path | HA hands over a `BLEDevice`, never a connection. Proxy routing already rides in `BLEDevice.details`, so client injection buys nothing for ESPHome proxies. The seam keeps bleak in one module and leaves injection a later constructor overload, not a refactor. |
| License | MIT | |

---

## 4. Architecture

Pure core, thin async shell. Crypto, framing, reassembly, the handshake state
machine, value decoding, and profiles are all I/O-free and importable without a
BLE stack present. Only three modules touch bleak.

```
src/scootscoot/
  __init__.py        public exports only
  exceptions.py      error hierarchy
  crypto.py          NbCrypto, derive_key, generate_password        (pure)
  framing.py         build_frame, parse_frame, FrameAssembler       (pure)
  handshake.py       PRE_COMM → SET_PWD → AUTH state machine        (pure)
  decode.py          raw bytes → typed values, per ValueKind        (pure)
  models.py          ScooterState and friends                       (pure)
  channel.py         FrameChannel protocol definition               (pure)
  transport.py       bleak GATT I/O: notify reassembly, fragmented write
  session.py         ScooterSession — authenticated connection
  client.py          Scooter — public entry point
  profiles/
    types.py         frozen dataclasses
    registry.py      ALL, get(key)
    gt3_pro.py       first profile
  py.typed
```

Dependency direction is strictly downward. `session.py` depends on the
`FrameChannel` protocol, not on `transport.py`; `transport.py` is one
implementation of it.

---

## 5. Device profiles

Frozen dataclasses in modules — not JSON, not TOML, not dicts. They are
type-checked, covered by `py.typed`, need no runtime parsing, and adding a model
means adding one file plus a registry entry. The protocol and transport layers
never name a vehicle.

```python
class BoardRole(StrEnum):
    VCU = "vcu"; MCU = "mcu"; BMS1 = "bms1"; BMS2 = "bms2"
    BLE = "ble"; DIS = "dis"; ECU = "ecu"

class ValueKind(StrEnum):
    U16 = "u16"; I16 = "i16"; U32 = "u32"; I32 = "i32"
    ASCII = "ascii"; RAW = "raw"
    VERSION = "version"          # packed firmware version, e.g. 290 → 1.2.2
    DATE = "date"                # (yr-2000)<<9 | mon<<5 | day
    U16_ARRAY = "u16_array"

@dataclass(frozen=True, slots=True)
class Board:
    role: BoardRole
    address: int
    awake_when_parked: bool

@dataclass(frozen=True, slots=True)
class Register:
    name: str                    # "rLeftMileage"
    board: BoardRole
    index: int                   # 0x5F
    kind: ValueKind
    length: int                  # bytes requested on the wire
    scale: float = 1.0
    unit: str | None = None
    count: int = 1               # elements, for U16_ARRAY

@dataclass(frozen=True, slots=True)
class CryptoSuite:
    label: str                   # "enc2-gen2"
    sync2: int                   # 0xA5 gen2, 0xB5 gen3
    ecb_input: bytes             # FW_DATA (gen2) or 16 zero bytes (gen3)
    initial_key2: bytes | None   # FW_DATA (gen2) or None (gen3)

@dataclass(frozen=True, slots=True)
class GattProfile:
    label: str                   # "Nordic UART"
    service: str
    write: str
    notify: str

@dataclass(frozen=True)
class DeviceProfile:
    key: str                     # "gt3_pro"
    name: str                    # "Segway SuperScooter GT3 Pro"
    hardware_id: int | None      # 257
    server_id: int | None        # 10257
    crypto: CryptoSuite
    transports: tuple[GattProfile, ...]   # preference order
    boards: tuple[Board, ...]
    registers: tuple[Register, ...]
    poll: tuple[str, ...]        # register names in the default poll set
    identity: tuple[str, ...]    # register names read by identify()

    def board(self, role: BoardRole) -> Board: ...
    def register(self, name: str) -> Register: ...
```

Module constants: `ENC2_GEN2`, `ENC2_GEN3`, `NORDIC_UART`, `NINEBOT_CUSTOM`.

Lookup helpers are backed by dicts built once at construction. `DeviceProfile`
omits `slots=True` for that reason; every nested dataclass keeps it.

### 5.1 GT3 Pro profile

Board map, from a full 256-address sweep on real hardware:

| Role | Address | Awake when parked |
|---|---|---|
| VCU | `0x16` | no |
| MCU | `0x02` | no |
| BMS1 | `0x07` | **yes** |
| BLE | `0x04` | **yes** |

`0x16` for the VCU is absent from upstream `board_ids.json`, which documents
board IDs as the one thing not present in the app's config packages. No DIS
board, no BMS2, nothing at `0x09` or `0x23`.

Crypto suite `ENC2_GEN2`; transports `(NORDIC_UART, NINEBOT_CUSTOM)` — the GT3
exposes both services and only Nordic UART answers.

Default poll set — 16 reads, ordered BMS1 first (awake when parked), then VCU,
then MCU:

| Board | Register | Index | Kind | Scale / unit |
|---|---|---|---|---|
| BMS1 | `rBmsSOC` | `0x8F` | U16 | % |
| BMS1 | `rBMSVolt` | `0x8C` | U16 | 0.01 V |
| BMS1 | `rBMSCur` | `0x8D` | I16 | 0.01 A (signed; regen negative) |
| BMS1 | `rBmsCycleCountLT` | `0x59` | U16 | — |
| BMS1 | `rBmsCapFull` | `0x5A` | U16 | 10 mAh |
| BMS1 | `rBmsRB` | `0x5B` | U16 | 10 mAh |
| BMS1 | `rBmsTemps` | `0x96` | U16_ARRAY ×8, len 16 | °C direct |
| BMS1 | `rChargeStatus` | `0x92` | U16 | — |
| VCU | `rBattery` | `0x55` | U16 | % |
| VCU | `rSpeed` | `0x57` | U16 | 0.1 km/h |
| VCU | `rMileage` | `0x62` | U32 | **0.1 km** |
| VCU | `rLeftMileage` | `0x5F` | U16 | **0.01 km** |
| VCU | `rBodyTemp` | `0x6B` | U16 | 0.1 °C |
| VCU | `rErrorCode` | `0x58` | U16 | — |
| VCU | `rWarnCode` | `0x59` | U16 | — |
| MCU | `rMCUBodyTemp` | `0x3E` | U16 | 0.1 °C |

Range and odometer use different scales. Conflating them is what produced
"745.2 km range" and a "5.781 km odometer" during development; the decode tests
in §10 pin both.

Identity set, read by `identify()` rather than every poll: `rPN` (VCU `0x20`,
16B ASCII), `rCtrlV` (`0x17`), `rMCUV` (`0x18`), `rBmsV` (`0x19`), `rActDate`
(`0x40`, DATE), `rBleV` (BLE `0x01`), `rMCUPN` (MCU `0x10`, 16B ASCII).

Declared but outside both sets, reachable via `session.read()`:
`rBmsCellVolFrequence` (BMS1 `0xA0`, U16_ARRAY ×**20**, length 40, mV) — 20
cells on a 72 V pack, not the `0x1A` the generated command table specifies;
`rGearMode` (`0x5A`), `rRuntime` (`0x64`, U32 s), `rRideTime` (`0x66`, U32 s),
`rBmsCapacity` (`0x13`), `rBmsManufactureDateLT` (`0x0A`), `rTimeFull` (`0x94`).

---

## 6. Protocol core

### 6.1 Crypto

Port `nb_crypto.py` nearly verbatim: `derive_key` (`SHA-1(key1_pad16 ‖
key2_pad16)[0:16]`), 13-byte nonce, `A_i` / `B_0` block construction, CBC-MAC,
CTR XOR, SN and non-SN paths, `JavaRandom`, `generate_password`. `NbCrypto`
remains a stateful context (keys, auth param, counter) that performs no I/O.

The only substantive change is the AES call: `cryptography`'s single-block ECB
encryptor replaces `Crypto.Cipher.AES`.

**Replay handling.** The reference disables the replay check entirely. Track the
*received* counter separately from the send counter, log a warning on a
non-increasing value, and accept it by default (`strict_replay=False`).
Enforcing strictly against hardware we cannot test broadly risks a library that
silently stops working on models we have never seen.

### 6.2 Framing

`build_frame(target, cmd, index, data, sync2)` produces
`[0x5A, sync2, LEN, 0x3E, target, cmd, index, *data]`.

`parse_frame` reads the response layout
`[0x5A, sync2, LEN, source_board, 0x3E, cmd, index, *data]`, accepting either
sync byte and rejecting frames whose `BT_ID` is not `0x3E`.

`FrameAssembler` consumes notification chunks and yields complete frames: scan
for `0x5A` followed by a valid sync byte, then accumulate `LEN + 13` bytes.
Pure bytes-in / frames-out.

### 6.3 Handshake state machine

Pure and I/O-free. `feed` takes *encrypted* bytes and decrypts internally, so
the driver loop only moves bytes and never touches crypto.

```python
hs = Handshake(device_name=..., suite=profile.crypto,
               password=creds.password, allow_pairing=False)

step = hs.start()            # Send(payload, timeout, retries)
step = hs.feed(raw_frame)    # Send | AwaitConfirmation | Established
```

`Established` carries the live `NbCrypto`, the serial, the negotiated sync byte,
the password, and whether pairing occurred (so the caller knows to persist a new
password).

Key evolution across phases:

| Phase | key1 | key2 | Counter mode |
|---|---|---|---|
| PRE_COMM | BLE device name | suite `initial_key2` | non-SN (0) |
| SET_PWD | BLE device name | auth param | SN |
| AUTH / COMM | session password | auth param | SN |

**Sync byte is read, not assumed.** PRE_COMM must go out under the profile's
declared suite — the ECB input and initial key2 are suite-dependent and
encryption necessarily precedes any response. The vehicle's reply header carries
*its* sync byte, and every subsequent frame adopts it. If the PRE_COMM decrypt
fails its non-SN checksum, retry once under the other Enc2 suite before giving
up, so a profile carrying the wrong generation self-corrects rather than timing
out.

**Stored-password path.** A non-zero `INDEX` in the PRE_COMM response means the
vehicle holds a password. SET_PWD is then skipped entirely and AUTH is sent
under `SHA-1(stored_password ‖ auth_param)`. No special counter handling is
needed: `start_sn()` sets 1 and the first encrypt increments to 2, so AUTH lands
on counter 2 whether or not SET_PWD ran — which is what the vehicle expects.

**Echo detection.** A response byte-identical to the request means the vehicle
echoed rather than answered. This is a distinct, retryable outcome, not a
handshake failure.

**Pairing** (SET_PWD) is implemented but gated behind `allow_pairing=True`,
since it can block on a physical button press for up to 60 s.

Retry budgets follow the documented app behaviour and are carried on each `Send`
step so the driver loop stays dumb: PRE_COMM 10 attempts at 2 s; SET_PWD
retried every 2 s within a 60 s window; AUTH 3 attempts.

---

## 7. Transport and connection

### 7.1 The seam

```python
class FrameChannel(Protocol):
    async def send(self, data: bytes) -> None: ...
    async def recv(self, timeout: float) -> bytes: ...
    def drain(self) -> None: ...
```

`ScooterSession` is written against this protocol. `BleTransport` is one
implementation; a test double is another. bleak is confined to `transport.py`
and `client.py`.

### 7.2 BleTransport

Wraps a connected client and a chosen `GattProfile`. Subscribes to notify, feeds
chunks into `FrameAssembler`, queues complete frames. Writes fragment at
`max(20, mtu - 3)` bytes with a ~10 ms inter-fragment delay — fragmentation is
bidirectional, and an oversized single write is silently truncated by the BLE
stack, after which the vehicle simply never answers.

**Service selection** walks `profile.transports` in order and requires that
**both the write and the notify characteristic UUIDs exist** in the connected
GATT table — not that the service exists. The GT3 exposes both Nordic UART and
Ninebot Custom, and the Ninebot service has *more* characteristics while being
the dead one; selecting on the service alone picks a pair that accepts writes
and answers nothing.

After subscribing, drain for ~250 ms before starting the handshake to discard
notifications cached from a previous session.

### 7.3 Connection

Never constructs a scanner. Takes a resolved `BLEDevice` and connects through
`bleak_retry_connector.establish_connection` with `BleakClientWithServiceCache`,
a fresh client per connection, and a 20 s default timeout.

Key material — the BLE device name — is taken from `device.name`, falling back
to a GATT `0x2A00` read, with an explicit constructor override. It must be the
exact advertised name; on a GT3 that is the bare serial, with no vendor token.

On an echoed PRE_COMM, disconnect and retry with escalating delays (1 s, 2 s) up
to 3 attempts before raising `VehicleBusy`.

---

## 8. Public API

```python
from bleak.backends.device import BLEDevice
from scootscoot import Scooter, Credentials, profiles

scooter = Scooter(
    device,                       # BLEDevice, resolved by the caller
    profiles.GT3_PRO,
    Credentials(password=pw),     # 16 raw bytes; caller owns persistence
    device_name=None,             # optional override of BLE name key material
    allow_pairing=False,
    connect_timeout=20.0,
)

state = await scooter.poll()      # opens, handshakes, reads, closes
info  = await scooter.identify()  # static identity; call once at setup

async with scooter.session() as s:        # one connection, many operations
    state = await s.poll()
    volts = await s.read("rBMSVolt")      # profile register by name
    raw   = await s.read_raw(board=0x16, index=0x5F, length=2)
    live  = await s.probe_boards()        # addresses that answer
    dump  = await s.scan_registers(0x16)  # {index: bytes}
```

Both `scooter.poll()` and `scooter.identify()` open their own connection and
close it; each is exactly `async with self.session() as s: return await s.<op>()`.
No connection outlives the operation that opened it.

Return types: `read(name)` returns the register's decoded value — `int`,
`float`, `str`, `tuple[float, ...]`, `date`, or `bytes` per its `ValueKind` —
or `None` on timeout. `read_raw` returns `bytes | None`. `probe_boards`
defaults to all 256 addresses and returns the responding ones;
`scan_registers` walks all 256 indices on one board. Both accept an explicit
range and a per-probe timeout.

`Credentials` is a frozen dataclass holding the 16-byte password — on iOS an
**NSUserDefaults key** `{SERIAL}_decrypt` in `com.ninebot.segway.plist`, not a
file. The library never reads or writes it to disk.

`read_raw` and `scan_registers` verify that the responding `board_id` matches
the requested target and discard mismatches. Without that, short timeouts let a
slow board's reply land on the next probe and invent boards that do not exist.

---

## 9. Data model and errors

```python
@dataclass(frozen=True, slots=True)
class ScooterState:
    serial: str
    profile_key: str
    responding: frozenset[BoardRole]
    battery: BatteryState | None
    vehicle: VehicleState | None
    motor: MotorState | None
```

A group is `None` when its board did not answer. A field inside a group is
`None` when that specific register did not. A parked GT3 therefore returns a
full `battery` with `vehicle is None`, and `responding` makes "asleep"
distinguishable from "broken" without the consumer guessing.

The poll orders `awake_when_parked` boards first. When a board that may sleep
fails its first read, the remaining registers on that board are skipped rather
than paying a timeout each.

Both halves of that behaviour are **pure functions**, deliberately kept out of
the async session so they fall under the test strategy in §10:
`plan_poll(profile) -> tuple[Register, ...]` produces the ordering, and
`build_state(profile, values) -> ScooterState` assembles the result from a
`{register_name: bytes | None}` mapping. `ScooterSession` is then thin glue that
walks the plan, performs I/O, and hands the collected values to `build_state`.

`BatteryState`: `soc_percent`, `voltage`, `current`, `cycles`,
`capacity_full_ah`, `capacity_remaining_ah`, `temperatures: tuple[float, ...]`,
`charge_status`.
`VehicleState`: `battery_percent`, `speed_kmh`, `odometer_km`, `range_km`,
`body_temp_c`, `error_code`, `warning_code`.
`MotorState`: `body_temp_c`.
`DeviceInfo` (from `identify()`): `serial`, `part_number`, `vcu_firmware`,
`mcu_firmware`, `bms_firmware`, `ble_firmware`, `activated_on`,
`motor_part_number`.

```
ScootScootError
├── ConnectionFailed        establish_connection gave up
├── ServiceNotFound         no service with both characteristics present
├── HandshakeFailed
│   ├── AuthenticationFailed   AUTH rejected — stale or wrong password
│   ├── PairingRequired        no stored password and allow_pairing=False
│   └── PairingTimeout         confirmation button never pressed
├── ProtocolError           unparseable frame or MAC mismatch
└── VehicleBusy             echo detected, or the phone app holds the slot
```

This maps cleanly onto HA: `ConnectionFailed` and `VehicleBusy` are transient
`UpdateFailed`; `AuthenticationFailed` is `ConfigEntryAuthFailed` and prompts
re-entry of the password.

---

## 10. Testing

pytest, unit tests on pure functions only. The handshake is designed as a pure
state machine, and poll ordering and state assembly are extracted as pure
functions (§9), precisely so this strategy still covers the logic that matters.
What remains untested is `transport.py`, `session.py` and `client.py` — GATT
plumbing, a walk over a precomputed plan, and connection setup. Those are
verified by ruff and mypy strict, and exercised manually against the GT3.

- **Crypto** — SN and non-SN round-trips under both suites; gen2 and gen3
  ciphertext proven distinct for identical plaintext; `JavaRandom` against known
  Java outputs; `derive_key` vectors.
- **Framing** — build/parse round-trip; `FrameAssembler` against a frame split
  across chunks, a garbage prefix, two back-to-back frames, and a truncated
  tail.
- **Handshake** — drive the state machine with canned frames. The vehicle side
  of a frame is `NbCrypto` run in the other direction, so test helpers
  synthesise responses using the same pure code. Cases: fresh pairing;
  stored-password path with SET_PWD skipped and AUTH on counter 2; echoed
  PRE_COMM; wrong-suite retry and recovery; AUTH rejected; pairing required but
  disallowed.
- **Decode** — one case per `ValueKind`, seeded with calibrated readings from
  real hardware: `7452 → 74.52 km` range against `5781 → 578.1 km` odometer
  (the two scales that must not be conflated); `13114 → 2025-09-26`; `290 →
  1.2.2`; twenty cell voltages summing to 75.76 V against `0x8C`'s 75.75 V.
- **State assembly** — `plan_poll` orders awake-when-parked boards first;
  `build_state` on a full result set, on a parked-vehicle set (BMS answered,
  VCU and MCU silent → `vehicle is None`, `motor is None`, `responding` holds
  only BMS1), and on a set with individual registers missing inside a group
  that did answer.
- **Profiles** — registry integrity: every name in `poll` and `identity`
  resolves, every register's board exists in `boards`, no duplicate register
  names, no duplicate board addresses or roles.

---

## 11. Packaging and CI

`src/` layout, hatchling + hatch-vcs so the version derives solely from the git
tag, `py.typed` shipped, `requires-python = ">=3.12"`.

Runtime dependencies: `bleak`, `bleak-retry-connector`, `cryptography`.
Development: ruff (lint + format), mypy strict, pytest.

- **`ci.yml`** on push and pull request — ruff, mypy, pytest on 3.12 and 3.13,
  then build sdist and wheel and run `twine check`, so packaging breakage
  surfaces before a tag rather than during a release.
- **`publish.yml`** on `v*` tags — build, then `pypa/gh-action-pypi-publish`
  with `permissions: id-token: write` and a `pypi` environment. Trusted
  Publishing; no API token in secrets. Requires a one-time publisher
  registration on PyPI naming the repository and workflow filename.

---

## 12. Protocol gotchas and where each is handled

| Gotcha | Handled in |
|---|---|
| Vehicle generates its own sync byte in PRE_COMM | §6.3 — adopted from the response; wrong-suite retry |
| Both Nordic UART and Ninebot Custom present, one dead | §7.2 — select on write **and** notify characteristics |
| Enc2 vehicles with a stored password silently drop SET_PWD | §6.3 — stored-password path skips SET_PWD; password is a constructor argument, never read from disk |
| Board availability split by power state | §5, §9 — `awake_when_parked`, optional state groups, early skip |
| One BLE client at a time; conflicts with the phone app | §3, §7.3, §9 — on-demand connections only; `VehicleBusy` |
| Every connection costs a full handshake | §5.1 — 16-read poll set; §8 — session batches reads |
| Outgoing frames must be fragmented too | §7.2 — `mtu - 3` chunking |
| Slow board's reply lands on the next probe | §8 — `board_id` verification on raw reads |

---

## 13. Future work

Not in v0.1, but the design leaves room:

- **Writes and typed settings.** `Register` already carries everything needed;
  add an ops field and write builders.
- **Vehicle actions.** Need the `$ident` token as a second credential.
- **Encryption3 / V3Auth.** A new `CryptoSuite` plus a second handshake state
  machine. Transport, profiles, session, and data model are unaffected.
- **Client injection.** `Scooter.from_client(...)` over the existing
  `FrameChannel` seam, with the rule that whoever opens a connection closes it.
- **More profiles.** One module plus a registry entry each.
