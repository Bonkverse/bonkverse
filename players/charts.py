"""Turning the replay API's player profile into what each profile tab draws.

Pure functions over plain data (no Django, no database), so each chart can be
tested with a hand-written profile. Server-drawn charts carry their sizes as
percentages the template passes to CSS as a custom property
(style="--bar: 42%") or as SVG coordinates; the interactive charts (Activity
week view, Level explorer) get compact data for a page script instead.
"""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote, urlencode

from . import converters

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
# A stretch with no replays for longer than this, across which the level
# rose, is drawn dashed: the level-ups happened somewhere in it, not on the
# day the player came back (design review).
GAP_DAYS = 14
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
    """/player/<name>/[tab/], with "." and ".." escaped (players/converters.py)."""
    segment = quote(converters.to_url(username), safe="")
    return f"/player/{segment}/" + (f"{tab}/" if tab else "")


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
    """The level over time as SVG paths, drawn as steps (levels only go up
    in steps): `line` for days with replays, `gaps` (dashed) across a gap of
    more than GAP_DAYS with no replays in which the level rose. None with
    fewer than two days."""
    points, best = [], 0
    for d, _, lv in _played(days):
        if lv:
            best = max(best, lv)
            points.append((d, best))
    if len(points) < 2:
        return None
    first, last = points[0][0], points[-1][0]
    span = max((last - first).days, 1)
    low, high = points[0][1], points[-1][1]
    rise = max(high - low, 1)

    def xy(d, lv):
        return width * (d - first).days / span, height - 6 - (height - 12) * (lv - low) / rise

    line, gaps, area = [], [], []
    prev = None
    for d, lv in points:
        x, y = xy(d, lv)
        if prev is None:
            line.append(f"M{x:.1f},{y:.1f}")
            area.append((x, y))
        elif (d - prev[0]).days > GAP_DAYS and lv != prev[3]:
            gaps.append(f"M{prev[1]:.1f},{prev[2]:.1f}L{x:.1f},{y:.1f}")
            line.append(f"M{x:.1f},{y:.1f}")
            area.append((x, y))
        else:
            line.append(f"L{x:.1f},{prev[2]:.1f}L{x:.1f},{y:.1f}")
            area += [(x, prev[2]), (x, y)]
        prev = (d, x, y, lv)
    return {
        "line": "".join(line),
        "gaps": "".join(gaps),
        "area": " ".join(
            [f"0,{height}"] + [f"{x:.1f},{y:.1f}" for x, y in area] + [f"{width},{height}"]
        ),
        "width": width,
        "height": height,
        "first_day": first,
        "last_day": last,
        "low": low,
        "high": high,
        "gained": high - low,
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
    """Compact data for player_level.js: [[day, level]], games per day,
    level-ups, and how many days without replays make a gap."""
    return {
        "gap_days": GAP_DAYS,
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
    """The last 53 weeks as columns of 7 days (Monday first), each day shaded
    0–4 by how many replays it had compared with the player's busier days
    (the colors come from the theme, players/css/profile.css). A week's
    `month` is the date to label it with when a month starts in it."""
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
            cells.append({"day": d, "games": g, "shade": shade, "future": d > today})
        # Label the week a month starts in ("Nov" over its column), like a
        # contribution grid. The oldest column only gets one if the next
        # month is at least 3 weeks away, so two labels never collide.
        first = next((c["day"] for c in cells if c["day"].day == 1), None)
        if w == 0 and first is None and (week_start + timedelta(days=21)).month == week_start.month:
            first = week_start
        weeks.append({"start": week_start, "cells": cells, "month": first})
        if first:
            months.append({"week": w, "label": first})
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


def mode_bars(modes):
    """Replays by mode as a bar list, most played first. Each bar is sized
    against the top mode so the smaller ones stay readable; the share of all
    replays is printed beside it."""
    total = sum(int(m["games"]) for m in modes)
    if not total:
        return []
    rows = sorted(modes, key=lambda m: -int(m["games"]))
    top = int(rows[0]["games"])
    return [
        {
            "label": mode_label(m.get("mode")),
            "games": int(m["games"]),
            "share": round(100 * int(m["games"]) / total),
            # "<1" rather than "0" for a mode they did play
            "share_label": str(round(100 * int(m["games"]) / total) or "<1"),
            "bar": _pct(int(m["games"]), top),
        }
        for m in rows
        if int(m["games"])
    ]


def room_split(rooms):
    """1v1 / free-for-all / teams / alone as one stacked bar. `only` names
    the one kind when there's just one (the page then says so instead of
    drawing a full bar), and the custom/quick play bar is left out the same
    way when one side is 0 (design review)."""
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
            "color": f"var(--site-series-{i + 1})",
        }
        for i, k in enumerate(ROOM_ORDER)
        if int(rooms.get(k) or 0)
    ]
    quick = _pct(int(rooms.get("quickplay") or 0), total)
    return {
        "parts": parts,
        "only": parts[0]["label"] if len(parts) == 1 else None,
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
