# scootscoot

Async BLE library for Segway-Ninebot vehicles using Encryption2 (authV2).

Read-only telemetry, declarative device profiles, and a connection model built
for Home Assistant. Validated against a Segway SuperScooter GT3 Pro.

## Install

```bash
pip install scootscoot
```

## Use

```python
from scootscoot import Credentials, Scooter, profiles

scooter = Scooter(device, profiles.GT3_PRO, Credentials(password=password))

state = await scooter.poll()
print(state.battery.soc_percent if state.battery else "battery unavailable")
```

`device` is a `BLEDevice` you have already resolved. This library never scans —
under Home Assistant, discovery belongs to the Bluetooth integration.

### Identifying a vehicle

```python
info = await scooter.identify()
print(info.serial, info.part_number, info.vcu_firmware)
```

`identify()` reads static data — serial, part numbers, firmware versions,
activation date. Call it once at setup, to populate a device registry, and not
on every poll: none of it changes, and the boards holding most of it are asleep
on a parked vehicle.

### Reading more than the poll set

```python
async with scooter.session() as session:
    state = await session.poll()
    cells = await session.read("rBmsCellVolFrequence")
    raw = await session.read_raw(board=0x16, index=0x5F, length=2)
```

A session is one connection. It opens, does its work, and closes — nothing is
held between calls, because the vehicle accepts a single BLE client at a time
and holding it would lock out the phone app.

### Mapping a new model

```python
async with scooter.session() as session:
    boards = await session.probe_boards()
    registers = await session.scan_registers(0x16)
```

## Credentials

The 16-byte BLE password is yours to store; this library never touches disk.
On iOS it is the NSUserDefaults key `{SERIAL}_decrypt` in
`Library/Preferences/com.ninebot.segway.plist` — a preferences key, not a file.

A vehicle already paired with the phone app holds a stored password and will
**silently ignore** an attempt to set a new one. Supply the existing password
rather than trying to re-pair.

### Pairing an unpaired vehicle

```python
scooter = Scooter(device, profiles.GT3_PRO, Credentials())
password = await scooter.pair()  # 16 bytes — store these
```

`pair()` is the only operation that writes to the vehicle, and the only one that
can pair. `poll()`, `identify()` and `session()` never do.

- The vehicle may want a **physical button press** to confirm, and will hold the
  connection open for up to 60 s waiting for it. Have it to hand.
- **The returned password is yours to persist.** Nothing else has a copy. Pass it
  back as `Credentials(password=...)` from then on.
- **Lose it and you lose the vehicle**, as far as this library is concerned: it
  now holds a password nobody can produce, and it will ignore any attempt to set
  another. Recovery means pairing with the phone app and extracting its password
  from the key above.

Against a vehicle that already holds a password, `pair()` raises
`PairingRequired` instead of overwriting it.

## What you get back

`poll()` returns a `ScooterState`. Each group is `None` when its board did not
answer — on a parked vehicle only the BLE radio and the BMS are awake, so
`battery` is populated while `vehicle` and `motor` are `None`. Check
`state.responding` to tell "asleep" from "broken".

## Errors

Every runtime failure — anything caused by the vehicle, the radio, or the link —
derives from `ScootScootError`, so one `except` clause covers the library:

```
ScootScootError
├── ConnectionFailed        could not connect, or the link dropped mid-session
├── ServiceNotFound         no GATT service had both characteristics
├── ProtocolError           unparseable frame, or a failed MAC
├── VehicleBusy             the phone app holds the vehicle's single BLE slot
└── HandshakeFailed
    ├── AuthenticationFailed   the password is wrong or stale
    ├── PairingRequired        a password is needed and none was supplied
    └── PairingTimeout         the confirmation button was never pressed
```

bleak's `BleakError` never escapes; it is translated at the transport boundary.

Two exceptions deliberately sit outside the tree, because both are programming
errors rather than vehicle conditions and neither can happen once a connection
is open: `Credentials(password=...)` raises `ValueError` unless the password is
exactly 16 bytes, and `profiles.get()` raises `KeyError` for a profile this
release does not ship.

## Timing

A healthy poll takes a few seconds; every timeout below is a ceiling, not a
cost. Size a coordinator's timeout against the worst case: up to 20 s to
connect, then a handshake that will retry PRE_COMM ten times and AUTH three
times at 2 s each (~26 s), then the register reads at 2 s each — around 20 s for
the GT3 poll set, because the first timeout from a sleeping board skips the rest
of that board's registers. An echoed PRE_COMM restarts connect-and-handshake up
to three times with 1 s and 2 s backoff, which puts the absolute worst case a
little over two minutes before `VehicleBusy` is raised. Set a shorter timeout
deliberately if you would rather be the one who gives up first.

## Debug logging

`scootscoot` logs at DEBUG without frame bodies, on purpose: the SET_PWD frame
carries the password, and the key that unlocks it is derivable from the logged
PRE_COMM response. Raw hex is available from a separate logger that DEBUG on the
package does *not* enable:

```python
logging.getLogger("scootscoot.transport.wire").setLevel(logging.DEBUG)
```

Treat anything it produces as secret, and do not paste it into a bug report.

## Supported devices

| Profile | Model | Generation |
|---|---|---|
| `gt3_pro` | Segway SuperScooter GT3 Pro | Enc2 / gen2 |

Profiles are frozen dataclasses in `scootscoot/profiles/`. Adding a model means
adding a module and a registry line — no changes to the protocol or transport.

## Scope

Read-only telemetry. No register writes, no vehicle actions, no Encryption3.
The single exception is the SET_PWD frame sent by `pair()`, which is what
pairing is.

## Credits

Protocol documentation and the reference implementation come from the
[segway-ninebot-ble](https://codeberg.org/NootNooot/segway-ninebot-ble) and
[segway-ninebot-ble-cli](https://codeberg.org/NootNooot/segway-ninebot-ble-cli)
projects.

## License

MIT
