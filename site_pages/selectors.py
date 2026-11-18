"""What the home page shows (design review 2026-11-09, step 2f: what Bonkverse
is, three doors, live activity).

Owns: putting the home page together from the apps that own each part:
skin rows and counts (skins.selectors), the number of known players
(players.selectors) and the newest replays and collector status from the
replay site (integrations/replays.py), shaped for the template.
Does not own: any of those numbers, or the replay site's pages.

The replay site is asked at most once a minute, whether it answered or not,
so a slow or down replay site never slows the home page more than once.
"""

from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from integrations.replays import (
    collector_status_configured,
    recent_replays_configured,
    thumbnail_url,
    watch_url,
)
from players.selectors import known_player_count, with_skin_avatars
from skins.selectors import home_strips, skin_counts

REPLAY_CARDS = 4
NAMES_PER_REPLAY = 4
HERO_PLAYERS = 5  # avatars on the hero's Players tile
_REPLAYS_KEY = "site_pages:home:replays:v1"
_REPLAYS_SECONDS = 60


def home(now: datetime | None = None) -> dict:
    """Everything home.html shows."""
    now = now or timezone.now()
    replays = _replay_activity()
    cards = [_replay_card(r, now) for r in replays["replays"]]
    return {
        **home_strips(),
        "skin_counts": skin_counts(now),
        "player_count": known_player_count(),
        "replays": cards,
        "collector": _collector(replays["status"], now),
        "hero_players": _hero_players(replays["replays"]),
        "replays_url": settings.BONKVERSE_REPLAYS_URL,
        "editor_url": settings.BONKVERSE_EDITOR_URL,
    }


def _hero_players(replays: list[dict]) -> list[dict]:
    """Registered players from the newest replays, each with their worn skin
    as an avatar when Bonkverse has seen it ("skin": URL or None)."""
    names = []
    for replay in replays:
        for p in replay.get("players") or []:
            name = p.get("username") if isinstance(p, dict) else None
            if name and not p.get("guest") and name.lower() not in {n.lower() for n in names}:
                names.append(name)
    return with_skin_avatars([{"username": n} for n in names[:HERO_PLAYERS]])


def _replay_activity() -> dict:
    """{"replays": [...], "status": {...} or None}, cached a minute."""
    found = cache.get(_REPLAYS_KEY)
    if found is not None:
        return found
    recent = recent_replays_configured(REPLAY_CARDS)
    status = collector_status_configured() if recent.data else None
    found = {
        "replays": recent.data or [],
        "status": status.data if status and status.data else None,
    }
    cache.set(_REPLAYS_KEY, found, _REPLAYS_SECONDS)
    return found


def ago(when: datetime | None, now: datetime) -> str:
    """The design guide's short times: "just now", "12 min ago", "3 h ago",
    then the date ("Nov 8, 2026")."""
    if when is None:
        return ""
    seconds = (now - when).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{when:%b} {when.day}, {when.year}"


def _time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return parse_datetime(value)
    except ValueError:
        return None


def _replay_card(replay: dict, now: datetime) -> dict:
    base = settings.BONKVERSE_REPLAYS_URL
    players = [p for p in replay.get("players") or [] if isinstance(p, dict) and p.get("username")]
    fetched = _time(replay.get("fetched_at"))
    return {
        "map_name": replay.get("mapname") or "Unknown map",
        "watch_url": watch_url(base, replay["cycle"], replay["id"]),
        "thumbnail_url": thumbnail_url(base, replay["mapid"]) if replay.get("mapid") else None,
        "players": [
            {"username": p["username"], "guest": bool(p.get("guest"))}
            for p in players[:NAMES_PER_REPLAY]
        ],
        "more_players": max(0, len(players) - NAMES_PER_REPLAY),
        "fetched_at": fetched,
        "ago": ago(fetched, now),
    }


def _collector(status: dict | None, now: datetime) -> dict | None:
    """What the countdown shows: seconds until the next collection (None
    while it's collecting or if unknown) and what the last one added."""
    if not status:
        return None
    next_fetch = _time(status.get("next_fetch_at"))
    last_run = _time(status.get("last_run_at"))
    seconds = int((next_fetch - now).total_seconds()) if next_fetch else None
    added = status.get("last_run_added")
    seconds = seconds if seconds is not None and seconds > 0 else None
    return {
        "seconds_to_next": seconds,
        "next_in": f"{seconds // 60}:{seconds % 60:02d}" if seconds else "",
        "last_added": added if isinstance(added, int) and added >= 0 else None,
        "last_ago": ago(last_run, now),
    }
