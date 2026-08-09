"""The shipped profile registry. Selection is explicit -- nothing is guessed."""

from __future__ import annotations

from scootscoot.profiles.gt3_pro import GT3_PRO
from scootscoot.profiles.types import DeviceProfile

#: Every profile this release ships. Consumers render this for a model picker.
ALL: tuple[DeviceProfile, ...] = (GT3_PRO,)

_BY_KEY = {profile.key: profile for profile in ALL}


def get(key: str) -> DeviceProfile:
    """Look up a profile by its key.

    Raises a bare ``KeyError`` for a key this release does not ship -- the one
    deliberate exception to the rule that every error scootscoot raises derives
    from ``ScootScootError``. A profile key is a compile-time choice from
    ``ALL``, not a runtime vehicle condition, and a mapping lookup that misses
    should say so in the language of mappings.
    """
    return _BY_KEY[key]
