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

import string
from dataclasses import dataclass

# Longest name seen in real data is 35; leave headroom rather than reject a
# real account. BonkPlayer.username is 255 wide.
MAX_LENGTH = 64

_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def fold(name: str) -> str:
    """`name` with A-Z lowercased and every other character left as it is.

    The one rule for "are these two spellings the same bonk.io account":
    capitalization of the 26 English letters is ignored, nothing else.

    Not str.lower(), str.casefold() or the database's UPPER()/LOWER(): each
    of those also turns some non-English letters into English ones, and they
    disagree about which. Postgres's UPPER() (what `__iexact` compares with)
    makes "ı" (dotless i, U+0131) an "I" and "ſ" (long s, U+017F) an "S", so
    "admın" matched the account "admin". Python's lower() makes the Kelvin
    sign (U+212A, drawn like a capital K) a "k", so a name written with it
    matched a player the account lookup didn't. A name that is only *almost*
    someone's must never be treated as theirs.
    """
    return name.translate(_ASCII_LOWER)


def same_name(a: str | None, b: str | None) -> bool:
    """Whether two spellings name the same bonk.io account (see `fold`)."""
    return a is not None and b is not None and fold(a) == fold(b)


class InvalidUsername(ValueError):
    """The text can't be a bonk.io username. The message is user-facing."""


@dataclass(frozen=True)
class BonkUsername:
    """A bonk.io username, exactly as bonk.io spells it.

    Never trimmed or re-cased: " Name" (leading space) and "Name" can be
    different accounts, while "name" and "NAME" cannot (bonk.io usernames are
    unique case-insensitively). Compare with `.key`, which ignores case but
    keeps spaces.
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

        # BONK: usernames are unique case-insensitively: registering
        # "the saucy tulip" fails as taken when "The Saucy Tulip" exists
        # (verified 2026-11-03). Spaces are kept: they distinguish accounts.

        Only A-Z are folded (see `fold`).
        """
        return fold(self.value)

    def __str__(self) -> str:
        return self.value
