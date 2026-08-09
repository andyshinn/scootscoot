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
