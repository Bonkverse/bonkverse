"""Discord ids, shared by every app that stores one (skins, accounts)."""

from __future__ import annotations


def discord_id_or_none(value) -> int | None:
    """A Discord user id as an int, or None for anything that isn't one.

    Discord ids are 64-bit snowflakes; the bot may send them as int or string.
    """
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 < number < 2**63 else None
