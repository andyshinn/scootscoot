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
from scootscoot import Credentials, Scooter
from scootscoot import profiles

scooter = Scooter(device, profiles.GT3_PRO, Credentials(password=password))

state = await scooter.poll()
print(state.battery.soc_percent if state.battery else "battery unavailable")
```

`device` is a `BLEDevice` you have already resolved. This library never scans —
under Home Assistant, discovery belongs to the Bluetooth integration.

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

## What you get back

`poll()` returns a `ScooterState`. Each group is `None` when its board did not
answer — on a parked vehicle only the BLE radio and the BMS are awake, so
`battery` is populated while `vehicle` and `motor` are `None`. Check
`state.responding` to tell "asleep" from "broken".

## Supported devices

| Profile | Model | Generation |
|---|---|---|
| `gt3_pro` | Segway SuperScooter GT3 Pro | Enc2 / gen2 |

Profiles are frozen dataclasses in `scootscoot/profiles/`. Adding a model means
adding a module and a registry line — no changes to the protocol or transport.

## Scope

Read-only. No register writes, no vehicle actions, no Encryption3.

## Credits

Protocol documentation and the reference implementation come from the
[segway-ninebot-ble](https://codeberg.org/NootNooot/segway-ninebot-ble) and
[segway-ninebot-ble-cli](https://codeberg.org/NootNooot/segway-ninebot-ble-cli)
projects.

## License

MIT
