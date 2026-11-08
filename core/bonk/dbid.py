"""Estimating when a bonk.io account was made from its ID (DBID).

BONK: account IDs count up as accounts are created, so an ID falls between
two accounts whose creation dates the community has recorded
(data/dbid_dates.json, merged from shaunx777/dbid2date and bonkonauts). The
estimate is a straight line between those two known points, the same method
those tools use. Past the newest known point we continue at the newest
pace, never later than today, and say it's extrapolated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "dbid_dates.json"


@dataclass(frozen=True)
class Estimate:
    day: date
    extrapolated: bool  # beyond the newest known point


@lru_cache(maxsize=1)
def known_points() -> tuple[tuple[int, date], ...]:
    """(dbid, date) pairs, oldest first."""
    raw = json.loads(DATA.read_text(encoding="utf-8"))["points"]
    return tuple((int(n), date.fromisoformat(d)) for n, d in raw)


def estimate(dbid: int | None, today: date | None = None) -> Estimate | None:
    """When account `dbid` was probably created; None for no or a bad ID."""
    if dbid is None or int(dbid) < 1:
        return None
    dbid = int(dbid)
    points = known_points()
    today = today or date.today()

    for (n0, d0), (n1, d1) in zip(points, points[1:], strict=False):
        if n0 <= dbid <= n1:
            return Estimate(_between(dbid, n0, d0, n1, d1), extrapolated=False)

    (n0, d0), (n1, d1) = points[-2], points[-1]
    day = min(_between(dbid, n0, d0, n1, d1), today)
    return Estimate(max(day, d1), extrapolated=True)


def _between(dbid, n0, d0, n1, d1):
    if n1 == n0:
        return d0
    days = (d1 - d0).days * (dbid - n0) / (n1 - n0)
    return d0 + timedelta(days=round(days))


def id_for_day(day: date) -> int:
    """About the first account ID made on `day` (the inverse of `estimate`),
    for "joined between" filters. Before the oldest known point it's 1; past
    the newest it continues at the newest pace."""
    points = known_points()
    if day <= points[0][1]:
        return 1
    for (n0, d0), (n1, d1) in zip(points, points[1:], strict=False):
        if d0 <= day <= d1:
            return _id_between(day, n0, d0, n1, d1)
    (n0, d0), (n1, d1) = points[-2], points[-1]
    return _id_between(day, n0, d0, n1, d1)


def _id_between(day, n0, d0, n1, d1):
    if d1 == d0:
        return n0
    return round(n0 + (n1 - n0) * (day - d0).days / (d1 - d0).days)


def timeline():
    """The known points as [[dbid, "YYYY-MM-DD"], ...] for charts."""
    return [[n, d.isoformat()] for n, d in known_points()]
