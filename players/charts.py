"""Turning the replay API's player profile into what the page draws.

Pure functions over plain data (no Django, no database), so each chart can be
tested with a hand-written profile. Bars carry their size as a percentage
the template passes to CSS as a custom property (style="--bar: 42%"); the
level chart is SVG polyline points.
"""

from __future__ import annotations

from datetime import date
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
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Level chart drawing area, in SVG user units (the SVG scales to fit).
CHART_W, CHART_H, CHART_PAD = 600, 160, 8


def mode_label(code):
    if not code:
        return "Unknown"
    return MODE_LABELS.get(code, code)


def _pct(value, top):
    return round(100 * value / top, 1) if top else 0


def _day(text):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def level_chart(days):
    """Highest level seen per day as an SVG line; None with fewer than two days."""
    points = [
        (d, p["level"]) for p in days if (d := _day(p.get("day"))) and p.get("level") is not None
    ]
    if len(points) < 2:
        return None

    first, last = points[0][0], points[-1][0]
    span = max((last - first).days, 1)
    low = min(level for _, level in points)
    high = max(level for _, level in points)
    rise = max(high - low, 1)

    def xy(day, level):
        x = CHART_PAD + (CHART_W - 2 * CHART_PAD) * (day - first).days / span
        y = CHART_H - CHART_PAD - (CHART_H - 2 * CHART_PAD) * (level - low) / rise
        return f"{x:.1f},{y:.1f}"

    return {
        "points": " ".join(xy(d, level) for d, level in points),
        "width": CHART_W,
        "height": CHART_H,
        "low": low,
        "high": high,
        "first_day": first,
        "last_day": last,
        "gained": high - points[0][1],
    }


def monthly_games(days):
    """Games per calendar month, oldest first, as bars (empty months included)."""
    months = {}
    for p in days:
        d = _day(p.get("day"))
        if d:
            key = (d.year, d.month)
            months[key] = months.get(key, 0) + int(p.get("games") or 0)
    if not months:
        return []
    top = max(months.values())
    # Every month from the first to the last, so quiet months show as gaps.
    (y, m), last = min(months), max(months)
    bars = []
    while (y, m) <= last:
        n = months.get((y, m), 0)
        bars.append({"label": date(y, m, 1), "games": n, "bar": _pct(n, top)})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return bars


def weekday_bars(weekdays):
    counts = {int(w["weekday"]): int(w["games"]) for w in weekdays if w.get("weekday")}
    top = max(counts.values(), default=0)
    return [
        {"label": name, "games": counts.get(i, 0), "bar": _pct(counts.get(i, 0), top)}
        for i, name in enumerate(WEEKDAYS, start=1)
    ]


def hour_bars(hours):
    """Games by UTC hour, all 24 hours; None when no replays were collected live."""
    if not hours or not hours.get("sample"):
        return None
    counts = {int(h["hour"]): int(h["games"]) for h in hours.get("hours", [])}
    top = max(counts.values(), default=0)
    return {
        "sample": hours["sample"],
        "bars": [
            {"hour": h, "games": counts.get(h, 0), "bar": _pct(counts.get(h, 0), top)}
            for h in range(24)
        ],
    }


def mode_rows(modes):
    total = sum(int(m["games"]) for m in modes) or 0
    return [
        {
            "code": m.get("mode"),
            "label": mode_label(m.get("mode")),
            "games": int(m["games"]),
            "bar": _pct(int(m["games"]), total),
        }
        for m in modes
    ]


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


def map_rows(maps, links, username):
    top = max((int(m["games"]) for m in maps), default=0)
    return [
        {
            "name": m.get("name") or f"Map {m['mapid']}",
            "mapid": m["mapid"],
            "games": int(m["games"]),
            "bar": _pct(int(m["games"]), top),
            "url": links.map_replays(m["mapid"], username),
        }
        for m in maps
    ]


def people_rows(people, links, username):
    return [
        {
            "username": p["username"],
            "games": int(p["games"]),
            "same_team": p.get("same_team"),
            "profile_path": f"/player/{quote(p['username'], safe='')}/",
            "replays_url": links.together(username, p["username"]),
        }
        for p in people
    ]


def recent_rows(recent, links):
    rows = []
    for r in recent:
        players = r.get("players") or []
        rows.append(
            {
                "url": links.watch(r["cycle"], r["id"]),
                "map": r.get("mapname") or f"Map {r.get('mapid')}",
                "mode": mode_label(r.get("mode")),
                "day": _day(r.get("estimated_day")) or _day((r.get("fetched_at") or "")[:10]),
                "estimated": bool(r.get("estimated_day")),
                "players": len(players),
                "cycle": r["cycle"],
                "id": r["id"],
            }
        )
    return rows


def build(profile, replays_base_url):
    """Everything the replay sections of a profile draw, from one API reply."""
    links = ReplayLinks(replays_base_url)
    username = profile["username"]
    summary = profile["summary"]
    return {
        "username": username,
        "summary": {
            **summary,
            "first_day": _day((summary.get("first") or {}).get("day")),
            "last_day": _day((summary.get("last") or {}).get("day")),
        },
        "level_chart": level_chart(profile.get("days", [])),
        "months": monthly_games(profile.get("days", [])),
        "weekdays": weekday_bars(profile.get("weekdays", [])),
        "hours": hour_bars(profile.get("hours")),
        "modes": mode_rows(profile.get("modes", [])),
        "maps": map_rows(profile.get("maps", []), links, username),
        "played_with": people_rows(profile.get("played_with", []), links, username),
        "teammates": people_rows(profile.get("teammates", []), links, username),
        "recent": recent_rows(profile.get("recent", []), links),
        "all_replays_url": links.player_replays(username),
    }
