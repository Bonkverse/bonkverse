"""Avatar slots: the five skin slots on a bonk.io account."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class AvatarSlot:
    """One of a bonk.io account's avatar slots, 1 to 5.

    Construct with `AvatarSlot.parse(value)`, which returns None for anything
    that isn't a valid slot instead of raising.
    """

    number: int

    FIRST = 1
    LAST = 5
    # Used when neither the request nor the session says which slot to use.
    DEFAULT_NUMBER = 3

    def __post_init__(self):
        if not self.FIRST <= self.number <= self.LAST:
            raise ValueError(f"avatar slot must be {self.FIRST}-{self.LAST}, got {self.number}")

    @classmethod
    def parse(cls, value) -> AvatarSlot | None:
        """A slot from an int or numeric string (form field, bonk.io JSON), else None."""
        if isinstance(value, AvatarSlot):
            return value
        if isinstance(value, bool) or value is None:
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return cls(number) if cls.FIRST <= number <= cls.LAST else None

    @classmethod
    def default(cls) -> AvatarSlot:
        return cls(cls.DEFAULT_NUMBER)

    @classmethod
    def choose(cls, requested, active) -> AvatarSlot:
        """The slot to wear a skin in: the requested one if valid, else the
        player's active slot, else the default."""
        return cls.parse(requested) or cls.parse(active) or cls.default()

    def __int__(self) -> int:
        return self.number

    def __str__(self) -> str:
        return str(self.number)
