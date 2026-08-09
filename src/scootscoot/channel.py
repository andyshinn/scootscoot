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
