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
