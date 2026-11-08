"""Turning the replay API's player profile into what each profile tab draws.

Pure functions over plain data (no Django, no database), so each chart can be
tested with a hand-written profile. Server-drawn charts carry their sizes as
percentages the template passes to CSS as a custom property
(style="--bar: 42%") or as SVG coordinates; the interactive charts (Activity
week view, Level explorer) get compact data for a page script instead.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from urllib.parse import quote, urlencode

MODE_LABELS = {
    "b": "Classic",
    "ar": "Arrows",
    "ard": "Death Arrows",
    "sp": "Grapple",
    "v": "VTOL",
    "f": "Football",
    "bs": "Simple",
}
ROOM_LABELS = {"1v1": "1v1", "ffa": "Free-for-all", "teams": "Teams", "solo": "Alone"}
ROOM_ORDER = ["1v1", "ffa", "teams", "solo"]
# Series colors: teal, blue, orange, then quieter ones. Neighbours differ in
# lightness too, so they stay apart without relying on hue.
SERIES = ["#47d8c4", "#90b7ff", "#ffb454", "#c79bff", "#ff8a8a", "#d8e36a", "#8fa3b8"]
HEAT = ["#101a25", "#1d4f4d", "#2a7d74", "#38ab9c", "#47d8c4"]
REPLAY_MILESTONES = [100, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]
COMEBACK_DAYS = 30


def mode_label(code):
    if not code:
        return "Unknown"
    return MODE_LABELS.get(code, code)


def _pct(value, top):
    return round(100 * value / top, 1) if top else 0


def _day(text):
    try:
        return date.fromisoformat(str(text)[:10])
    except (TypeError, ValueError):
        return None


def _played(days):
    """[(date, games, level)] for days with replays, oldest first."""
    rows = []
    for p in days:
        d = _day(p.get("day"))
        if d and int(p.get("games") or 0) > 0:
            rows.append((d, int(p["games"]), p.get("level")))
    return sorted(rows)


def profile_path(username, tab=""):
    return f"/player/{quote(username, safe='')}/" + (f"{tab}/" if tab else "")


class ReplayLinks:
    """URLs on the replay site (routes from ReplayRenderer's browser/app/router.js)."""

    def __init__(self, base_url):
        self.base = base_url.rstrip("/")

    def watch(self, cycle, replay_id):
        return f"{self.base}/watch/{cycle}/{replay_id}"

    def player_replays(self, username):
        return f"{self.base}/search?{urlencode({'with': username})}"

    def map_replays(self, mapid, username=None):
        params = {"map": mapid}
        if username:
            params["with"] = username
        return f"{self.base}/search?{urlencode(params)}"

    def together(self, username, other):
        return f"{self.base}/search?{urlencode([('with', username), ('with', other)])}"

    def thumbnail(self, mapid):
        return f"{self.base}/api/map/{mapid}/thumbnail.svg"


# ── Level ────────────────────────────────────────────────────────


def sparkline(days, width=600, height=110):
    """Highest level per day as SVG points; None with fewer than two days."""
    points = [(d, lv) for d, _, lv in _played(days) if lv]
    if len(points) < 2:
        return None
    first, last = points[0][0], points[-1][0]
    span = max((last - first).days, 1)
    low = min(lv for _, lv in points)
    high = max(lv for _, lv in points)
    rise = max(high - low, 1)

    def xy(d, lv):
        x = width * (d - first).days / span
        y = height - 6 - (height - 12) * (lv - low) / rise
        return f"{x:.1f},{y:.1f}"

    line = " ".join(xy(d, lv) for d, lv in points)
    return {
        "line": line,
        "area": f"0,{height} {line} {width},{height}",
        "width": width,
        "height": height,
        "first_day": first,
        "last_day": last,
        "low": low,
        "high": high,
        "gained": high - points[0][1],
    }


def level_ups(profile, links, limit=None):
    """Level-ups newest first, with when, how many replays and days it took."""
    ups = profile.get("level_ups") or []
    rows = []
    prev_day = _day(((profile.get("summary") or {}).get("first") or {}).get("day"))
    for u in ups:
        d = _day(u.get("day"))
        rows.append(
            {
                "level": u["level"],
                "day": d,
                "at": u.get("at"),
                "replays": u.get("replays"),
                "days": (d - prev_day).days if d and prev_day else None,
                "url": links.watch(u["cycle"], u["id"]),
            }
        )
        prev_day = d or prev_day
    rows.reverse()
    return rows[:limit] if limit else rows


def level_script_data(profile):
    """Compact data for player_level.js: [[day, level]], games per day and level-ups."""
    return {
        "days": [[p["day"], p["level"]] for p in profile.get("days", []) if p.get("level")],
        "games": [[p["day"], p["games"]] for p in profile.get("days", [])],
        "ups": [
            {
                "level": u["level"],
                "day": u.get("day"),
                "at": u.get("at"),
                "replays": u.get("replays"),
            }
            for u in profile.get("level_ups") or []
        ],
    }


# ── Activity ─────────────────────────────────────────────────────


def heatmap(days, today):
    """The last 53 weeks as columns of 7 days (Monday first), colored by how
    many replays that day had compared with the player's busier days."""
    counts = {d: g for d, g, _ in _played(days)}
    start = today - timedelta(days=today.weekday() + 52 * 7)
    nonzero = sorted(g for d, g in counts.items() if start <= d <= today)
    if nonzero:
        cuts = [nonzero[int(len(nonzero) * q)] for q in (0.25, 0.5, 0.75)]
    else:
        cuts = [1, 2, 3]

    weeks, months = [], []
    for w in range(53):
        week_start = start + timedelta(days=7 * w)
        cells = []
        for i in range(7):
            d = week_start + timedelta(days=i)
            g = counts.get(d, 0)
            shade = 0 if g == 0 or d > today else 1 + sum(g > c for c in cuts)
            cells.append({"day": d, "games": g, "color": HEAT[shade], "future": d > today})
        weeks.append({"start": week_start, "cells": cells})
        if w == 0 or week_start.month != (week_start - timedelta(days=7)).month:
            months.append({"week": w, "label": week_start})
    return {
        "weeks": weeks,
        "newest_first": weeks[::-1],
        "months": months,
        "days_played": len(nonzero),
    }


def streaks(days, today):
    """Current and longest run of consecutive days with replays."""
    longest, longest_end, run, prev = 0, None, 0, None
    for d, _, _ in _played(days):
        run = run + 1 if prev and (d - prev).days == 1 else 1
        if run > longest:
            longest, longest_end = run, d
        prev = d
    current = run if prev and (today - prev).days <= 1 else 0
    return {"current": current, "longest": longest, "longest_end": longest_end}


def minutes_label(minutes):
    if minutes is None:
        return None
    minutes = int(round(float(minutes)))
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} m" if minutes % 60 else f"{minutes // 60} h"


def activity_script_data(profile):
    """Compact data for player_activity.js. `days` counts every replay by its
    (UTC or estimated) day; `hours` are live replays per UTC hour, which the
    script moves into the viewer's time zone."""
    return {
        "days": [[p["day"], p["games"]] for p in profile.get("days", [])],
        "hours": [[h["t"], h["games"]] for h in profile.get("live_hours") or []],
    }


def milestones(profile, links, *, show_level=True, show_activity=True):
    """A short story of the player, newest first: first replay, replay counts,
    every 25th level, and comebacks after a month or more away."""
    out = []
    first = (profile.get("summary") or {}).get("first") or {}
    if show_activity and first.get("day"):
        out.append(
            {
                "day": _day(first["day"]),
                "what": "First replay in the archive",
                "url": links.watch(first["cycle"], first["id"]),
            }
        )
    if show_activity:
        total, marks = 0, iter(REPLAY_MILESTONES)
        mark, prev = next(marks), None
        for d, g, _ in _played(profile.get("days", [])):
            if prev and (d - prev).days >= COMEBACK_DAYS:
                out.append({"day": d, "what": f"Back after {(d - prev).days} days away"})
            total += g
            while mark and total >= mark:
                out.append({"day": d, "what": f"{mark:,}th replay"})
                mark = next(marks, None)
            prev = d
    if show_level:
        for u in profile.get("level_ups") or []:
            if u["level"] % 25 == 0:
                out.append(
                    {
                        "day": _day(u.get("day")),
                        "what": f"Reached level {u['level']}",
                        "url": links.watch(u["cycle"], u["id"]),
                    }
                )
    return sorted((m for m in out if m["day"]), key=lambda m: m["day"], reverse=True)


# ── Maps and modes ───────────────────────────────────────────────


def mode_ring(modes, size=200, outer=92, inner=58):
    """Donut slices as SVG paths. Tiny modes get a minimum sweep so they can
    still be pointed at; the legend has the true share."""
    total = sum(int(m["games"]) for m in modes)
    if not total:
        return {"slices": [], "total": 0, "size": size}
    min_sweep = 0.12
    raw = [int(m["games"]) / total * 2 * math.pi for m in modes]
    small = sum(1 for r in raw if r < min_sweep)
    spare = 2 * math.pi - small * min_sweep
    big_total = sum(r for r in raw if r >= min_sweep) or 1
    sweeps = [min_sweep if r < min_sweep else r / big_total * spare for r in raw]
    c = size / 2

    def pt(radius, angle):
        return f"{c + radius * math.cos(angle):.2f} {c + radius * math.sin(angle):.2f}"

    slices, angle = [], -math.pi / 2
    for i, (m, sweep) in enumerate(zip(modes, sweeps, strict=True)):
        a0 = angle
        a1 = angle + sweep - (0.03 if len(modes) > 1 else 0.0001)
        angle += sweep
        large = 1 if (a1 - a0) > math.pi else 0
        games = int(m["games"])
        slices.append(
            {
                "d": (
                    f"M {pt(outer, a0)} A {outer} {outer} 0 {large} 1 {pt(outer, a1)} "
                    f"L {pt(inner, a1)} A {inner} {inner} 0 {large} 0 {pt(inner, a0)} Z"
                ),
                "color": SERIES[i % len(SERIES)],
                "label": mode_label(m.get("mode")),
                "games": games,
                "share": round(100 * games / total),
            }
        )
    return {"slices": slices, "total": total, "size": size}


def room_split(rooms):
    """1v1 / free-for-all / teams / alone as one stacked bar."""
    if not rooms:
        return None
    total = sum(int(rooms.get(k) or 0) for k in ROOM_ORDER)
    if not total:
        return None
    parts = [
        {
            "key": k,
            "label": ROOM_LABELS[k],
            "games": int(rooms.get(k) or 0),
            "share": _pct(int(rooms.get(k) or 0), total),
            "color": SERIES[i],
        }
        for i, k in enumerate(ROOM_ORDER)
        if int(rooms.get(k) or 0)
    ]
    quick = _pct(int(rooms.get("quickplay") or 0), total)
    return {
        "parts": parts,
        "total": total,
        "quickplay_share": quick,
        "custom_share": round(100 - quick, 1),
        "median_players": rooms.get("median_players"),
        "distinct_maps": rooms.get("distinct_maps"),
    }


def map_rows(maps, links):
    return [
        {
            "name": m.get("name") or f"Map {m['mapid']}",
            "mapid": str(m["mapid"]),
            "games": int(m["games"]),
            "last_day": _day(m.get("last_day")),
            "thumbnail": links.thumbnail(m["mapid"]),
        }
        for m in maps
    ]


def map_detail(detail, links, username, total_games):
    """The selected map on the Maps tab."""
    games = int(detail.get("games") or 0)
    return {
        "name": detail.get("name") or f"Map {detail['mapid']}",
        "mapid": str(detail["mapid"]),
        "games": games,
        "share": max(1, round(100 * games / total_games)) if total_games and games else 0,
        "first_day": _day(detail.get("first_day")),
        "last_day": _day(detail.get("last_day")),
        "rooms": room_split(detail.get("rooms")),
        "modes": sorted(
            ((mode_label(k), int(v)) for k, v in (detail.get("modes") or {}).items()),
            key=lambda kv: -kv[1],
        ),
        "people": people_rows(detail.get("played_with") or [], links, username),
        "thumbnail": links.thumbnail(detail["mapid"]),
        "replays_url": links.map_replays(detail["mapid"], username),
    }


# ── People ───────────────────────────────────────────────────────


def people_rows(people, links, username):
    top = max((int(p["games"]) for p in people), default=0)
    return [
        {
            "username": p["username"],
            "initials": p["username"].strip()[:2].upper() or "?",
            "games": int(p["games"]),
            "same_team": p.get("same_team"),
            "bar": _pct(int(p["games"]), top),
            "profile_path": profile_path(p["username"]),
            "replays_url": links.together(username, p["username"]),
        }
        for p in people
    ]


# ── Whole profile ────────────────────────────────────────────────


def summary(profile):
    s = profile["summary"]
    return {
        **s,
        "first_day": _day((s.get("first") or {}).get("day")),
        "last_day": _day((s.get("last") or {}).get("day")),
    }


def main_mode(modes):
    total = sum(int(m["games"]) for m in modes)
    if not total:
        return None
    top = max(modes, key=lambda m: int(m["games"]))
    return {"label": mode_label(top.get("mode")), "share": round(100 * int(top["games"]) / total)}
