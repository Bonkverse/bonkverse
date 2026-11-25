"""Roles shown on a few known accounts' profiles: a short label and a line
explaining it (players/templates/players/_layout.html).

Owns: which bonk.io names have a role, and its text.
Does not own: anything an account can do; a role is only shown.

Names compare ignoring case, the way bonk.io names do. To add or change a
role, edit ROLES and its test (tests/test_player_roles.py).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    label: str
    description: str


ROLES = {
    "butdogebot": Role(
        label="Bot",
        description="This is a Human-Controlled bot, and is not affiliated with Bonk.io",
    ),
}


def role_for(username: str | None) -> Role | None:
    """The role shown on this player's profile, or None."""
    return ROLES.get((username or "").lower())
