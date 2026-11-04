"""bonk.io usernames: validation and normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ALLOWED = re.compile(r"^[A-Za-z0-9 _]+$")
_GUEST_PREFIXES = ("guest", "new player")


class InvalidUsername(ValueError):
    """The text can't be a registered bonk.io username. The message is user-facing."""


@dataclass(frozen=True)
class BonkUsername:
    """A registered bonk.io username, exactly as bonk.io spells it.

    bonk.io usernames are 3-35 characters of letters, digits, spaces and
    underscores, and compare case-insensitively. Guest names ("Guest1234",
    "New Player") are not registered accounts.
    """

    value: str

    MIN_LENGTH = 3
    MAX_LENGTH = 35

    def __post_init__(self):
        self.validate(self.value)

    @classmethod
    def validate(cls, value: str) -> None:
        """Raise InvalidUsername with a user-facing message if `value` isn't valid."""
        if not value:
            raise InvalidUsername("Username is required.")
        if len(value) < cls.MIN_LENGTH:
            raise InvalidUsername(f"Username must be at least {cls.MIN_LENGTH} characters long.")
        if len(value) > cls.MAX_LENGTH:
            raise InvalidUsername(f"Username must be at most {cls.MAX_LENGTH} characters long.")
        if not _ALLOWED.match(value):
            raise InvalidUsername(
                "Username can only contain letters, numbers, spaces, and underscores."
            )
        if is_guest(value):
            raise InvalidUsername("Guest accounts are not allowed.")

    @property
    def key(self) -> str:
        """Case-insensitive form, for comparing and looking up usernames."""
        return self.value.lower()

    def __str__(self) -> str:
        return self.value


def is_guest(value: str) -> bool:
    """True for bonk.io guest names, which aren't registered accounts."""
    return value.lower().startswith(_GUEST_PREFIXES)
