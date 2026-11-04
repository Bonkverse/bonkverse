"""bonk.io usernames: what bonk.io actually allows, as seen in real data.

bonk.io's rules for *new* accounts (letters, numbers, spaces, underscores;
at most 15 characters; no leading space or underscore; no double spaces; no
"Chaz") have changed over the years, and older accounts keep names that
break them. A 2026-11-03 audit of names stored from bonk.io logins and
friend lists (docs/bonk/accounts.md) found real accounts with:

- 1 to 35 characters (35 was an older limit; 20 another common one)
- punctuation such as . ! - ; : [ ] ( ) * $ ' < / & ?
- leading, trailing and repeated spaces
- names starting with "Guest" (registered accounts, not guests)

So a name that bonk.io gives us is always accepted exactly as spelled, spaces
included. Bonkverse never creates bonk.io accounts, so it never needs the
new-account rules.
"""

from __future__ import annotations

from dataclasses import dataclass

# Longest name seen in real data is 35; leave headroom rather than reject a
# real account. BonkPlayer.username is 255 wide.
MAX_LENGTH = 64


class InvalidUsername(ValueError):
    """The text can't be a bonk.io username. The message is user-facing."""


@dataclass(frozen=True)
class BonkUsername:
    """A bonk.io username, exactly as bonk.io spells it.

    Never trimmed or re-cased: " Name" (leading space) and "Name" can be
    different accounts. Compare with `.key`, which is
    case-insensitive but keeps spaces.
    """

    value: str

    def __post_init__(self):
        self.validate(self.value)

    @classmethod
    def validate(cls, value: str) -> None:
        """Raise InvalidUsername if `value` can't be a bonk.io username at all.

        Only rejects what no bonk.io account can have: empty, absurdly long, or
        containing control characters (newlines, tabs, NUL).
        """
        if not value:
            raise InvalidUsername("Username is required.")
        if len(value) > MAX_LENGTH:
            raise InvalidUsername(f"Username must be at most {MAX_LENGTH} characters long.")
        if any(not ch.isprintable() for ch in value):
            raise InvalidUsername("Username contains characters bonk.io doesn't allow.")

    @property
    def key(self) -> str:
        """Case-insensitive form for comparing and looking up usernames.

        # BONK: whether bonk.io treats names case-insensitively is not yet
        # verified; spaces are kept because they distinguish real accounts.
        """
        return self.value.casefold()

    def __str__(self) -> str:
        return self.value
