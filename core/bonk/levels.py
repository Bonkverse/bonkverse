"""bonk.io levels and XP: the game's own formulas.

BONK: total XP at level L is 100·(L−1)², so level L→L+1 takes 100·(2L−1)
XP. In the HTML5 game a won round gives 100 XP and a lost one 0, in custom
rooms and quick play alike, and an account can earn at most 18,000 XP a day
(raised from 12,000 in 2023). Source: bonkio.fandom.com/wiki/Levels.

Replays show a player's level but not their XP, so for anyone but a
signed-in player we only know the XP range their level covers.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isqrt

XP_PER_WIN = 100
DAILY_XP_CAP = 18_000
WINS_PER_DAY_AT_CAP = DAILY_XP_CAP // XP_PER_WIN


def xp_for_level(level: int) -> int:
    """Total XP an account has on reaching `level` (level 1 = 0 XP)."""
    level = max(1, int(level))
    return 100 * (level - 1) ** 2


def level_for_xp(xp: int) -> int:
    """The level an account with `xp` total XP is at."""
    xp = max(0, int(xp))
    # floor(sqrt(xp / 100)) == isqrt(xp // 100) for non-negative integers
    return isqrt(xp // 100) + 1


@dataclass(frozen=True)
class Progress:
    level: int
    xp: int
    into_level: int  # XP earned since reaching `level`
    level_size: int  # XP from `level` to `level + 1`

    @property
    def to_next(self) -> int:
        return self.level_size - self.into_level

    @property
    def percent(self) -> float:
        return round(100 * self.into_level / self.level_size, 2)


def progress(xp: int) -> Progress:
    level = level_for_xp(xp)
    start = xp_for_level(level)
    return Progress(
        level=level,
        xp=max(0, int(xp)),
        into_level=max(0, int(xp)) - start,
        level_size=xp_for_level(level + 1) - start,
    )


@dataclass(frozen=True)
class Goal:
    xp_needed: int
    wins_needed: int
    days_at_cap: int


def goal(from_xp: int, to_xp: int) -> Goal:
    """What it takes to go from one XP total to another: XP, won rounds,
    and days if every day reached the daily XP cap."""
    needed = max(0, int(to_xp) - int(from_xp))
    return Goal(
        xp_needed=needed,
        wins_needed=ceil(needed / XP_PER_WIN),
        days_at_cap=ceil(needed / DAILY_XP_CAP),
    )
