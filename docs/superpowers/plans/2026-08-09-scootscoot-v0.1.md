# scootscoot v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a read-only, Home Assistant-compatible async Python library on PyPI for reading telemetry from Segway-Ninebot vehicles over BLE using Encryption2 (authV2), with the Segway SuperScooter GT3 Pro as the first device profile.

**Architecture:** Pure core, thin async shell. Crypto, framing, frame reassembly, the handshake state machine, value decoding, poll planning, and state assembly are all I/O-free and unit-tested. Only `transport.py`, `session.py`, and `client.py` touch bleak. Vehicles are described by frozen-dataclass profile modules; the protocol layers never name a model.

**Tech Stack:** Python 3.12+, `bleak`, `bleak-retry-connector`, `cryptography`, hatchling + hatch-vcs, pytest, ruff, mypy strict, uv.

**Spec:** `docs/superpowers/specs/2026-08-09-scootscoot-ble-library-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- `requires-python = ">=3.12"`. Package name `scootscoot`. License MIT.
- Runtime dependencies are exactly `bleak`, `bleak-retry-connector`, `cryptography`. Nothing else.
- Version derives solely from the git tag via hatch-vcs. No hand-edited version strings anywhere.
- **No `print()`, no `sys.exit`, no `argparse`, no file I/O** anywhere in `src/`. Logging only, via `logging.getLogger(__name__)`.
- Never construct a `BleakScanner`. Accept a resolved `BLEDevice`.
- Connect only via `bleak_retry_connector.establish_connection`, fresh client per connection, connect timeout ≥ 10 s (default 20 s).
- All public functions return dataclasses or scalars, never formatted strings.
- `py.typed` ships. `mypy --strict` passes over `src` and `tests`.
- `from __future__ import annotations` at the top of every module in `src/`.
- v0.1 is **read-only**: no register writes, no vehicle actions, no `$ident`, no Encryption3, no CLI, no scanning.

## Dev commands

```bash
uv sync                 # install package + dev group
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Packaging, deps, ruff/mypy/pytest config |
| `LICENSE`, `.gitignore`, `README.md` | Repo hygiene and docs |
| `src/scootscoot/__init__.py` | Public exports only |
| `src/scootscoot/exceptions.py` | Error hierarchy |
| `src/scootscoot/crypto.py` | Enc2 primitives + `NbCrypto` (pure) |
| `src/scootscoot/framing.py` | Frame build/parse + `FrameAssembler` (pure) |
| `src/scootscoot/profiles/types.py` | Frozen profile dataclasses + `choose_gatt_profile` (pure) |
| `src/scootscoot/profiles/gt3_pro.py` | GT3 Pro profile data |
| `src/scootscoot/profiles/registry.py` | `ALL`, `get(key)` |
| `src/scootscoot/decode.py` | Raw bytes → typed values (pure) |
| `src/scootscoot/models.py` | Result dataclasses + `plan_poll` + `build_state` (pure) |
| `src/scootscoot/handshake.py` | PRE_COMM→SET_PWD→AUTH state machine (pure) |
| `src/scootscoot/channel.py` | `FrameChannel` protocol |
| `src/scootscoot/transport.py` | bleak GATT I/O |
| `src/scootscoot/session.py` | `ScooterSession` — walks a plan, does I/O |
| `src/scootscoot/client.py` | `Scooter` — public entry point |
| `.github/workflows/ci.yml` | Lint, typecheck, test, build |
| `.github/workflows/publish.yml` | PyPI Trusted Publishing on tag |

Tasks 1–7 are pure and fully tested. Tasks 8–10 are the bleak-touching glue, verified by ruff + mypy. Task 11 is release infrastructure.

---

### Task 1: Project scaffold, packaging, and exceptions

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `.gitignore`, `README.md`
- Create: `src/scootscoot/__init__.py`, `src/scootscoot/py.typed`, `src/scootscoot/exceptions.py`
- Test: `tests/test_exceptions.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `scootscoot.__version__: str`. Exception classes `ScootScootError`, `ConnectionFailed`, `ServiceNotFound`, `HandshakeFailed`, `AuthenticationFailed`, `PairingRequired`, `PairingTimeout`, `ProtocolError`, `VehicleBusy`, `UnknownBoard`, `UnknownRegister` — all importable from `scootscoot.exceptions` and from `scootscoot`.

> Note: `UnknownBoard` and `UnknownRegister` are additions to the spec's §9 tree. They signal programming errors (a profile lookup for something not declared), not runtime vehicle conditions, but they inherit from `ScootScootError` so a consumer can catch everything with one class.

- [ ] **Step 1: Create the repo skeleton and packaging**

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "scootscoot"
description = "Async BLE library for Segway-Ninebot vehicles (Encryption2 / authV2)"
readme = "README.md"
license = "MIT"
license-files = ["LICENSE"]
requires-python = ">=3.12"
dynamic = ["version"]
authors = [{ name = "Andy Shinn", email = "andy.shinn@gmail.com" }]
keywords = ["ble", "bluetooth", "segway", "ninebot", "scooter", "home-assistant"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Framework :: AsyncIO",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Home Automation",
    "Typing :: Typed",
]
dependencies = [
    "bleak>=0.22",
    "bleak-retry-connector>=3.5",
    "cryptography>=42",
]

[project.urls]
Homepage = "https://github.com/andyshinn/scootscoot"
Issues = "https://github.com/andyshinn/scootscoot/issues"

[dependency-groups]
dev = ["pytest>=8", "mypy>=1.11", "ruff>=0.6"]

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.targets.wheel]
packages = ["src/scootscoot"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "A", "C4", "RUF"]
# N815: vendor register names such as rBmsSOC are mixed-case by protocol definition.
ignore = ["N815"]

[tool.mypy]
python_version = "3.12"
strict = true
files = ["src", "tests"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

`.gitignore`:

```
__pycache__/
*.py[cod]
.venv/
dist/
build/
*.egg-info/
.mypy_cache/
.ruff_cache/
.pytest_cache/
```

`README.md` — a stub for now; Task 11 expands it:

```markdown
# scootscoot

Async BLE library for Segway-Ninebot vehicles using Encryption2 (authV2).

Read-only telemetry, device-agnostic profiles, built for Home Assistant.
```

`LICENSE` — the standard MIT text, copyright `2026 Andy Shinn`.

`src/scootscoot/py.typed` — empty file.

- [ ] **Step 2: Write the failing test**

`tests/test_exceptions.py`:

```python
from __future__ import annotations

import pytest

import scootscoot
from scootscoot import exceptions as exc


def test_version_is_a_non_empty_string() -> None:
    assert isinstance(scootscoot.__version__, str)
    assert scootscoot.__version__


@pytest.mark.parametrize(
    "error",
    [
        exc.ConnectionFailed,
        exc.ServiceNotFound,
        exc.HandshakeFailed,
        exc.AuthenticationFailed,
        exc.PairingRequired,
        exc.PairingTimeout,
        exc.ProtocolError,
        exc.VehicleBusy,
        exc.UnknownBoard,
        exc.UnknownRegister,
    ],
)
def test_every_error_derives_from_the_base(error: type[Exception]) -> None:
    assert issubclass(error, exc.ScootScootError)


def test_handshake_failures_are_catchable_as_one_group() -> None:
    for error in (exc.AuthenticationFailed, exc.PairingRequired, exc.PairingTimeout):
        assert issubclass(error, exc.HandshakeFailed)


def test_vehicle_busy_is_not_a_handshake_failure() -> None:
    # Echo and phone-app contention are retryable connection conditions,
    # not a rejection of our credentials.
    assert not issubclass(exc.VehicleBusy, exc.HandshakeFailed)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_exceptions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scootscoot'`

- [ ] **Step 4: Write the implementation**

`src/scootscoot/exceptions.py`:

```python
"""Error hierarchy. Every error scootscoot raises derives from ScootScootError."""

from __future__ import annotations


class ScootScootError(Exception):
    """Base class for every error raised by scootscoot."""


class ConnectionFailed(ScootScootError):
    """establish_connection exhausted its attempts."""


class ServiceNotFound(ScootScootError):
    """No candidate GATT service had both its write and notify characteristics."""


class ProtocolError(ScootScootError):
    """A frame was unparseable, or failed its MAC or checksum."""


class VehicleBusy(ScootScootError):
    """The vehicle echoed our frame, or another client holds its single BLE slot."""


class HandshakeFailed(ScootScootError):
    """The three-phase authentication handshake did not complete."""


class AuthenticationFailed(HandshakeFailed):
    """AUTH was rejected — the password is wrong or stale."""


class PairingRequired(HandshakeFailed):
    """A password is needed and none was supplied, or pairing was not allowed."""


class PairingTimeout(HandshakeFailed):
    """The vehicle asked for physical confirmation that never arrived."""


class UnknownBoard(ScootScootError):
    """The profile does not declare a board for the requested role."""


class UnknownRegister(ScootScootError):
    """The profile does not declare a register with the requested name."""
```

`src/scootscoot/__init__.py`:

```python
"""Async BLE library for Segway-Ninebot vehicles (Encryption2 / authV2)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from scootscoot.exceptions import (
    AuthenticationFailed,
    ConnectionFailed,
    HandshakeFailed,
    PairingRequired,
    PairingTimeout,
    ProtocolError,
    ScootScootError,
    ServiceNotFound,
    UnknownBoard,
    UnknownRegister,
    VehicleBusy,
)

try:
    __version__ = version("scootscoot")
except PackageNotFoundError:  # pragma: no cover - only when running from a bare tree
    __version__ = "0.0.0.dev0"

__all__ = [
    "AuthenticationFailed",
    "ConnectionFailed",
    "HandshakeFailed",
    "PairingRequired",
    "PairingTimeout",
    "ProtocolError",
    "ScootScootError",
    "ServiceNotFound",
    "UnknownBoard",
    "UnknownRegister",
    "VehicleBusy",
    "__version__",
]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv sync && uv run pytest tests/test_exceptions.py -v`
Expected: PASS — 13 tests.

- [ ] **Step 6: Verify lint, format and types**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all clean. If `ruff format --check` fails, run `uv run ruff format .` and re-check.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml LICENSE .gitignore README.md src tests
git commit -m "feat: project scaffold, packaging, and error hierarchy"
```

---

### Task 2: Encryption2 crypto primitives

**Files:**
- Create: `src/scootscoot/crypto.py`
- Test: `tests/test_crypto.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `FW_DATA: bytes` (16), `ZERO16: bytes` (16)
  - `CryptoStatus` — `IntEnum` with `OK = 0`, `MAC_MISMATCH = 1`, `REPLAY = 2`
  - `aes_ecb_block(key: bytes, block: bytes) -> bytes`
  - `derive_key(key1: bytes, key2: bytes | None) -> bytes`
  - `build_nonce(counter: int, auth: bytes) -> bytes`
  - `cbc_mac(key: bytes, plaintext: bytes, nonce13: bytes) -> bytes`
  - `ctr_xor(key: bytes, data: bytes, nonce13: bytes, start: int = 1) -> bytes`
  - `JavaRandom(seed: int)` with `.next_int() -> int` (unsigned 32-bit) and `.next_bytes(n: int) -> bytes`
  - `generate_password(auth: bytes, time_ms: int | None = None) -> bytes` (16 bytes)
  - `NbCrypto(ecb_input: bytes = ZERO16, *, strict_replay: bool = False)` with `set_key`, `set_auth_param`, `start_sn`, `reset_sn`, `encrypt(plaintext: bytes) -> bytes`, `decrypt(frame: bytes) -> tuple[bytes, CryptoStatus]`, and a mutable `counter: int` attribute.

**Background the implementer needs:** this is a port of `nb_crypto.py` from `~/GitHub/andyshinn/scooter-query/segway-ninebot-ble-cli/`, which was verified against a Ghidra decompilation of `libnbcrypto.so`. The algorithm is documented in `~/GitHub/andyshinn/scooter-query/segway-ninebot-ble/docs/encryption.md`. The only intended change is using `cryptography` instead of `pycryptodome` for the single-block AES call. Do not "improve" the algorithm — the non-standard CTR and truncated 4-byte CBC-MAC are what the vehicle expects.

- [ ] **Step 1: Write the failing test**

All hex vectors below were generated from the verified reference implementation. `JavaRandom` is additionally cross-checked against published `java.util.Random` outputs: seed 0 gives `-1155484576` and seed 42 gives `-1170105035` as signed 32-bit, which are `3139482720` and `3124862261` unsigned.

`tests/test_crypto.py`:

```python
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
    assert nonce[:4] == b"\x00\x00\x00\x02"   # counter, big-endian
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
    assert gen2.encrypt(b"\x5a\xa5\x00" + payload)[3:] != gen3.encrypt(b"\x5a\xb5\x00" + payload)[3:]


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
    assert crypto.encrypt(plain).hex() == (
        "5aa50e61953a24af9d804adf4b6574c538dec052420eab3d9f0002"
    )


def test_first_sn_frame_uses_counter_two() -> None:
    # start_sn sets 1 and the first encrypt increments to 2, so AUTH lands on
    # counter 2 whether or not SET_PWD ran. The vehicle depends on this.
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
    assert generate_password(AUTH, 1_700_000_000_000) != generate_password(
        AUTH, 1_700_000_000_001
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scootscoot.crypto'`

- [ ] **Step 3: Write the implementation**

`src/scootscoot/crypto.py`:

```python
"""Encryption2 (authV2) crypto primitives.

Ported from the reference implementation, which was verified against a Ghidra
decompilation of libnbcrypto.so: nb_encrypt @ 0x169f80, the CBC-MAC routine
@ 0x16a35c, and nb_decrypt @ 0x16a55c.

The construction resembles AES-CCM but is not CCM: the CTR nonce format is
custom and the MAC is truncated to four bytes. Do not substitute a standard
mode -- the vehicle will reject the frames.
"""

from __future__ import annotations

import hashlib
import logging
import struct
import time
from enum import IntEnum

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

#: Fixed protocol parameter from libnbcrypto.so @ 0x45A80. Shared by every
#: device and app version; used as the gen2 ECB input and initial key2.
FW_DATA = bytes.fromhex("97cfb802844143de56002b3b34780a5d")
ZERO16 = b"\x00" * 16

_HEADER_LEN = 3
_TAIL_LEN = 6
_TAG_LEN = 4


class CryptoStatus(IntEnum):
    """Outcome of a decrypt attempt."""

    OK = 0
    MAC_MISMATCH = 1
    REPLAY = 2


def aes_ecb_block(key: bytes, block: bytes) -> bytes:
    """Encrypt exactly one 16-byte block with AES-128-ECB."""
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(block) + encryptor.finalize()


def derive_key(key1: bytes, key2: bytes | None) -> bytes:
    """SHA-1(key1_pad16 || key2_pad16)[0:16] -> AES-128 key."""
    k1 = (key1 + ZERO16)[:16]
    k2 = (key2 + ZERO16)[:16] if key2 else ZERO16
    return hashlib.sha1(k1 + k2, usedforsecurity=False).digest()[:16]


def build_nonce(counter: int, auth: bytes) -> bytes:
    """13-byte nonce: counter_BE32 || auth[0:8] || 0x00."""
    return struct.pack(">I", counter) + auth[:8] + b"\x00"


def _a_block(nonce13: bytes, index: int) -> bytes:
    """CTR keystream block A_i = 0x01 || nonce || 0x00 || i."""
    return b"\x01" + nonce13 + bytes([0x00, index & 0xFF])


def _b0(nonce13: bytes, payload_len: int) -> bytes:
    """CBC-MAC seed block B_0 = 0x59 || nonce || 0x00 || payload_len."""
    return b"\x59" + nonce13 + bytes([0x00, payload_len & 0xFF])


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right, strict=False))


def cbc_mac(key: bytes, plaintext: bytes, nonce13: bytes) -> bytes:
    """Four-byte CBC-MAC over a plaintext frame.

    The three-byte frame header is folded in as associated data, zero-padded to
    a full block, before the payload blocks.
    """
    state = aes_ecb_block(key, _b0(nonce13, len(plaintext) - _HEADER_LEN))
    state = aes_ecb_block(key, _xor(state, plaintext[:_HEADER_LEN] + b"\x00" * 13))
    payload = plaintext[_HEADER_LEN:]
    for offset in range(0, len(payload), 16):
        block = payload[offset : offset + 16].ljust(16, b"\x00")
        state = aes_ecb_block(key, _xor(state, block))
    return state[:_TAG_LEN]


def ctr_xor(key: bytes, data: bytes, nonce13: bytes, start: int = 1) -> bytes:
    """CTR-mode XOR. Symmetric, so this both encrypts and decrypts."""
    out = bytearray()
    index = start
    for offset in range(0, len(data), 16):
        keystream = aes_ecb_block(key, _a_block(nonce13, index))
        out += _xor(data[offset : offset + 16], keystream)
        index += 1
    return bytes(out)


class NbCrypto:
    """Stateful Encryption2 context: keys, auth parameter, packet counter.

    Performs no I/O. One instance corresponds to one connection; the counter and
    derived key cannot outlive it, because the vehicle regenerates its auth
    parameter on every PRE_COMM.
    """

    def __init__(self, ecb_input: bytes = ZERO16, *, strict_replay: bool = False) -> None:
        self.key1: bytes = b""
        self.key2: bytes | None = None
        self.auth: bytes = ZERO16
        self.counter: int = 0
        self.ecb_input: bytes = ecb_input[:16]
        self.strict_replay = strict_replay
        self.last_received: int = 0

    def set_key(self, key1: bytes, key2: bytes | None) -> None:
        self.key1 = key1
        self.key2 = key2

    def set_auth_param(self, auth: bytes) -> None:
        self.auth = bytes(auth[:16])

    def start_sn(self) -> None:
        """Enter SN mode. The next encrypt uses counter 2."""
        self.counter = 1

    def reset_sn(self) -> None:
        self.counter = 0
        self.last_received = 0

    def _aes_key(self) -> bytes:
        return derive_key(self.key1, self.key2)

    def encrypt(self, plaintext: bytes) -> bytes:
        key = self._aes_key()
        header = plaintext[:_HEADER_LEN]
        if self.counter > 0:
            self.counter += 1
            nonce = build_nonce(self.counter, self.auth)
            tag = cbc_mac(key, plaintext, nonce)
            body = ctr_xor(key, plaintext[_HEADER_LEN:], nonce)
            enc_tag = _xor(tag, aes_ecb_block(key, _a_block(nonce, 0))[:_TAG_LEN])
            return header + body + enc_tag + struct.pack(">H", self.counter & 0xFFFF)

        payload = plaintext[_HEADER_LEN:]
        checksum = (~sum(payload)) & 0xFFFF
        keystream = aes_ecb_block(key, self.ecb_input)
        body = bytearray()
        for offset in range(0, len(payload), 16):
            body += _xor(payload[offset : offset + 16], keystream)
        tail = bytes([0x00, 0x00, checksum & 0xFF, (checksum >> 8) & 0xFF, 0x00, 0x00])
        return header + bytes(body) + tail

    def decrypt(self, frame: bytes) -> tuple[bytes, CryptoStatus]:
        if len(frame) < _HEADER_LEN + _TAIL_LEN:
            msg = f"frame too short to decrypt: {len(frame)} bytes"
            raise ValueError(msg)

        key = self._aes_key()
        header = frame[:_HEADER_LEN]
        tail = frame[-_TAIL_LEN:]
        body = frame[_HEADER_LEN:-_TAIL_LEN]
        counter = (tail[4] << 8) | tail[5]

        if counter > 0:
            if counter <= self.last_received:
                if self.strict_replay:
                    return b"", CryptoStatus.REPLAY
                _LOGGER.warning(
                    "non-increasing receive counter %d (last seen %d); accepting anyway",
                    counter,
                    self.last_received,
                )
            nonce = build_nonce(counter, self.auth)
            plaintext = header + ctr_xor(key, body, nonce)
            recv_tag = _xor(tail[:_TAG_LEN], aes_ecb_block(key, _a_block(nonce, 0))[:_TAG_LEN])
            if recv_tag != cbc_mac(key, plaintext, nonce):
                return plaintext, CryptoStatus.MAC_MISMATCH
            self.last_received = counter
            return plaintext, CryptoStatus.OK

        keystream = aes_ecb_block(key, self.ecb_input)
        out = bytearray()
        for offset in range(0, len(body), 16):
            out += _xor(body[offset : offset + 16], keystream)
        plaintext = header + bytes(out)
        expected = (~sum(plaintext[_HEADER_LEN:])) & 0xFFFF
        if expected != (tail[2] | (tail[3] << 8)):
            return plaintext, CryptoStatus.MAC_MISMATCH
        return plaintext, CryptoStatus.OK


_JAVA_MASK = (1 << 48) - 1
_JAVA_MULT = 0x5DEECE66D
_JAVA_ADD = 0xB


class JavaRandom:
    """java.util.Random -- a 48-bit LCG. Needed to reproduce app passwords."""

    def __init__(self, seed: int) -> None:
        self._seed = (seed ^ _JAVA_MULT) & _JAVA_MASK

    def _next(self, bits: int) -> int:
        self._seed = (self._seed * _JAVA_MULT + _JAVA_ADD) & _JAVA_MASK
        return self._seed >> (48 - bits)

    def next_int(self) -> int:
        """One nextInt(), as an unsigned 32-bit value."""
        return self._next(32)

    def next_bytes(self, count: int) -> bytes:
        """Fill `count` bytes, four per nextInt(), low byte first."""
        out = bytearray(count)
        i = 0
        while i < count:
            value = self.next_int()
            for shift in range(min(4, count - i)):
                out[i] = (value >> (8 * shift)) & 0xFF
                i += 1
        return bytes(out)


def _java_int(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def _java_long(value: int) -> int:
    value &= 0xFFFFFFFFFFFFFFFF
    return value - 0x10000000000000000 if value >= 0x8000000000000000 else value


def generate_password(auth: bytes, time_ms: int | None = None) -> bytes:
    """Generate a 16-byte session password, matching the app's provider.

    seed = currentTimeMillis + sum(signed(auth[i]) << ((i % 8) * 8)), where the
    shift is a Java int shift and therefore masked with 31.
    """
    if time_ms is None:
        time_ms = int(time.time() * 1000)

    accumulated = 0
    for i, byte in enumerate(auth):
        signed = byte if byte < 128 else byte - 256
        accumulated = _java_long(accumulated + _java_int(signed << (((i % 8) * 8) & 31)))

    random_bytes = JavaRandom(_java_long(time_ms + accumulated)).next_bytes(16)
    return hashlib.sha256(random_bytes).digest()[:16]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_crypto.py -v`
Expected: PASS — all tests, including every hex vector.

- [ ] **Step 5: Verify lint and types**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/scootscoot/crypto.py tests/test_crypto.py
git commit -m "feat: Encryption2 crypto primitives with verified vectors"
```

---

### Task 3: Frame building, parsing, and reassembly

**Files:**
- Create: `src/scootscoot/framing.py`
- Test: `tests/test_framing.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Constants `SYNC1 = 0x5A`, `SYNC2_GEN2 = 0xA5`, `SYNC2_GEN3 = 0xB5`, `VALID_SYNC2: frozenset[int]`, `BT_ID = 0x3E`, `FRAME_OVERHEAD = 13`
  - Command constants `CMD_READ = 0x01`, `CMD_WRITE = 0x02`, `CMD_WRITE_NR = 0x03`, `CMD_READ_RESP = 0x04`, `CMD_WRITE_RESP = 0x05`, `CMD_PRE_COMM = 0x5B`, `CMD_SET_PWD = 0x5C`, `CMD_AUTH = 0x5D`
  - `Frame` — frozen dataclass with `length: int`, `board_id: int`, `cmd: int`, `index: int`, `data: bytes`
  - `build_frame(target: int, cmd: int, index: int, data: bytes = b"", *, sync2: int = SYNC2_GEN2) -> bytes`
  - `build_read(target: int, index: int, length: int, *, sync2: int = SYNC2_GEN2) -> bytes`
  - `parse_frame(plaintext: bytes) -> Frame | None`
  - `FrameAssembler` with `feed(chunk: bytes) -> list[bytes]` and `clear() -> None`

**Key detail:** requests and responses have *different* layouts. A request is `[SYNC1, sync2, LEN, 0x3E, target, cmd, index, *data]`; a response is `[SYNC1, sync2, LEN, source_board, 0x3E, cmd, index, *data]`. The `0x3E` moves. An encrypted frame on the wire is always `LEN + 13` bytes.

- [ ] **Step 1: Write the failing test**

`tests/test_framing.py`:

```python
from __future__ import annotations

from scootscoot.framing import (
    BT_ID,
    CMD_AUTH,
    CMD_PRE_COMM,
    SYNC2_GEN2,
    SYNC2_GEN3,
    FrameAssembler,
    build_frame,
    build_read,
    parse_frame,
)


def test_build_frame_lays_out_a_request() -> None:
    assert build_frame(0x04, CMD_PRE_COMM, 0x00).hex() == "5aa5003e045b00"


def test_build_frame_honours_the_gen3_sync_byte() -> None:
    assert build_frame(0x04, CMD_PRE_COMM, 0x00, sync2=SYNC2_GEN3).hex() == "5ab5003e045b00"


def test_build_frame_sets_length_from_the_payload() -> None:
    frame = build_frame(0x04, CMD_AUTH, 0x00, b"03GGG2527C0165")
    assert frame[2] == 14
    assert frame[7:] == b"03GGG2527C0165"


def test_build_read_requests_a_length() -> None:
    # A read carries the requested byte count as its single payload byte.
    assert build_read(0x07, 0x8F, 2).hex() == "5aa5013e07018f02"


def test_parse_frame_reads_a_response() -> None:
    frame = parse_frame(bytes.fromhex("5aa502073e04" "8f" "3600"))
    assert frame is not None
    assert frame.length == 2
    assert frame.board_id == 0x07
    assert frame.cmd == 0x04
    assert frame.index == 0x8F
    assert frame.data == bytes.fromhex("3600")


def test_parse_frame_accepts_either_sync_byte() -> None:
    for sync2 in (SYNC2_GEN2, SYNC2_GEN3):
        raw = bytes([0x5A, sync2, 0x00, 0x04, BT_ID, CMD_PRE_COMM, 0x01])
        assert parse_frame(raw) is not None


def test_parse_frame_rejects_a_bad_sync() -> None:
    assert parse_frame(bytes([0x5A, 0x99, 0x00, 0x04, BT_ID, CMD_PRE_COMM, 0x01])) is None


def test_parse_frame_rejects_a_wrong_bt_id() -> None:
    # Byte 4 of a response must be 0x3E or the vehicle is not talking to us.
    assert parse_frame(bytes([0x5A, 0xA5, 0x00, 0x04, 0x99, CMD_PRE_COMM, 0x01])) is None


def test_parse_frame_rejects_a_runt() -> None:
    assert parse_frame(b"\x5a\xa5\x00") is None


def test_assembler_yields_a_whole_frame() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(frame) == [frame]


def test_assembler_waits_for_a_frame_split_across_chunks() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(frame[:5]) == []
    assert assembler.feed(frame[5:]) == [frame]


def test_assembler_survives_a_sync_split_across_chunks() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(frame[:1]) == []
    assert assembler.feed(frame[1:]) == [frame]


def test_assembler_skips_a_garbage_prefix() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(b"\xde\xad\xbe\xef" + frame) == [frame]


def test_assembler_returns_two_back_to_back_frames() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(frame + frame) == [frame, frame]


def test_assembler_holds_a_truncated_tail() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(frame + frame[:4]) == [frame]
    assert assembler.feed(frame[4:]) == [frame]


def test_assembler_discards_pure_garbage_without_growing() -> None:
    assembler = FrameAssembler()
    for _ in range(100):
        assert assembler.feed(b"\xde\xad\xbe\xef") == []
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assert assembler.feed(frame) == [frame]


def test_clear_drops_buffered_bytes() -> None:
    assembler = FrameAssembler()
    frame = bytes.fromhex("5aa500e1748ab4000062ff0000")
    assembler.feed(frame[:5])
    assembler.clear()
    assert assembler.feed(frame[5:]) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_framing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scootscoot.framing'`

- [ ] **Step 3: Write the implementation**

`src/scootscoot/framing.py`:

```python
"""Encryption2 frame construction, parsing, and stream reassembly.

Request  (app -> vehicle):  [0x5A, sync2, LEN, 0x3E, target, cmd, index, *data]
Response (vehicle -> app):  [0x5A, sync2, LEN, source_board, 0x3E, cmd, index, *data]

Note the 0x3E moves between the two layouts. On the wire, after encryption, a
frame is always LEN + 13 bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

SYNC1 = 0x5A
SYNC2_GEN2 = 0xA5
SYNC2_GEN3 = 0xB5
VALID_SYNC2 = frozenset({SYNC2_GEN2, SYNC2_GEN3})

#: Protocol-layer identifier. Not a board address. Frames without it are dropped.
BT_ID = 0x3E

#: Encrypted frame length = LEN + header(3) + tag(4) + counter(2) + ... = LEN + 13.
FRAME_OVERHEAD = 13

_MIN_FRAME_LEN = 7
_MAX_PAYLOAD = 255

CMD_READ = 0x01
CMD_WRITE = 0x02
CMD_WRITE_NR = 0x03
CMD_READ_RESP = 0x04
CMD_WRITE_RESP = 0x05

CMD_PRE_COMM = 0x5B
CMD_SET_PWD = 0x5C
CMD_AUTH = 0x5D


@dataclass(frozen=True, slots=True)
class Frame:
    """A decrypted response frame."""

    length: int
    board_id: int
    cmd: int
    index: int
    data: bytes


def build_frame(
    target: int,
    cmd: int,
    index: int,
    data: bytes = b"",
    *,
    sync2: int = SYNC2_GEN2,
) -> bytes:
    """Build a plaintext request frame."""
    if len(data) > _MAX_PAYLOAD:
        msg = f"payload too long: {len(data)} > {_MAX_PAYLOAD}"
        raise ValueError(msg)
    return bytes([SYNC1, sync2, len(data), BT_ID, target, cmd, index]) + data


def build_read(target: int, index: int, length: int, *, sync2: int = SYNC2_GEN2) -> bytes:
    """Build a register read. The payload is the requested byte count."""
    return build_frame(target, CMD_READ, index, bytes([length]), sync2=sync2)


def parse_frame(plaintext: bytes) -> Frame | None:
    """Parse a decrypted response frame, or None if it is not one."""
    if len(plaintext) < _MIN_FRAME_LEN:
        return None
    if plaintext[0] != SYNC1 or plaintext[1] not in VALID_SYNC2:
        return None
    if plaintext[4] != BT_ID:
        return None
    length = plaintext[2]
    return Frame(
        length=length,
        board_id=plaintext[3],
        cmd=plaintext[5],
        index=plaintext[6],
        data=plaintext[7 : 7 + length],
    )


class FrameAssembler:
    """Reassembles encrypted frames from a stream of GATT notification chunks."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def clear(self) -> None:
        self._buf.clear()

    def feed(self, chunk: bytes) -> list[bytes]:
        """Add a chunk and return every complete frame it completed."""
        self._buf.extend(chunk)
        frames: list[bytes] = []
        while True:
            start = self._find_sync()
            if start is None:
                break
            if start:
                del self._buf[:start]
            if len(self._buf) < 3:
                break
            total = self._buf[2] + FRAME_OVERHEAD
            if len(self._buf) < total:
                break
            frames.append(bytes(self._buf[:total]))
            del self._buf[:total]
        return frames

    def _find_sync(self) -> int | None:
        """Offset of the next sync pair, trimming the buffer when there is none."""
        for i in range(len(self._buf) - 1):
            if self._buf[i] == SYNC1 and self._buf[i + 1] in VALID_SYNC2:
                return i
        # Keep a trailing lone 0x5A: the sync pair may straddle two chunks.
        if self._buf and self._buf[-1] == SYNC1:
            del self._buf[:-1]
        else:
            self._buf.clear()
        return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_framing.py -v`
Expected: PASS.

- [ ] **Step 5: Verify lint and types**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/scootscoot/framing.py tests/test_framing.py
git commit -m "feat: frame building, parsing, and stream reassembly"
```

---

### Task 4: Device profiles — types, GT3 Pro, registry

**Files:**
- Create: `src/scootscoot/profiles/__init__.py`, `src/scootscoot/profiles/types.py`, `src/scootscoot/profiles/gt3_pro.py`, `src/scootscoot/profiles/registry.py`
- Test: `tests/test_profiles.py`

**Interfaces:**
- Consumes: `scootscoot.exceptions.{ServiceNotFound, UnknownBoard, UnknownRegister}`, `scootscoot.crypto.{FW_DATA, ZERO16}`, `scootscoot.framing.{SYNC2_GEN2, SYNC2_GEN3}`.
- Produces:
  - `BoardRole` — `StrEnum`: `VCU`, `MCU`, `BMS1`, `BMS2`, `BLE`, `DIS`, `ECU`
  - `ValueKind` — `StrEnum`: `U16`, `I16`, `U32`, `I32`, `ASCII`, `RAW`, `VERSION`, `DATE`, `U16_ARRAY`
  - `Board(role, address, awake_when_parked)` — frozen, slots
  - `Register(name, board, index, kind, length, scale=1.0, unit=None, count=1)` — frozen, slots
  - `CryptoSuite(label, sync2, ecb_input, initial_key2)` — frozen, slots; constants `ENC2_GEN2`, `ENC2_GEN3`
  - `GattProfile(label, service, write, notify)` — frozen, slots; constants `NORDIC_UART`, `NINEBOT_CUSTOM`
  - `DeviceProfile(key, name, hardware_id, server_id, crypto, transports, boards, registers, poll, identity)` — frozen, with `board(role) -> Board`, `register(name) -> Register`, `has_register(name) -> bool`, `registers_for(role) -> tuple[Register, ...]`
  - `choose_gatt_profile(available: Collection[str], candidates: Sequence[GattProfile]) -> GattProfile`
  - `scootscoot.profiles.GT3_PRO`, `scootscoot.profiles.ALL: tuple[DeviceProfile, ...]`, `scootscoot.profiles.get(key: str) -> DeviceProfile`

**Data provenance:** board addresses and register scales come from `~/GitHub/andyshinn/scooter-query/README.md`, which records a full 256-address sweep and per-register calibration against the Segway app's own display. Register *names* come from the generated command table in `segway-ninebot-ble/docs/devices/segway-superscooter-gt3.md`. Where the two disagree, the hardware wins — notably the cell count (20, not the `0x1A` the table specifies).

- [ ] **Step 1: Write the failing test**

`tests/test_profiles.py`:

```python
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


def test_gt3_sleeps_the_vcu_and_mcu_when_parked() -> None:
    gt3 = profiles.GT3_PRO
    assert gt3.board(BoardRole.BMS1).awake_when_parked
    assert gt3.board(BoardRole.BLE).awake_when_parked
    assert not gt3.board(BoardRole.VCU).awake_when_parked
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_profiles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scootscoot.profiles'`

- [ ] **Step 3: Write the profile types**

`src/scootscoot/profiles/types.py`:

```python
"""Declarative device description. Frozen dataclasses, not data files.

Everything model-specific lives here and in the profile modules. The protocol,
transport, and session layers never name a vehicle.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property

from scootscoot.crypto import FW_DATA, ZERO16
from scootscoot.exceptions import ServiceNotFound, UnknownBoard, UnknownRegister
from scootscoot.framing import SYNC2_GEN2, SYNC2_GEN3


class BoardRole(StrEnum):
    """Logical function of a board. Addresses vary by model; roles do not."""

    VCU = "vcu"
    MCU = "mcu"
    BMS1 = "bms1"
    BMS2 = "bms2"
    BLE = "ble"
    DIS = "dis"
    ECU = "ecu"


class ValueKind(StrEnum):
    """How a register's raw bytes should be interpreted."""

    U16 = "u16"
    I16 = "i16"
    U32 = "u32"
    I32 = "i32"
    ASCII = "ascii"
    RAW = "raw"
    VERSION = "version"
    DATE = "date"
    U16_ARRAY = "u16_array"


@dataclass(frozen=True, slots=True)
class Board:
    """One addressable module inside a vehicle."""

    role: BoardRole
    address: int
    #: Whether this board answers with the vehicle switched off. On a parked
    #: vehicle only the BLE radio and the BMS respond; VCU and MCU sleep.
    awake_when_parked: bool


@dataclass(frozen=True, slots=True)
class Register:
    """One readable register on one board."""

    name: str
    board: BoardRole
    index: int
    kind: ValueKind
    #: Bytes requested on the wire. Explicit rather than derived, because the
    #: vendor command tables specify it and are occasionally wrong.
    length: int
    scale: float = 1.0
    unit: str | None = None
    #: Element count for U16_ARRAY.
    count: int = 1


@dataclass(frozen=True, slots=True)
class CryptoSuite:
    """Framing and key-seeding parameters for one protocol generation."""

    label: str
    sync2: int
    ecb_input: bytes
    initial_key2: bytes | None


ENC2_GEN2 = CryptoSuite(
    label="enc2-gen2",
    sync2=SYNC2_GEN2,
    ecb_input=FW_DATA,
    initial_key2=FW_DATA,
)

ENC2_GEN3 = CryptoSuite(
    label="enc2-gen3",
    sync2=SYNC2_GEN3,
    ecb_input=ZERO16,
    initial_key2=None,
)


@dataclass(frozen=True, slots=True)
class GattProfile:
    """A candidate GATT service and its write/notify characteristic pair."""

    label: str
    service: str
    write: str
    notify: str


NORDIC_UART = GattProfile(
    label="Nordic UART",
    service="6e400001-b5a3-f393-e0a9-e50e24dcca9e",
    write="6e400002-b5a3-f393-e0a9-e50e24dcca9e",
    notify="6e400003-b5a3-f393-e0a9-e50e24dcca9e",
)

NINEBOT_CUSTOM = GattProfile(
    label="Ninebot Custom",
    service="6e400001-0000-0000-006e-696e65626f74",
    write="6e400002-0000-0000-006e-696e65626f74",
    # 0004, not 0003 -- 0003 is the secondary RCTP write channel.
    notify="6e400004-0000-0000-006e-696e65626f74",
)


@dataclass(frozen=True)
class DeviceProfile:
    """Everything model-specific about one vehicle family."""

    key: str
    name: str
    hardware_id: int | None
    server_id: int | None
    crypto: CryptoSuite
    #: GATT candidates in preference order.
    transports: tuple[GattProfile, ...]
    boards: tuple[Board, ...]
    registers: tuple[Register, ...]
    #: Register names read by poll(), in declaration order.
    poll: tuple[str, ...]
    #: Register names read by identify(). Static data, not polled.
    identity: tuple[str, ...]

    @cached_property
    def _boards_by_role(self) -> dict[BoardRole, Board]:
        return {board.role: board for board in self.boards}

    @cached_property
    def _registers_by_name(self) -> dict[str, Register]:
        return {register.name: register for register in self.registers}

    def board(self, role: BoardRole) -> Board:
        try:
            return self._boards_by_role[role]
        except KeyError:
            msg = f"{self.key} declares no {role} board"
            raise UnknownBoard(msg) from None

    def register(self, name: str) -> Register:
        try:
            return self._registers_by_name[name]
        except KeyError:
            msg = f"{self.key} declares no register named {name!r}"
            raise UnknownRegister(msg) from None

    def has_register(self, name: str) -> bool:
        return name in self._registers_by_name

    def registers_for(self, role: BoardRole) -> tuple[Register, ...]:
        return tuple(register for register in self.registers if register.board is role)


def choose_gatt_profile(
    available: Collection[str],
    candidates: Sequence[GattProfile],
) -> GattProfile:
    """Pick the first candidate whose write *and* notify characteristics exist.

    Selecting on the service alone is a trap: a GT3 Pro exposes both Nordic UART
    and Ninebot Custom, the Ninebot service has more characteristics, and it is
    the dead one -- it accepts writes and never answers.
    """
    present = {uuid.lower() for uuid in available}
    for candidate in candidates:
        if candidate.write.lower() in present and candidate.notify.lower() in present:
            return candidate
    msg = (
        "no candidate service had both a write and a notify characteristic; "
        f"saw {sorted(present)}"
    )
    raise ServiceNotFound(msg)
```

- [ ] **Step 4: Write the GT3 Pro profile**

`src/scootscoot/profiles/gt3_pro.py`:

```python
"""Segway SuperScooter GT3 Pro.

Board addresses and register scales come from a full 256-address sweep and
per-register calibration against the Segway app on serial 03GGG2527C0165
(VCU 1.2.2 / MCU 2.1.1 / BMS 1.0.7 / BLE 0.2.8). Register names come from the
app's generated command table (server id 10257).

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
```

- [ ] **Step 5: Write the registry and package exports**

`src/scootscoot/profiles/registry.py`:

```python
"""The shipped profile registry. Selection is explicit -- nothing is guessed."""

from __future__ import annotations

from scootscoot.profiles.gt3_pro import GT3_PRO
from scootscoot.profiles.types import DeviceProfile

#: Every profile this release ships. Consumers render this for a model picker.
ALL: tuple[DeviceProfile, ...] = (GT3_PRO,)

_BY_KEY = {profile.key: profile for profile in ALL}


def get(key: str) -> DeviceProfile:
    """Look up a profile by its key. Raises KeyError if it is not shipped."""
    return _BY_KEY[key]
```

`src/scootscoot/profiles/__init__.py`:

```python
"""Device profiles. Adding a model means adding a module here, nothing else."""

from __future__ import annotations

from scootscoot.profiles.gt3_pro import GT3_PRO
from scootscoot.profiles.registry import ALL, get
from scootscoot.profiles.types import (
    ENC2_GEN2,
    ENC2_GEN3,
    NINEBOT_CUSTOM,
    NORDIC_UART,
    Board,
    BoardRole,
    CryptoSuite,
    DeviceProfile,
    GattProfile,
    Register,
    ValueKind,
    choose_gatt_profile,
)

__all__ = [
    "ALL",
    "ENC2_GEN2",
    "ENC2_GEN3",
    "GT3_PRO",
    "NINEBOT_CUSTOM",
    "NORDIC_UART",
    "Board",
    "BoardRole",
    "CryptoSuite",
    "DeviceProfile",
    "GattProfile",
    "Register",
    "ValueKind",
    "choose_gatt_profile",
    "get",
]
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_profiles.py -v`
Expected: PASS.

- [ ] **Step 7: Verify lint and types**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/scootscoot/profiles tests/test_profiles.py
git commit -m "feat: declarative device profiles with the GT3 Pro as the first"
```

---

### Task 5: Register value decoding

**Files:**
- Create: `src/scootscoot/decode.py`
- Test: `tests/test_decode.py`

**Interfaces:**
- Consumes: `scootscoot.profiles.types.{Register, ValueKind}`.
- Produces:
  - `DecodedValue` — type alias `int | float | str | date | bytes | tuple[int | float, ...]`
  - `decode(register: Register, raw: bytes) -> DecodedValue | None` — returns `None` when `raw` is shorter than the register's declared length, or when a packed date is not a real calendar date.

**Encodings, all confirmed against hardware:**
- Packed version: `major = (v >> 8) & 0xFF`, `minor = (v >> 4) & 0x0F`, `patch = v & 0x0F`. So `290 -> "1.2.2"`, `529 -> "2.1.1"`, `263 -> "1.0.7"`, `40 -> "0.2.8"`.
- Packed date: `(year - 2000) << 9 | month << 5 | day`. So `13114 -> 2025-09-26` and `13016 -> 2025-06-24`.
- All multi-byte integers are little-endian.

- [ ] **Step 1: Write the failing test**

`tests/test_decode.py`:

```python
from __future__ import annotations

from datetime import date

import pytest

from scootscoot import profiles
from scootscoot.decode import decode
from scootscoot.profiles.types import BoardRole, Register, ValueKind

GT3 = profiles.GT3_PRO


def test_u16_little_endian() -> None:
    assert decode(GT3.register("rBmsSOC"), bytes.fromhex("3600")) == 54


def test_i16_is_signed() -> None:
    # rBMSCur reads -6 raw at rest; regeneration makes it negative in use.
    assert decode(GT3.register("rBMSCur"), bytes.fromhex("faff")) == -0.06


def test_u32_little_endian_with_scale() -> None:
    # 5781 at 0.1 km = 578.1 km odometer (359.2 mi; the app showed 359.0).
    assert decode(GT3.register("rMileage"), bytes.fromhex("95160000")) == 578.1


def test_range_uses_a_hundredth_scale_not_a_tenth() -> None:
    # 7452 at 0.01 km = 74.52 km (46.30 mi; the app showed 46.26). Reading this
    # at the odometer's scale is what produced a bogus "745.2 km range".
    assert decode(GT3.register("rLeftMileage"), bytes.fromhex("1c1d")) == 74.52


def test_voltage_scale() -> None:
    # 0x1D97 = 7575 -> 75.75 V, matching the sum of the twenty cells.
    assert decode(GT3.register("rBMSVolt"), bytes.fromhex("971d")) == 75.75


def test_capacity_scale_is_ten_milliamp_hours() -> None:
    assert decode(GT3.register("rBmsCapFull"), bytes.fromhex("b80b")) == 30.0


def test_temperature_scale() -> None:
    # 0x015A = 346 -> 34.6 degrees.
    assert decode(GT3.register("rBodyTemp"), bytes.fromhex("5a01")) == 34.6


def test_unscaled_registers_stay_integers() -> None:
    value = decode(GT3.register("rBmsCycleCountLT"), bytes.fromhex("0200"))
    assert value == 2
    assert isinstance(value, int)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2201", "1.2.2"),
        ("1102", "2.1.1"),
        ("0701", "1.0.7"),
        ("2800", "0.2.8"),
    ],
)
def test_packed_version(raw: str, expected: str) -> None:
    assert decode(GT3.register("rCtrlV"), bytes.fromhex(raw)) == expected


def test_packed_date_activation() -> None:
    # 13114 -> 2025-09-26, exactly 317 days before the app's "317 days as owner".
    assert decode(GT3.register("rActDate"), bytes.fromhex("3a33")) == date(2025, 9, 26)


def test_packed_date_manufacture() -> None:
    assert decode(
        GT3.register("rBmsManufactureDateLT"), bytes.fromhex("d832")
    ) == date(2025, 6, 24)


def test_impossible_packed_date_returns_none() -> None:
    assert decode(GT3.register("rActDate"), bytes.fromhex("0000")) is None


def test_ascii_strips_padding() -> None:
    raw = b"03GGG2527C0165"
    assert decode(GT3.register("rSN"), raw) == "03GGG2527C0165"


def test_ascii_strips_trailing_nulls() -> None:
    raw = b"Z03QB4G25FJ4\x00\x00\x00\x00"
    assert decode(GT3.register("rPN"), raw) == "Z03QB4G25FJ4"


def test_u16_array_of_temperatures() -> None:
    raw = bytes.fromhex("22002200230023002200220023002200")
    assert decode(GT3.register("rBmsTemps"), raw) == (34, 34, 35, 35, 34, 34, 35, 34)


def test_u16_array_of_cell_voltages_sums_to_the_pack() -> None:
    # Twenty cells around 3.788 V summing to ~75.76 V against rBMSVolt's 75.75.
    cells = [3788] * 20
    raw = b"".join(cell.to_bytes(2, "little") for cell in cells)
    decoded = decode(GT3.register("rBmsCellVolFrequence"), raw)
    assert isinstance(decoded, tuple)
    assert len(decoded) == 20
    assert decoded[0] == 3.788
    assert round(sum(decoded), 2) == 75.76


def test_raw_kind_returns_bytes() -> None:
    register = Register("rBlob", BoardRole.BLE, 0x4D, ValueKind.RAW, 4)
    assert decode(register, bytes.fromhex("deadbeefcafe")) == bytes.fromhex("deadbeef")


def test_short_read_returns_none() -> None:
    assert decode(GT3.register("rMileage"), bytes.fromhex("9516")) is None


def test_empty_read_returns_none() -> None:
    assert decode(GT3.register("rBmsSOC"), b"") is None


def test_extra_bytes_are_ignored() -> None:
    assert decode(GT3.register("rBmsSOC"), bytes.fromhex("3600ffff")) == 54
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_decode.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scootscoot.decode'`

- [ ] **Step 3: Write the implementation**

`src/scootscoot/decode.py`:

```python
"""Turn a register's raw bytes into a typed value.

All multi-byte integers on this protocol are little-endian. Scales come from the
profile, not from here -- getting range and odometer scales confused is a real
bug that shipped in an earlier client.
"""

from __future__ import annotations

from datetime import date

from scootscoot.profiles.types import Register, ValueKind

DecodedValue = int | float | str | date | bytes | tuple[int | float, ...]

_SIGNED_KINDS = frozenset({ValueKind.I16, ValueKind.I32})
#: Round after scaling so 7452 * 0.01 reads 74.52 rather than 74.52000000000001.
_SCALE_PRECISION = 6


def decode(register: Register, raw: bytes) -> DecodedValue | None:
    """Decode `raw` per `register`, or None if it is unusable.

    Returns None when the response is shorter than the register's declared
    length (a truncated or absent read) or when a packed date is not a real
    calendar date.
    """
    if len(raw) < register.length:
        return None

    kind = register.kind
    payload = raw[: register.length]

    if kind is ValueKind.RAW:
        return payload

    if kind is ValueKind.ASCII:
        return payload.decode("ascii", errors="replace").replace("\x00", "").strip()

    if kind is ValueKind.U16_ARRAY:
        return tuple(
            _scaled(int.from_bytes(payload[i * 2 : i * 2 + 2], "little"), register.scale)
            for i in range(register.count)
        )

    value = int.from_bytes(payload, "little", signed=kind in _SIGNED_KINDS)

    if kind is ValueKind.VERSION:
        return f"{(value >> 8) & 0xFF}.{(value >> 4) & 0x0F}.{value & 0x0F}"

    if kind is ValueKind.DATE:
        return _decode_date(value)

    return _scaled(value, register.scale)


def _scaled(value: int, scale: float) -> int | float:
    if scale == 1.0:
        return value
    return round(value * scale, _SCALE_PRECISION)


def _decode_date(value: int) -> date | None:
    """Unpack (year - 2000) << 9 | month << 5 | day."""
    try:
        return date(2000 + (value >> 9), (value >> 5) & 0x0F, value & 0x1F)
    except ValueError:
        return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_decode.py -v`
Expected: PASS.

- [ ] **Step 5: Verify lint and types**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/scootscoot/decode.py tests/test_decode.py
git commit -m "feat: register value decoding calibrated against hardware readings"
```

---

### Task 6: Result model, poll planning, and state assembly

**Files:**
- Create: `src/scootscoot/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `scootscoot.decode.decode`, `scootscoot.profiles.types.{BoardRole, DeviceProfile, Register}`.
- Produces:
  - `BatteryState`, `VehicleState`, `MotorState`, `ScooterState`, `DeviceInfo` — frozen, slots, every field defaulting to `None` except `ScooterState.serial`/`profile_key`/`responding` and `DeviceInfo.serial`
  - `plan_poll(profile: DeviceProfile) -> tuple[Register, ...]`
  - `build_state(profile: DeviceProfile, values: Mapping[str, bytes | None], *, serial: str) -> ScooterState`
  - `build_info(profile: DeviceProfile, values: Mapping[str, bytes | None], *, serial: str) -> DeviceInfo`

**Why this is a separate module from `session.py`:** these two functions are where the real polling logic lives — board ordering, and deciding what "the VCU was asleep" looks like in the result. Keeping them pure puts them under the project's unit-test strategy, and leaves `ScooterSession` as glue that walks a plan and does I/O.

The register-name → field maps are keyed by vendor register names (`rBmsSOC`, `rMileage`), which are stable across models because they come from Segway's own command tables. A profile that does not declare a given register simply yields `None` for that field, so the maps stay device-agnostic.

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:

```python
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
    values.update({name: None for name in VCU_VALUES})
    values.update({name: None for name in MCU_VALUES})

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
    values: dict[str, bytes | None] = {name: None for name in GT3.poll}
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scootscoot.models'`

- [ ] **Step 3: Write the implementation**

`src/scootscoot/models.py`:

```python
"""Result dataclasses, poll planning, and state assembly.

plan_poll and build_state are pure by design: they hold the polling logic that
matters (board ordering, and what "the board was asleep" looks like in a
result), so ScooterSession can stay glue.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, TypeVar

from scootscoot.decode import decode
from scootscoot.profiles.types import BoardRole, DeviceProfile, Register

_T = TypeVar("_T")


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


def _group(
    profile: DeviceProfile,
    values: Mapping[str, bytes | None],
    role: BoardRole,
    fields: Mapping[str, str],
    factory: Callable[..., _T],
    responding: frozenset[BoardRole],
) -> _T | None:
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Verify lint and types**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/scootscoot/models.py tests/test_models.py
git commit -m "feat: result model, poll planning, and state assembly"
```

---

### Task 7: Handshake state machine

**Files:**
- Create: `src/scootscoot/handshake.py`
- Create: `tests/vehicle_frames.py`
- Test: `tests/test_handshake.py`

**Interfaces:**
- Consumes: `scootscoot.crypto.{NbCrypto, CryptoStatus, generate_password}`, `scootscoot.framing.{build_frame, parse_frame, CMD_PRE_COMM, CMD_SET_PWD, CMD_AUTH, SYNC2_GEN2}`, `scootscoot.profiles.types.{CryptoSuite, ENC2_GEN2, ENC2_GEN3}`, `scootscoot.exceptions.*`.
- Produces:
  - `Send(payload: bytes, timeout: float, attempts: int)` — frozen, slots
  - `AwaitConfirmation(timeout: float)` — frozen, slots
  - `Established(crypto: NbCrypto, serial: str, password: bytes, sync2: int, paired: bool)` — frozen, slots
  - `Step` — type alias `Send | AwaitConfirmation | Established`
  - `Handshake(*, device_name: str, suite: CryptoSuite, ble_address: int, password: bytes | None = None, allow_pairing: bool = False, clock_ms: Callable[[], int] | None = None)` with `start() -> Step` and `feed(raw: bytes) -> Step`

**This is the riskiest code in the project, and it is pure on purpose.** `feed` takes *encrypted* bytes and decrypts internally, so the driver in Task 10 only moves bytes. No `await`, no I/O, no sleeping.

Three behaviours the tests must pin:

1. **The vehicle generates its own sync byte.** PRE_COMM must go out under the profile's declared suite, because the ECB input and initial key2 are suite-dependent and encryption precedes any response. But the reply's header byte 1 is the vehicle's own sync byte — read it and use it for everything after. The header travels in the clear (it is copied verbatim through encryption), so it is readable before decrypting.
2. **Wrong-suite recovery.** If the PRE_COMM response fails its non-SN checksum, rebuild the context under the other Encryption2 suite and decrypt the *same* response again. A profile carrying the wrong generation self-corrects instead of timing out.
3. **A stored password means SET_PWD is futile.** When the vehicle reports a stored password (`index != 0`) and the caller supplied none, raise `PairingRequired` immediately rather than sending a SET_PWD that will be silently dropped and read as a timeout.

- [ ] **Step 1: Write the vehicle-side frame helpers**

The vehicle side of a frame is `NbCrypto` run in the other direction, so the tests build responses with the same pure code that is already vector-verified in Task 2. These are functions, not a simulated device.

`tests/vehicle_frames.py`:

```python
"""Synthesise vehicle-side frames for handshake tests.

The vehicle encrypts with the same algorithm we do, just with the roles of the
key material swapped per phase. Nothing here simulates a device -- these are
frame builders.
"""

from __future__ import annotations

from scootscoot.crypto import NbCrypto
from scootscoot.framing import BT_ID, CMD_AUTH, CMD_PRE_COMM, CMD_SET_PWD, SYNC1
from scootscoot.profiles.types import CryptoSuite

DEVICE_NAME = "TESTDEVICE0001"
SERIAL = b"03GGG2527C0165"
AUTH_PARAM = bytes(range(16))
BLE_ADDRESS = 0x04
STORED_PASSWORD = bytes.fromhex("000102030405060708090a0b0c0d0e0f")


def response_plaintext(sync2: int, board: int, cmd: int, index: int, data: bytes = b"") -> bytes:
    """A decrypted response: [5A, sync2, LEN, source_board, 3E, cmd, index, *data]."""
    return bytes([SYNC1, sync2, len(data), board, BT_ID, cmd, index]) + data


def pre_comm_response(
    suite: CryptoSuite,
    *,
    has_stored_password: bool,
    auth: bytes = AUTH_PARAM,
    serial: bytes = SERIAL,
    device_name: str = DEVICE_NAME,
) -> bytes:
    """Phase 1 reply. Non-SN mode, keyed on the BLE name and the suite's key2."""
    plaintext = response_plaintext(
        suite.sync2,
        BLE_ADDRESS,
        CMD_PRE_COMM,
        1 if has_stored_password else 0,
        auth + serial,
    )
    crypto = NbCrypto(ecb_input=suite.ecb_input)
    crypto.set_key(device_name.encode(), suite.initial_key2)
    return crypto.encrypt(plaintext)


def set_pwd_response(
    suite: CryptoSuite,
    *,
    accepted: bool,
    auth: bytes = AUTH_PARAM,
    device_name: str = DEVICE_NAME,
    counter: int = 2,
) -> bytes:
    """Phase 2 reply. SN mode, keyed on the BLE name and the auth parameter."""
    plaintext = response_plaintext(suite.sync2, BLE_ADDRESS, CMD_SET_PWD, 1 if accepted else 0)
    return _sn_frame(plaintext, suite, device_name.encode(), auth, auth, counter)


def auth_response(
    suite: CryptoSuite,
    *,
    accepted: bool,
    password: bytes,
    auth: bytes = AUTH_PARAM,
    counter: int = 3,
) -> bytes:
    """Phase 3 reply. SN mode, keyed on the session password and the auth parameter."""
    plaintext = response_plaintext(suite.sync2, BLE_ADDRESS, CMD_AUTH, 1 if accepted else 0)
    return _sn_frame(plaintext, suite, password, auth, auth, counter)


def _sn_frame(
    plaintext: bytes,
    suite: CryptoSuite,
    key1: bytes,
    key2: bytes,
    auth: bytes,
    counter: int,
) -> bytes:
    crypto = NbCrypto(ecb_input=suite.ecb_input)
    crypto.set_key(key1, key2)
    crypto.set_auth_param(auth)
    crypto.counter = counter - 1  # encrypt() increments before use
    return crypto.encrypt(plaintext)
```

- [ ] **Step 2: Write the failing test**

`tests/test_handshake.py`:

```python
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
from scootscoot.profiles.types import ENC2_GEN2, ENC2_GEN3
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
    suite=ENC2_GEN2,
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

    step = handshake.feed(
        auth_response(ENC2_GEN2, accepted=True, password=STORED_PASSWORD)
    )
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
```

Add `tests/__init__.py` (empty) so `from tests.vehicle_frames import ...` resolves.

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_handshake.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scootscoot.handshake'`

- [ ] **Step 4: Write the implementation**

`src/scootscoot/handshake.py`:

```python
"""The three-phase Encryption2 handshake, as a pure state machine.

    PRE_COMM  -> auth parameter + serial number
    SET_PWD   -> establish a session password (may need a button press)
    AUTH      -> prove the password, then normal encrypted communication

feed() takes encrypted bytes and decrypts internally, so the driver only moves
bytes between this object and the transport. No I/O happens here.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from scootscoot.crypto import CryptoStatus, NbCrypto, generate_password
from scootscoot.exceptions import (
    AuthenticationFailed,
    HandshakeFailed,
    PairingRequired,
    PairingTimeout,
    ProtocolError,
    VehicleBusy,
)
from scootscoot.framing import (
    CMD_AUTH,
    CMD_PRE_COMM,
    CMD_SET_PWD,
    SYNC2_GEN2,
    Frame,
    build_frame,
    parse_frame,
)
from scootscoot.profiles.types import ENC2_GEN2, ENC2_GEN3, CryptoSuite

_LOGGER = logging.getLogger(__name__)

PRE_COMM_TIMEOUT = 2.0
PRE_COMM_ATTEMPTS = 10
SET_PWD_TIMEOUT = 2.0
SET_PWD_ATTEMPTS = 1
AUTH_TIMEOUT = 2.0
AUTH_ATTEMPTS = 3
CONFIRM_TIMEOUT = 60.0
#: The app polls SET_PWD every 2s inside a 60s window.
MAX_CONFIRMATIONS = 30

_PRE_COMM_PAYLOAD_LEN = 30
_SERIAL_LEN = 14


@dataclass(frozen=True, slots=True)
class Send:
    """Write `payload`, then feed the reply back in."""

    payload: bytes
    timeout: float
    attempts: int


@dataclass(frozen=True, slots=True)
class AwaitConfirmation:
    """The vehicle wants a physical button press. Wait, then feed the reply."""

    timeout: float


@dataclass(frozen=True, slots=True)
class Established:
    """The session is authenticated."""

    crypto: NbCrypto
    serial: str
    password: bytes
    sync2: int
    #: True when a new password was negotiated and the caller should persist it.
    paired: bool


Step = Send | AwaitConfirmation | Established


class _Phase(Enum):
    INITIAL = auto()
    PRE_COMM = auto()
    SET_PWD = auto()
    AUTH = auto()
    DONE = auto()


class Handshake:
    """Drives PRE_COMM -> SET_PWD -> AUTH. One instance per connection."""

    def __init__(
        self,
        *,
        device_name: str,
        suite: CryptoSuite,
        ble_address: int,
        password: bytes | None = None,
        allow_pairing: bool = False,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._name = device_name.encode()
        self._suite = suite
        self._ble = ble_address
        self._password = password
        self._allow_pairing = allow_pairing
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))

        self._phase = _Phase.INITIAL
        self._crypto = NbCrypto(ecb_input=suite.ecb_input)
        self._sync2 = suite.sync2
        self._auth = b""
        self._serial = b""
        self._request = b""
        self._paired = False
        self._suite_retried = False
        self._confirmations = 0

    def start(self) -> Step:
        """Build the PRE_COMM request."""
        self._crypto = NbCrypto(ecb_input=self._suite.ecb_input)
        self._crypto.set_key(self._name, self._suite.initial_key2)
        self._sync2 = self._suite.sync2
        self._request = self._crypto.encrypt(
            build_frame(self._ble, CMD_PRE_COMM, 0x00, sync2=self._sync2)
        )
        self._phase = _Phase.PRE_COMM
        return Send(self._request, PRE_COMM_TIMEOUT, PRE_COMM_ATTEMPTS)

    def feed(self, raw: bytes) -> Step:
        """Consume one encrypted response frame and return the next step."""
        if self._phase is _Phase.PRE_COMM:
            return self._feed_pre_comm(raw)
        if self._phase is _Phase.SET_PWD:
            return self._feed_set_pwd(raw)
        if self._phase is _Phase.AUTH:
            return self._feed_auth(raw)
        msg = f"handshake received a frame while in phase {self._phase.name}"
        raise HandshakeFailed(msg)

    def _feed_pre_comm(self, raw: bytes) -> Step:
        if raw == self._request:
            msg = (
                "the vehicle echoed our PRE_COMM frame instead of answering; "
                "another client (usually the phone app) most likely holds its "
                "single BLE slot"
            )
            raise VehicleBusy(msg)

        plaintext, status = self._decrypt_pre_comm(raw)

        frame = parse_frame(plaintext)
        if frame is None or frame.cmd != CMD_PRE_COMM:
            msg = f"unexpected PRE_COMM response (status={status.name}): {plaintext.hex()}"
            raise ProtocolError(msg)
        if len(frame.data) < _PRE_COMM_PAYLOAD_LEN:
            msg = f"PRE_COMM payload too short: {len(frame.data)} bytes"
            raise ProtocolError(msg)

        # The vehicle generates its own sync byte. Adopt it rather than trusting
        # the profile -- the header is copied verbatim through encryption, so it
        # is readable straight off the wire.
        self._sync2 = raw[1]
        self._auth = frame.data[:16]
        self._serial = frame.data[16:_PRE_COMM_PAYLOAD_LEN]
        has_stored_password = frame.index != 0

        self._crypto.set_auth_param(self._auth)
        self._crypto.start_sn()

        if self._password is not None:
            return self._begin_auth()

        if has_stored_password:
            msg = (
                "the vehicle holds a password from an earlier pairing and will "
                "silently ignore SET_PWD; supply that password instead. On iOS it "
                "is the NSUserDefaults key {serial}_decrypt in "
                "com.ninebot.segway.plist, holding 16 raw bytes"
            )
            raise PairingRequired(msg)

        if not self._allow_pairing:
            msg = "no password supplied and allow_pairing is False"
            raise PairingRequired(msg)

        return self._begin_set_pwd()

    def _decrypt_pre_comm(self, raw: bytes) -> tuple[bytes, CryptoStatus]:
        plaintext, status = self._crypto.decrypt(raw)
        if status is CryptoStatus.OK:
            return plaintext, status

        if self._suite_retried:
            msg = "PRE_COMM response did not decrypt under either Encryption2 suite"
            raise ProtocolError(msg)

        alternate = _alternate_suite(self._suite)
        _LOGGER.debug(
            "PRE_COMM failed under %s; retrying under %s", self._suite.label, alternate.label
        )
        self._suite_retried = True
        self._suite = alternate
        self._crypto = NbCrypto(ecb_input=alternate.ecb_input)
        self._crypto.set_key(self._name, alternate.initial_key2)

        plaintext, status = self._crypto.decrypt(raw)
        if status is not CryptoStatus.OK:
            msg = "PRE_COMM response did not decrypt under either Encryption2 suite"
            raise ProtocolError(msg)
        return plaintext, status

    def _begin_set_pwd(self) -> Step:
        self._crypto.set_key(self._name, self._auth)
        self._password = generate_password(self._auth, self._clock_ms())
        self._paired = True
        self._phase = _Phase.SET_PWD
        payload = self._crypto.encrypt(
            build_frame(self._ble, CMD_SET_PWD, 0x00, self._password, sync2=self._sync2)
        )
        return Send(payload, SET_PWD_TIMEOUT, SET_PWD_ATTEMPTS)

    def _feed_set_pwd(self, raw: bytes) -> Step:
        frame = self._expect(raw, CMD_SET_PWD)
        if frame.index == 1:
            return self._begin_auth()

        self._confirmations += 1
        if self._confirmations > MAX_CONFIRMATIONS:
            msg = "the vehicle never confirmed pairing; was its button pressed?"
            raise PairingTimeout(msg)
        return AwaitConfirmation(CONFIRM_TIMEOUT)

    def _begin_auth(self) -> Step:
        password = self._password
        if password is None:  # pragma: no cover - guarded by the callers
            msg = "internal error: AUTH requires a password"
            raise HandshakeFailed(msg)

        # start_sn() set 1 and the first encrypt increments to 2, so AUTH lands
        # on counter 2 whether or not SET_PWD ran. The vehicle depends on that.
        self._crypto.set_key(password, self._auth)
        self._phase = _Phase.AUTH
        payload = self._crypto.encrypt(
            build_frame(
                self._ble, CMD_AUTH, 0x00, self._serial[:_SERIAL_LEN], sync2=self._sync2
            )
        )
        return Send(payload, AUTH_TIMEOUT, AUTH_ATTEMPTS)

    def _feed_auth(self, raw: bytes) -> Step:
        frame = self._expect(raw, CMD_AUTH)
        if frame.index != 1:
            msg = (
                f"AUTH rejected (index={frame.index}); the password is wrong or "
                "stale for this vehicle"
            )
            raise AuthenticationFailed(msg)

        password = self._password
        if password is None:  # pragma: no cover - guarded by _begin_auth
            msg = "internal error: authenticated without a password"
            raise HandshakeFailed(msg)

        self._phase = _Phase.DONE
        return Established(
            crypto=self._crypto,
            serial=self._serial.decode("ascii", errors="replace").replace("\x00", "").strip(),
            password=password,
            sync2=self._sync2,
            paired=self._paired,
        )

    def _expect(self, raw: bytes, cmd: int) -> Frame:
        plaintext, status = self._crypto.decrypt(raw)
        if status is not CryptoStatus.OK:
            msg = f"handshake response failed verification ({status.name})"
            raise ProtocolError(msg)
        frame = parse_frame(plaintext)
        if frame is None:
            msg = f"unparseable handshake response: {plaintext.hex()}"
            raise ProtocolError(msg)
        if frame.cmd != cmd:
            msg = f"expected cmd 0x{cmd:02X}, got 0x{frame.cmd:02X}"
            raise ProtocolError(msg)
        return frame


def _alternate_suite(suite: CryptoSuite) -> CryptoSuite:
    return ENC2_GEN3 if suite.sync2 == SYNC2_GEN2 else ENC2_GEN2
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_handshake.py -v`
Expected: PASS.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest`
Expected: every test from Tasks 1–7 passes.

- [ ] **Step 7: Verify lint and types**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/scootscoot/handshake.py tests/test_handshake.py tests/vehicle_frames.py tests/__init__.py
git commit -m "feat: pure three-phase handshake state machine"
```

---

### Task 8: FrameChannel seam and the bleak transport

**Files:**
- Create: `src/scootscoot/channel.py`, `src/scootscoot/transport.py`
- Test: `tests/test_channel_contract.py`

**Interfaces:**
- Consumes: `scootscoot.framing.FrameAssembler`, `scootscoot.profiles.types.{GattProfile, choose_gatt_profile}`.
- Produces:
  - `FrameChannel` — `Protocol` with `async send(data: bytes) -> None`, `async recv(timeout: float) -> bytes`, `drain() -> None`
  - `BleTransport(client: BleakClient, gatt: GattProfile)` implementing `FrameChannel`, plus `async start()`, `async stop()`
  - `available_characteristics(client: BleakClient) -> frozenset[str]`
  - `select_transport(client: BleakClient, candidates: Sequence[GattProfile]) -> GattProfile`

**This task has no behavioural tests** — it is GATT plumbing, and the project's test strategy covers pure functions only. The one test here is a compile-time conformance check: mypy verifies that `BleTransport` structurally satisfies `FrameChannel`, which is what keeps `session.py` free of any bleak dependency. Everything else is verified by ruff, mypy, and manual testing against the GT3.

Two details that are easy to get wrong and expensive to debug:

- **Fragmentation is bidirectional.** The vehicle fragments its notifications, and the app must fragment its writes at `MTU - 3` bytes. An oversized single write is silently truncated by the BLE stack; the vehicle then receives an incomplete frame and never answers. A ~10 ms gap between fragments is required.
- **Writes are without response** (`response=False`). The protocol acknowledges at the frame layer, not the GATT layer.

- [ ] **Step 1: Write the conformance test**

`tests/test_channel_contract.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from scootscoot.channel import FrameChannel
from scootscoot.transport import BleTransport

if TYPE_CHECKING:

    def _ble_transport_is_a_frame_channel(transport: BleTransport) -> FrameChannel:
        """Checked by mypy: session.py can depend on the protocol, not on bleak."""
        return transport


def test_frame_channel_declares_the_expected_surface() -> None:
    for method in ("send", "recv", "drain"):
        assert hasattr(FrameChannel, method)


def test_ble_transport_implements_every_channel_method() -> None:
    for method in ("send", "recv", "drain"):
        assert callable(getattr(BleTransport, method))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_channel_contract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scootscoot.channel'`

- [ ] **Step 3: Write the channel protocol**

`src/scootscoot/channel.py`:

```python
"""The seam between the protocol layers and whatever moves bytes.

Everything above this line -- handshake, session, decoding -- talks only to
FrameChannel. BleTransport is one implementation; a test double is another.
"""

from __future__ import annotations

from typing import Protocol


class FrameChannel(Protocol):
    """Moves whole encrypted frames to and from a vehicle."""

    async def send(self, data: bytes) -> None:
        """Write one complete encrypted frame, fragmenting if required."""
        ...

    async def recv(self, timeout: float) -> bytes:
        """Return the next complete frame, or raise TimeoutError."""
        ...

    def drain(self) -> None:
        """Discard buffered and queued frames before starting an exchange."""
        ...
```

- [ ] **Step 4: Write the bleak transport**

`src/scootscoot/transport.py`:

```python
"""GATT plumbing: notification reassembly and MTU-aware fragmented writes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from bleak import BleakClient

from scootscoot.framing import FrameAssembler
from scootscoot.profiles.types import GattProfile, choose_gatt_profile

_LOGGER = logging.getLogger(__name__)

#: BLE 4.0 default. Used when a backend will not report the negotiated MTU.
_DEFAULT_MTU = 23
#: ATT write overhead: the payload limit is MTU - 3.
_ATT_OVERHEAD = 3
_MIN_CHUNK = 20
_FRAGMENT_DELAY = 0.01


def available_characteristics(client: BleakClient) -> frozenset[str]:
    """Every characteristic UUID the connected client can see, lowercased."""
    return frozenset(
        characteristic.uuid.lower()
        for service in client.services
        for characteristic in service.characteristics
    )


def select_transport(client: BleakClient, candidates: Sequence[GattProfile]) -> GattProfile:
    """Pick the GATT profile whose write and notify characteristics both exist."""
    chosen = choose_gatt_profile(available_characteristics(client), candidates)
    _LOGGER.debug("using the %s service", chosen.label)
    return chosen


class BleTransport:
    """A FrameChannel over a connected BleakClient."""

    def __init__(self, client: BleakClient, gatt: GattProfile) -> None:
        self._client = client
        self._gatt = gatt
        self._assembler = FrameAssembler()
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def start(self) -> None:
        await self._client.start_notify(self._gatt.notify, self._on_notify)

    async def stop(self) -> None:
        try:
            await self._client.stop_notify(self._gatt.notify)
        except Exception:
            # Teardown must never mask the error that caused it.
            _LOGGER.debug("stop_notify failed during teardown", exc_info=True)

    def _on_notify(self, _sender: object, data: bytearray) -> None:
        for frame in self._assembler.feed(bytes(data)):
            self._queue.put_nowait(frame)

    async def send(self, data: bytes) -> None:
        chunk_size = max(_MIN_CHUNK, self._mtu() - _ATT_OVERHEAD)
        _LOGGER.debug("TX (%d bytes, chunk %d) %s", len(data), chunk_size, data.hex())
        for offset in range(0, len(data), chunk_size):
            await self._client.write_gatt_char(
                self._gatt.write, data[offset : offset + chunk_size], response=False
            )
            if offset + chunk_size < len(data):
                # The stack silently truncates back-to-back oversized writes.
                await asyncio.sleep(_FRAGMENT_DELAY)

    async def recv(self, timeout: float) -> bytes:
        try:
            frame = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            msg = f"no frame within {timeout}s"
            raise TimeoutError(msg) from None
        _LOGGER.debug("RX (%d bytes) %s", len(frame), frame.hex())
        return frame

    def drain(self) -> None:
        self._assembler.clear()
        while not self._queue.empty():
            self._queue.get_nowait()

    def _mtu(self) -> int:
        try:
            return int(self._client.mtu_size)
        except Exception:
            # Not every backend reports the negotiated MTU.
            return _DEFAULT_MTU
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_channel_contract.py -v`
Expected: PASS.

- [ ] **Step 6: Verify lint and types**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean. mypy must accept `_ble_transport_is_a_frame_channel` — if it does not, `BleTransport` has drifted from the protocol and the signatures need reconciling.

- [ ] **Step 7: Commit**

```bash
git add src/scootscoot/channel.py src/scootscoot/transport.py tests/test_channel_contract.py
git commit -m "feat: FrameChannel seam and MTU-aware bleak transport"
```

---

### Task 9: ScooterSession

**Files:**
- Create: `src/scootscoot/session.py`
- Test: none — this is glue over a precomputed plan; the logic it would test lives in `models.plan_poll` and `models.build_state` (Task 6).

**Interfaces:**
- Consumes: `scootscoot.channel.FrameChannel`, `scootscoot.crypto.{NbCrypto, CryptoStatus}`, `scootscoot.framing.{build_read, parse_frame}`, `scootscoot.decode.{DecodedValue, decode}`, `scootscoot.models.{DeviceInfo, ScooterState, build_info, build_state, plan_poll}`, `scootscoot.profiles.types.{DeviceProfile, Register}`.
- Produces: `ScooterSession(channel, crypto, profile, *, sync2, serial, timeout=2.0)` with:
  - `async read_raw(board: int, index: int, length: int = 2, *, timeout: float | None = None) -> bytes | None`
  - `async read(name: str) -> DecodedValue | None`
  - `async poll() -> ScooterState`
  - `async identify() -> DeviceInfo`
  - `async probe_boards(addresses: Iterable[int] = range(256), *, index: int = 0x10, length: int = 2, timeout: float = 0.5) -> tuple[int, ...]`
  - `async scan_registers(board: int, indices: Iterable[int] = range(256), *, length: int = 2, timeout: float = 0.5) -> dict[int, bytes]`

**Two rules this module enforces:**

- **Verify the responding board.** A reply whose `board_id` differs from the requested target is discarded. Without that, a short timeout lets a slow board's answer land on the next probe and invent boards that do not exist.
- **Skip a sleeping board's remaining registers.** After the first no-answer from a board that is not `awake_when_parked`, mark the rest of its registers absent rather than paying a timeout each. On a parked GT3 that turns roughly thirty timeouts into two.

- [ ] **Step 1: Write the implementation**

`src/scootscoot/session.py`:

```python
"""An authenticated connection. Walks a read plan and does the I/O.

Deliberately thin: ordering lives in models.plan_poll and result assembly in
models.build_state, both pure and unit-tested.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

from scootscoot.channel import FrameChannel
from scootscoot.crypto import CryptoStatus, NbCrypto
from scootscoot.decode import DecodedValue, decode
from scootscoot.framing import build_read, parse_frame
from scootscoot.models import (
    DeviceInfo,
    ScooterState,
    build_info,
    build_state,
    plan_poll,
)
from scootscoot.profiles.types import BoardRole, DeviceProfile, Register

_LOGGER = logging.getLogger(__name__)

DEFAULT_READ_TIMEOUT = 2.0
DEFAULT_PROBE_TIMEOUT = 0.5
#: Part number / serial. Present on most boards, so it makes a decent probe.
DEFAULT_PROBE_INDEX = 0x10


class ScooterSession:
    """Reads registers over an authenticated channel.

    Created by Scooter.session(); not constructed directly. The session ends
    when its connection does -- the crypto context cannot outlive it, because
    the vehicle regenerates its auth parameter on every PRE_COMM.
    """

    def __init__(
        self,
        channel: FrameChannel,
        crypto: NbCrypto,
        profile: DeviceProfile,
        *,
        sync2: int,
        serial: str,
        timeout: float = DEFAULT_READ_TIMEOUT,
    ) -> None:
        self._channel = channel
        self._crypto = crypto
        self._profile = profile
        self._sync2 = sync2
        self._serial = serial
        self._timeout = timeout

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def profile(self) -> DeviceProfile:
        return self._profile

    async def read_raw(
        self,
        board: int,
        index: int,
        length: int = 2,
        *,
        timeout: float | None = None,
    ) -> bytes | None:
        """Read one register by raw address. None on timeout or a mismatch."""
        self._channel.drain()
        request = build_read(board, index, length, sync2=self._sync2)
        await self._channel.send(self._crypto.encrypt(request))

        try:
            raw = await self._channel.recv(timeout if timeout is not None else self._timeout)
        except TimeoutError:
            _LOGGER.debug("read 0x%02X:0x%02X timed out", board, index)
            return None

        plaintext, status = self._crypto.decrypt(raw)
        if status is not CryptoStatus.OK:
            _LOGGER.debug("read 0x%02X:0x%02X failed verification (%s)", board, index, status.name)

        frame = parse_frame(plaintext)
        if frame is None:
            _LOGGER.debug("read 0x%02X:0x%02X unparseable: %s", board, index, plaintext.hex())
            return None
        if frame.board_id != board:
            # A slow board's reply landing on the next probe would otherwise
            # invent boards that do not exist.
            _LOGGER.debug(
                "board 0x%02X answered a request aimed at 0x%02X; discarding",
                frame.board_id,
                board,
            )
            return None
        return frame.data

    async def read(self, name: str) -> DecodedValue | None:
        """Read one register by profile name and decode it."""
        register = self._profile.register(name)
        raw = await self._read_register(register)
        return decode(register, raw) if raw is not None else None

    async def poll(self) -> ScooterState:
        """Read the profile's poll set and assemble a state snapshot."""
        values = await self._read_many(plan_poll(self._profile))
        return build_state(self._profile, values, serial=self._serial)

    async def identify(self) -> DeviceInfo:
        """Read static identity. Call once at setup, not every poll."""
        registers = [self._profile.register(name) for name in self._profile.identity]
        values = await self._read_many(registers)
        return build_info(self._profile, values, serial=self._serial)

    async def probe_boards(
        self,
        addresses: Iterable[int] = range(256),
        *,
        index: int = DEFAULT_PROBE_INDEX,
        length: int = 2,
        timeout: float = DEFAULT_PROBE_TIMEOUT,
    ) -> tuple[int, ...]:
        """Return the board addresses that answer. For mapping new models."""
        found = []
        for address in addresses:
            if await self.read_raw(address, index, length, timeout=timeout) is not None:
                _LOGGER.debug("board 0x%02X answered", address)
                found.append(address)
        return tuple(found)

    async def scan_registers(
        self,
        board: int,
        indices: Iterable[int] = range(256),
        *,
        length: int = 2,
        timeout: float = DEFAULT_PROBE_TIMEOUT,
    ) -> dict[int, bytes]:
        """Walk every register index on one board. For mapping new models."""
        found: dict[int, bytes] = {}
        for index in indices:
            raw = await self.read_raw(board, index, length, timeout=timeout)
            if raw is not None:
                found[index] = raw
        return found

    async def _read_register(self, register: Register) -> bytes | None:
        board = self._profile.board(register.board)
        return await self.read_raw(board.address, register.index, register.length)

    async def _read_many(self, registers: Sequence[Register]) -> dict[str, bytes | None]:
        values: dict[str, bytes | None] = {}
        asleep: set[BoardRole] = set()

        for register in registers:
            if register.board in asleep:
                values[register.name] = None
                continue

            raw = await self._read_register(register)
            values[register.name] = raw

            if raw is None and not self._profile.board(register.board).awake_when_parked:
                _LOGGER.debug(
                    "%s did not answer; skipping its remaining registers", register.board
                )
                asleep.add(register.board)

        return values
```

- [ ] **Step 2: Verify lint and types**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean. mypy is the real gate here: it proves `session.py` imports nothing from bleak.

- [ ] **Step 3: Confirm the module has no BLE dependency**

Run: `uv run python -c "import ast,sys; tree=ast.parse(open('src/scootscoot/session.py').read()); mods=[n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]; assert not any(m.startswith('bleak') for m in mods), mods; print('session.py is bleak-free')"`
Expected: `session.py is bleak-free`

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: everything still passes.

- [ ] **Step 5: Commit**

```bash
git add src/scootscoot/session.py
git commit -m "feat: ScooterSession over the FrameChannel seam"
```

---

### Task 10: Scooter client and public API

**Files:**
- Create: `src/scootscoot/client.py`
- Modify: `src/scootscoot/__init__.py` (replace the export list written in Task 1)
- Test: `tests/test_public_api.py`

**Interfaces:**
- Consumes: everything from Tasks 1–9.
- Produces:
  - `Credentials(password: bytes | None = None)` — frozen, slots; rejects a password that is not exactly 16 bytes
  - `Scooter(device: BLEDevice, profile: DeviceProfile, credentials: Credentials, *, device_name: str | None = None, allow_pairing: bool = False, connect_timeout: float = 20.0, read_timeout: float = 2.0)` with `session()` (async context manager), `async poll() -> ScooterState`, `async identify() -> DeviceInfo`
  - `scootscoot.__all__` re-exporting `Scooter`, `Credentials`, `ScooterSession`, the model dataclasses, `BoardRole`, `DeviceProfile`, and the error hierarchy

**Connection policy, non-negotiable:**

- No connection outlives the operation that opened it. `poll()` and `identify()` each open a session and close it. Nothing is cached across calls except the caller's password.
- Retries wrap **connect and handshake only**, never the caller's `session()` body. An echoed PRE_COMM means disconnect, wait (1 s then 2 s), reconnect — up to three attempts, then raise `VehicleBusy`.
- Resending an unanswered handshake frame is safe: the counter was fixed when the frame was encrypted, and a vehicle that never received the first copy has an unchanged replay window.

- [ ] **Step 1: Write the failing test**

This tests the public surface and credential validation only — nothing that needs a radio.

`tests/test_public_api.py`:

```python
from __future__ import annotations

import inspect
import pathlib
import re

import pytest

import scootscoot
from scootscoot import Credentials, Scooter

VALID = bytes(range(16))


def test_credentials_accept_sixteen_bytes() -> None:
    assert Credentials(password=VALID).password == VALID


def test_credentials_allow_no_password_for_pairing() -> None:
    assert Credentials().password is None


@pytest.mark.parametrize("bad", [b"", bytes(15), bytes(17)])
def test_credentials_reject_a_wrong_length_password(bad: bytes) -> None:
    with pytest.raises(ValueError, match="16 bytes"):
        Credentials(password=bad)


def test_scooter_defaults_meet_the_home_assistant_floor() -> None:
    signature = inspect.signature(Scooter.__init__)
    assert signature.parameters["connect_timeout"].default >= 10.0
    assert signature.parameters["allow_pairing"].default is False


def test_scooter_exposes_the_documented_operations() -> None:
    for name in ("session", "poll", "identify"):
        assert callable(getattr(Scooter, name))


def test_package_exports_the_public_surface() -> None:
    expected = {
        "BatteryState",
        "BoardRole",
        "Credentials",
        "DeviceInfo",
        "DeviceProfile",
        "MotorState",
        "Scooter",
        "ScooterSession",
        "ScooterState",
        "VehicleState",
    }
    assert expected <= set(scootscoot.__all__)
    for name in scootscoot.__all__:
        assert hasattr(scootscoot, name), name


def test_library_constructs_no_scanner() -> None:
    # Home Assistant owns discovery. Constructing a scanner here would fight it.
    for path in _sources():
        assert "BleakScanner" not in path.read_text(), path


def test_library_does_no_console_io_or_file_io() -> None:
    # Word boundaries matter: a method named _open must not trip the open( rule.
    banned = (r"\bprint\(", r"\bsys\.exit\b", r"\bargparse\b", r"\bopen\(")
    for path in _sources():
        source = path.read_text()
        for pattern in banned:
            assert re.search(pattern, source) is None, f"{path} matches {pattern}"


def _sources() -> list[pathlib.Path]:
    root = pathlib.Path(__file__).resolve().parent.parent / "src" / "scootscoot"
    paths = sorted(root.rglob("*.py"))
    assert paths, f"no sources found under {root}"
    return paths
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_public_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'Credentials' from 'scootscoot'`

- [ ] **Step 3: Write the client**

`src/scootscoot/client.py`:

```python
"""The public entry point.

Home Assistant owns discovery and hands over a resolved BLEDevice; this module
owns the connection. Every operation opens its own connection and closes it, so
the vehicle's single BLE slot is free for the phone app between polls.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from scootscoot.exceptions import ConnectionFailed, HandshakeFailed, PairingTimeout, VehicleBusy
from scootscoot.handshake import Established, Handshake, Send
from scootscoot.models import DeviceInfo, ScooterState
from scootscoot.profiles.types import BoardRole, DeviceProfile
from scootscoot.session import DEFAULT_READ_TIMEOUT, ScooterSession
from scootscoot.transport import BleTransport, select_transport

_LOGGER = logging.getLogger(__name__)

#: Home Assistant requires at least 10s; 20s is comfortable over a proxy.
DEFAULT_CONNECT_TIMEOUT = 20.0
#: Discard notifications cached by the stack from a previous session.
_DRAIN_DELAY = 0.25
#: Backoff before each connect attempt. An echoed PRE_COMM needs a real
#: disconnect to reset the vehicle's BLE stack.
_ATTEMPT_DELAYS = (0.0, 1.0, 2.0)
_GATT_DEVICE_NAME = "00002a00-0000-1000-8000-00805f9b34fb"
_PASSWORD_LEN = 16


@dataclass(frozen=True, slots=True)
class Credentials:
    """Caller-owned secrets. Never read from or written to disk by this library.

    On iOS the password is the NSUserDefaults key ``{SERIAL}_decrypt`` in
    ``Library/Preferences/com.ninebot.segway.plist`` -- 16 raw bytes. It is a
    preferences key, not a file.
    """

    password: bytes | None = None

    def __post_init__(self) -> None:
        if self.password is not None and len(self.password) != _PASSWORD_LEN:
            msg = f"password must be exactly {_PASSWORD_LEN} bytes, got {len(self.password)}"
            raise ValueError(msg)


class Scooter:
    """A Segway-Ninebot vehicle reachable over BLE."""

    def __init__(
        self,
        device: BLEDevice,
        profile: DeviceProfile,
        credentials: Credentials,
        *,
        device_name: str | None = None,
        allow_pairing: bool = False,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
    ) -> None:
        self._device = device
        self._profile = profile
        self._credentials = credentials
        self._device_name = device_name
        self._allow_pairing = allow_pairing
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout

    @property
    def profile(self) -> DeviceProfile:
        return self._profile

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ScooterSession]:
        """Open one authenticated connection for the duration of the block."""
        client, transport, established = await self._open()
        try:
            yield ScooterSession(
                transport,
                established.crypto,
                self._profile,
                sync2=established.sync2,
                serial=established.serial,
                timeout=self._read_timeout,
            )
        finally:
            await transport.stop()
            await client.disconnect()

    async def poll(self) -> ScooterState:
        """Open a connection, read the profile's poll set, close it."""
        async with self.session() as session:
            return await session.poll()

    async def identify(self) -> DeviceInfo:
        """Open a connection, read static identity, close it."""
        async with self.session() as session:
            return await session.identify()

    async def _open(self) -> tuple[BleakClient, BleTransport, Established]:
        """Connect and handshake, retrying only on a busy vehicle."""
        last_busy: VehicleBusy | None = None

        for delay in _ATTEMPT_DELAYS:
            if delay:
                await asyncio.sleep(delay)

            client = await self._establish()
            transport: BleTransport | None = None
            try:
                gatt = select_transport(client, self._profile.transports)
                transport = BleTransport(client, gatt)
                await transport.start()
                await asyncio.sleep(_DRAIN_DELAY)
                transport.drain()
                established = await self._handshake(client, transport)
                return client, transport, established
            except VehicleBusy as err:
                # An echoed frame needs a real disconnect to reset the
                # vehicle's BLE stack; reconnecting is the only recovery.
                last_busy = err
                _LOGGER.debug("vehicle busy; disconnecting before retrying")
                await self._close(client, transport)
            except BaseException:
                await self._close(client, transport)
                raise

        msg = (
            "the vehicle would not start a session after three attempts; it "
            "accepts one BLE client at a time, so close the phone app and retry"
        )
        raise VehicleBusy(msg) from last_busy

    async def _establish(self) -> BleakClient:
        try:
            return await establish_connection(
                BleakClientWithServiceCache,
                self._device,
                self._device_name or self._device.name or self._device.address,
                timeout=self._connect_timeout,
            )
        except (BleakError, TimeoutError) as err:
            msg = f"could not connect to {self._device.address}: {err}"
            raise ConnectionFailed(msg) from err

    async def _close(self, client: BleakClient, transport: BleTransport | None) -> None:
        if transport is not None:
            await transport.stop()
        await client.disconnect()

    async def _handshake(self, client: BleakClient, transport: BleTransport) -> Established:
        handshake = Handshake(
            device_name=await self._key_material(client),
            suite=self._profile.crypto,
            ble_address=self._profile.board(BoardRole.BLE).address,
            password=self._credentials.password,
            allow_pairing=self._allow_pairing,
        )

        step = handshake.start()
        while True:
            if isinstance(step, Established):
                if step.paired:
                    _LOGGER.info(
                        "paired with %s; persist the negotiated password to avoid "
                        "re-pairing on the next connection",
                        step.serial,
                    )
                return step
            if isinstance(step, Send):
                step = handshake.feed(await self._exchange(transport, step))
                continue
            try:
                raw = await transport.recv(step.timeout)
            except TimeoutError as err:
                msg = "the vehicle never confirmed pairing; was its button pressed?"
                raise PairingTimeout(msg) from err
            step = handshake.feed(raw)

    async def _exchange(self, transport: BleTransport, step: Send) -> bytes:
        # Resending an identical frame is safe: its counter was fixed at
        # encryption time, and a vehicle that never received the first copy has
        # an unchanged replay window.
        last: TimeoutError | None = None
        for _ in range(step.attempts):
            transport.drain()
            await transport.send(step.payload)
            try:
                return await transport.recv(step.timeout)
            except TimeoutError as err:
                last = err
        msg = "the vehicle did not answer a handshake frame"
        raise HandshakeFailed(msg) from last

    async def _key_material(self, client: BleakClient) -> str:
        """The BLE name, which is phase-1 key material and must be exact.

        On a GT3 Pro this is the bare serial, with no vendor token.
        """
        if self._device_name:
            return self._device_name
        if self._device.name:
            return self._device.name

        raw = await client.read_gatt_char(_GATT_DEVICE_NAME)
        name = bytes(raw).decode("ascii", errors="ignore").replace("\x00", "").strip()
        if not name:
            msg = (
                "could not determine the BLE device name, which is required as "
                "handshake key material; pass device_name explicitly"
            )
            raise HandshakeFailed(msg)
        return name
```

- [ ] **Step 4: Replace the package exports**

`src/scootscoot/__init__.py`:

```python
"""Async BLE library for Segway-Ninebot vehicles (Encryption2 / authV2)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from scootscoot.client import Credentials, Scooter
from scootscoot.exceptions import (
    AuthenticationFailed,
    ConnectionFailed,
    HandshakeFailed,
    PairingRequired,
    PairingTimeout,
    ProtocolError,
    ScootScootError,
    ServiceNotFound,
    UnknownBoard,
    UnknownRegister,
    VehicleBusy,
)
from scootscoot.models import (
    BatteryState,
    DeviceInfo,
    MotorState,
    ScooterState,
    VehicleState,
)
from scootscoot.profiles.types import BoardRole, DeviceProfile, Register, ValueKind
from scootscoot.session import ScooterSession

try:
    __version__ = version("scootscoot")
except PackageNotFoundError:  # pragma: no cover - only when running from a bare tree
    __version__ = "0.0.0.dev0"

__all__ = [
    "AuthenticationFailed",
    "BatteryState",
    "BoardRole",
    "ConnectionFailed",
    "Credentials",
    "DeviceInfo",
    "DeviceProfile",
    "HandshakeFailed",
    "MotorState",
    "PairingRequired",
    "PairingTimeout",
    "ProtocolError",
    "Register",
    "ScootScootError",
    "Scooter",
    "ScooterSession",
    "ScooterState",
    "ServiceNotFound",
    "UnknownBoard",
    "UnknownRegister",
    "ValueKind",
    "VehicleBusy",
    "VehicleState",
    "__version__",
]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_public_api.py -v`
Expected: PASS.

If `test_library_does_no_console_io_or_file_io` fails on `open(` inside a docstring or comment, fix the source rather than the test — the constraint is real.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest`
Expected: all green.

- [ ] **Step 7: Verify lint and types**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/scootscoot/client.py src/scootscoot/__init__.py tests/test_public_api.py
git commit -m "feat: Scooter client with on-demand sessions and public API"
```

---

### Task 11: README, CI, and PyPI Trusted Publishing

**Files:**
- Modify: `README.md` (replace the Task 1 stub)
- Create: `.github/workflows/ci.yml`, `.github/workflows/publish.yml`

**Interfaces:**
- Consumes: the finished package.
- Produces: no Python API. A green CI run on push, and a tag-triggered PyPI release with no API tokens.

- [ ] **Step 1: Write the README**

Replace `README.md` entirely:

````markdown
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
````

- [ ] **Step 2: Write the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: ["**"]
    tags-ignore: ["**"]
  pull_request:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
        with:
          # hatch-vcs derives the version from tags, so a shallow clone breaks it.
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --python ${{ matrix.python-version }}
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy
      - run: uv run pytest

  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v5
      - run: uv build
      - run: uvx twine check dist/*
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
```

- [ ] **Step 3: Write the publish workflow**

`.github/workflows/publish.yml`:

```yaml
name: Publish

on:
  push:
    tags: ["v*"]

permissions:
  contents: read

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v5
      - run: uv build
      - run: uvx twine check dist/*
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      # Required for Trusted Publishing. No API token is stored anywhere.
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 4: Verify the build produces a versioned artifact**

```bash
git tag -a v0.1.0 -m "v0.1.0"
uv build
ls dist/
```

Expected: `scootscoot-0.1.0.tar.gz` and `scootscoot-0.1.0-py3-none-any.whl`. If the version reads `0.0.0` or `0.1.dev...`, hatch-vcs is not seeing the tag — check that the tag exists and the clone is not shallow.

- [ ] **Step 5: Confirm py.typed ships in the wheel**

Run: `unzip -l dist/scootscoot-0.1.0-py3-none-any.whl | grep py.typed`
Expected: one line showing `scootscoot/py.typed`. Without it, consumers get no type information.

- [ ] **Step 6: Run the whole suite one last time**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add README.md .github
git commit -m "docs: README, CI, and PyPI trusted publishing"
```

- [ ] **Step 8: Register the Trusted Publisher (manual, one time)**

This cannot be scripted. On PyPI, under the project's publishing settings, add a
GitHub publisher with:

- Owner: `andyshinn`
- Repository: `scootscoot`
- Workflow: `publish.yml`
- Environment: `pypi`

Until this exists, `publish.yml` will fail at the upload step with an OIDC
error — that is expected, not a bug in the workflow.

---

## Manual verification against hardware

Nothing above touches a radio. Once Task 11 is done, verify on the GT3 Pro with
a short script (kept out of the repo — the library ships no CLI):

1. **Parked vehicle.** `poll()` returns a populated `battery`, with `vehicle`
   and `motor` as `None`, and `responding == {BoardRole.BMS1}`. Should complete
   in a few seconds, not thirty — if it is slow, the sleeping-board skip is not
   working.
2. **Powered-on vehicle.** `poll()` returns all three groups. Cross-check
   `battery.soc_percent` against `vehicle.battery_percent` and against the app.
3. **Odometer and range.** Compare against the app's display. They use different
   scales; a range in the hundreds of km means the scales got crossed.
4. **`identify()`** returns firmware versions matching the app.
5. **Phone-app contention.** Connect with the app, then call `poll()`. Expect
   `VehicleBusy` after three attempts, not a hang.
6. **Wrong password.** Expect `AuthenticationFailed`, promptly.
7. **Back-to-back polls.** Two `poll()` calls a minute apart both succeed, and
   the phone app can connect in between — proving no connection is held.

---

## Self-review notes

- **Spec coverage.** §4 architecture → Tasks 1–10 file layout. §5 profiles →
  Task 4. §5.1 GT3 data → Task 4. §6.1 crypto → Task 2. §6.2 framing → Task 3.
  §6.3 handshake → Task 7. §7.1 seam and §7.2 transport → Task 8. §7.3
  connection → Task 10. §8 public API → Tasks 9–10. §9 models and errors →
  Tasks 1 and 6. §10 testing → tests in Tasks 2–7. §11 packaging and CI →
  Tasks 1 and 11. §12 gotchas → each has a test or an explicit code comment.
- **Additions beyond the spec**, both recorded above: `UnknownBoard` /
  `UnknownRegister` (Task 1), and `choose_gatt_profile` extracted as a pure
  function so the both-services-present trap is unit-tested (Task 4).
- **Deliberately untested**: `transport.py`, `session.py`, `client.py`, per the
  spec's test strategy. The manual checklist above covers them.

