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
on every poll: none of it changes. On a parked GT3 everything but the motor
controller's part number is readable; that one needs the vehicle switched on.

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

To check a profile against real hardware, `scripts/probe_registers.py` reads
every register in it and records every frame that comes back, including the
ones `read_raw` discards, and why. Capture once with the vehicle off and once
with it on:

```bash
uv run python scripts/probe_registers.py AA:BB:CC:DD:EE:FF --note off --out off.json
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
answer. A switched-off GT3 still answers from the BMS and the VCU, so `battery`
and `vehicle` are populated while `motor` is `None` — which makes
`BoardRole.MCU in state.responding` the test for "switched on". Check
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
times at 2 s each (~26 s), then the register reads at 2 s each. A read that gets
no answer is retried once, because awake boards drop the odd reply; a sleeping
board's remaining registers are then skipped. On a parked GT3 that costs 4 s for
the MCU, and a link that goes silent mid-poll costs about 64 s for the poll set.
An echoed PRE_COMM restarts connect-and-handshake up to three times with 1 s and
2 s backoff. That is a little over two minutes when it ends in `VehicleBusy`,
and around three and a half when the last attempt connects and the link then
goes silent. Set a shorter timeout
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

## Attribution

scootscoot is a derivative work of two Apache-2.0 projects by NootNooot,
Copyright 2026 NootNooot:

- [segway-ninebot-ble](https://codeberg.org/NootNooot/segway-ninebot-ble) —
  the protocol documentation. Framing, the Encryption2 handshake, board ids,
  and the per-device command tables the register names come from.
- [segway-ninebot-ble-cli](https://codeberg.org/NootNooot/segway-ninebot-ble-cli) —
  the reference implementation. `scootscoot/crypto.py` is a port of its
  `nb_crypto.py`, which was itself verified against a Ghidra decompilation of
  `libnbcrypto.so`.

What this package changed: the CLI's I/O-free modules were rewritten as an
async library with a session-scoped connection model, register decoding moved
behind declarative per-model profiles, `cryptography` replaced `pycryptodome`
for the single-block AES call, and the CLI surface was dropped. The protocol
and crypto behavior itself is unchanged — the vehicle would reject it otherwise.

Neither upstream project nor this one is affiliated with, authorized by, or
endorsed by Segway Inc. or Ninebot. "Segway" and "Ninebot" are trademarks of
their respective owners, used here only to identify the hardware this library
talks to.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Upstream picked Apache-2.0 for the patent grant, the liability terms, and the
explicit trademark clause, all of which matter for code that talks to a
vehicle. This package stays on it: it carries enough of that work that keeping
the license and the attribution chain together is the honest arrangement.
