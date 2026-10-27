"""Read every register in a profile and record exactly what comes back.

A field tool for checking the profile's assumptions against real hardware --
above all, which boards answer while the vehicle is switched off, and what an
"answer" from a sleeping board actually looks like. ScooterSession.read_raw
keeps only the first frame and reduces anything unexpected to None; this keeps
every frame that arrives after each request, decrypted and parsed, with a note
of whether it is a valid reply (read_raw only ever sees the first one).

    uv run python scripts/probe_registers.py AA:BB:CC:DD:EE:FF --out parked.json

The 16-byte password is read as hex from --password, then $SCOOTSCOOT_PASSWORD,
and is otherwise prompted for. Run it once with the scooter off and once with it
on, and compare. --rounds repeats the sweep on the same connection, which shows
whether a board wakes partway through or a counter such as rRuntime is ticking.

The output holds decrypted register replies and the vehicle serial, but no
password and no handshake frames.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bleak import BleakScanner

import scootscoot
from scootscoot import Credentials, Scooter, ScooterSession, profiles
from scootscoot.crypto import CryptoStatus, NbCrypto
from scootscoot.decode import decode
from scootscoot.framing import CMD_READ_RESP, build_read, parse_frame
from scootscoot.profiles.types import DeviceProfile, Register

#: How long to keep listening after the first frame, for stragglers.
DEFAULT_LINGER = 0.3


async def exchange(
    session: ScooterSession,
    board: int,
    index: int,
    length: int,
    *,
    timeout: float,
    linger: float,
    register: Register | None = None,
) -> dict[str, Any]:
    """Send one read and describe every frame that arrives in response."""
    # Deliberately reaches past read_raw: it stops at the first frame and hides
    # why a reply was rejected, which is the very thing this script records.
    channel = session._channel
    crypto = session._crypto

    channel.drain()
    started = time.monotonic()
    await channel.send(crypto.encrypt(build_read(board, index, length, sync2=session._sync2)))

    frames: list[dict[str, Any]] = []
    wait = timeout
    while True:
        try:
            raw = await channel.recv(wait)
        except TimeoutError:
            break
        elapsed_ms = round((time.monotonic() - started) * 1000)
        frames.append(describe(raw, board, index, length, elapsed_ms, crypto, register))
        wait = linger

    return {
        "board": f"0x{board:02X}",
        "index": f"0x{index:02X}",
        "length": length,
        "register": register.name if register else None,
        "frames": frames,
    }


def describe(
    raw: bytes,
    board: int,
    index: int,
    length: int,
    elapsed_ms: int,
    crypto: NbCrypto,
    register: Register | None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"elapsed_ms": elapsed_ms, "wire_length": len(raw)}
    try:
        plaintext, status = crypto.decrypt(raw)
    except ValueError as err:
        entry["error"] = str(err)
        return entry

    entry["status"] = status.name
    entry["plaintext"] = plaintext.hex()
    frame = parse_frame(plaintext)
    if frame is None:
        entry["error"] = "unparseable"
        return entry

    entry.update(
        board=f"0x{frame.board_id:02X}",
        cmd=f"0x{frame.cmd:02X}",
        index=f"0x{frame.index:02X}",
        data=frame.data.hex(),
    )
    problems = []
    if status is not CryptoStatus.OK:
        problems.append(f"verification {status.name}")
    if frame.board_id != board:
        problems.append("wrong board")
    if frame.cmd != CMD_READ_RESP:
        problems.append("not a read response")
    if frame.index != index:
        problems.append("wrong index")
    if len(frame.data) < length:
        problems.append(f"{len(frame.data)} of {length} bytes")
    entry["accepted"] = not problems
    if problems:
        entry["rejected_because"] = problems
    elif register is not None:
        entry["decoded"] = jsonable(decode(register, frame.data))
    return entry


async def sweep(
    session: ScooterSession,
    profile: DeviceProfile,
    *,
    timeout: float,
    linger: float,
) -> list[dict[str, Any]]:
    results = []
    for register in profile.registers:
        board = profile.board(register.board).address
        result = await exchange(
            session,
            board,
            register.index,
            register.length,
            timeout=timeout,
            linger=linger,
            register=register,
        )
        result["role"] = str(register.board)
        print_result(result)
        results.append(result)
    return results


async def sweep_boards(
    session: ScooterSession, *, index: int, timeout: float, linger: float
) -> list[dict[str, Any]]:
    results = []
    for address in range(256):
        result = await exchange(session, address, index, 2, timeout=timeout, linger=linger)
        if result["frames"]:
            print_result(result)
            results.append(result)
    return results


def print_result(result: dict[str, Any]) -> None:
    label = f"{result.get('role', ''):>4} {result['board']}:{result['index']} "
    label += f"{result['register'] or '':<22}"
    if not result["frames"]:
        print(f"{label} timeout")
        return
    for number, frame in enumerate(result["frames"]):
        prefix = label if number == 0 else " " * len(label)
        if "error" in frame and "cmd" not in frame:
            print(f"{prefix} {frame['error']} ({frame.get('plaintext', '')})")
            continue
        detail = (
            f"from {frame['board']} cmd {frame['cmd']} idx {frame['index']} "
            f"data [{frame['data']}] {frame['elapsed_ms']}ms"
        )
        if frame["accepted"]:
            value = frame.get("decoded")
            print(f"{prefix} ok   {detail}" + (f" = {value}" if value is not None else ""))
        else:
            print(f"{prefix} REJECT {detail}: {', '.join(frame['rejected_because'])}")


def jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, frozenset | set):
        return sorted(str(item) for item in value)
    if isinstance(value, tuple | list):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def password_from(args: argparse.Namespace) -> bytes:
    text = (
        args.password
        or os.environ.get("SCOOTSCOOT_PASSWORD")
        or getpass.getpass("Password (32 hex characters): ")
    )
    try:
        return bytes.fromhex(text.strip())
    except ValueError:
        sys.exit("the password must be hex, e.g. 000102030405060708090a0b0c0d0e0f")


async def run(args: argparse.Namespace) -> dict[str, Any]:
    profile = profiles.get(args.profile)
    credentials = Credentials(password=password_from(args))

    print(f"scanning for {args.address} ...")
    device = await BleakScanner.find_device_by_address(args.address, timeout=args.scan_timeout)
    if device is None:
        sys.exit(f"{args.address} was not seen within {args.scan_timeout:.0f}s")

    scooter = Scooter(device, profile, credentials, device_name=args.name)
    report: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "library_version": scootscoot.__version__,
        "profile": profile.key,
        "address": args.address,
        "note": args.note,
        "settings": {
            "timeout": args.timeout,
            "linger": args.linger,
            "rounds": args.rounds,
            "interval": args.interval,
        },
        "rounds": [],
    }

    async with scooter.session() as session:
        report["serial"] = session.serial
        print(f"connected to {session.serial}")
        for number in range(args.rounds):
            if number:
                print(f"\nwaiting {args.interval:.0f}s")
                await asyncio.sleep(args.interval)
            print(f"\n--- round {number + 1} of {args.rounds} ---")
            started = datetime.now(UTC).isoformat()
            results = await sweep(session, profile, timeout=args.timeout, linger=args.linger)
            report["rounds"].append({"started_at": started, "reads": results})

        if args.sweep_boards:
            print(f"\n--- board sweep at index 0x{args.sweep_index:02X} ---")
            report["board_sweep"] = await sweep_boards(
                session, index=args.sweep_index, timeout=args.sweep_timeout, linger=args.linger
            )

        print("\n--- library poll() ---")
        state = await session.poll()
        report["poll"] = jsonable(asdict(state))
        print(json.dumps(report["poll"], indent=2))

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("address", help="BLE address (a UUID on macOS)")
    parser.add_argument("--password", help="16-byte password as hex")
    parser.add_argument("--name", help="BLE device name, if the scan does not report it")
    parser.add_argument("--profile", default="gt3_pro", help="profile key (default: gt3_pro)")
    parser.add_argument("--out", type=Path, help="write the full capture as JSON here")
    parser.add_argument("--note", help="free text saved with the capture, e.g. 'off, unplugged'")
    parser.add_argument("--rounds", type=int, default=1, help="sweeps on one connection")
    parser.add_argument("--interval", type=float, default=10.0, help="seconds between rounds")
    parser.add_argument("--timeout", type=float, default=2.0, help="seconds to wait per read")
    parser.add_argument("--linger", type=float, default=DEFAULT_LINGER)
    parser.add_argument("--scan-timeout", type=float, default=20.0)
    parser.add_argument(
        "--sweep-boards",
        action="store_true",
        help="also probe all 256 board addresses (about two minutes at the default timeout)",
    )
    parser.add_argument("--sweep-index", type=lambda text: int(text, 0), default=0x10)
    parser.add_argument("--sweep-timeout", type=float, default=0.5)
    parser.add_argument("--debug", action="store_true", help="DEBUG logging for scootscoot")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.debug:
        # Never the wire logger: it would print handshake frames.
        logging.getLogger("scootscoot").setLevel(logging.DEBUG)

    report = asyncio.run(run(args))
    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
