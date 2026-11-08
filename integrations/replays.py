"""The replay site's player API (ReplayRenderer, replays.bonkverse.io).

Owns: the `GET /api/player/<name>`, `/api/player/<name>/map/<mapid>`
(or `?name=` for "." and ".."),
`/api/players/lookup`, `/api/players?q=` and `/api/levels/distribution`
requests, URL-encoding the username, the
timeout, and sorting the reply into found / no such player / no usable
answer. Every call returns a `PlayerResult` instead of raising.
Does not own: what a profile page shows or who may see it (players/), or
the numbers themselves (computed by the replay service from its own
database, which is separate from Bonkverse's).

Free of Django at import time; `get_player_configured()` reads the URL from
settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

# The replay service aggregates every replay a player is in, which can take
# a few seconds for someone with tens of thousands of games.
DEFAULT_TIMEOUT = (3.0, 12.0)  # (connect, read) seconds
MAX_USERNAME_LENGTH = 100


def _player_url(base_url: str, username: str, tail: str = "") -> tuple[str, dict]:
    """(url, query params) for `/api/player/<name><tail>`. The names "." and
    ".." are dot segments that requests and proxies resolve away (even
    percent-encoded: /api/player/%2E%2E becomes /api/), so those go in the
    query instead: `/api/player<tail>?name=..`."""
    if username in (".", ".."):
        return f"{base_url}/api/player{tail}", {"name": username}
    return f"{base_url}/api/player/{quote(username, safe='')}{tail}", {}


class PlayerError:
    """`PlayerResult.error` codes."""

    NOT_CONFIGURED = "not_configured"  # no BONKVERSE_REPLAYS_URL here
    NOT_FOUND = "not_found"  # no replays for that registered name
    UNAVAILABLE = "unavailable"  # unreachable, 5xx, or not JSON


@dataclass(frozen=True)
class PlayerResult:
    data: dict[str, Any] | None = None  # the profile, on success
    error: str | None = None


def get_player(base_url: str, username: str, *, timeout=DEFAULT_TIMEOUT) -> PlayerResult:
    """A registered player's replay profile. Usernames are not trimmed:
    bonk.io names can have meaningful leading or trailing spaces."""
    if not base_url:
        return PlayerResult(error=PlayerError.NOT_CONFIGURED)
    if not username or len(username) > MAX_USERNAME_LENGTH:
        return PlayerResult(error=PlayerError.NOT_FOUND)

    url, params = _player_url(base_url, username)
    try:
        response = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("replays api: unreachable: %s", type(exc).__name__)
        return PlayerResult(error=PlayerError.UNAVAILABLE)

    if response.status_code in (400, 404):
        return PlayerResult(error=PlayerError.NOT_FOUND)

    try:
        data = response.json()
    except ValueError:
        logger.warning("replays api: non-JSON reply, http=%s", response.status_code)
        return PlayerResult(error=PlayerError.UNAVAILABLE)

    if not response.ok or not isinstance(data, dict) or not isinstance(data.get("summary"), dict):
        logger.warning("replays api: http=%s", response.status_code)
        return PlayerResult(error=PlayerError.UNAVAILABLE)
    return PlayerResult(data=data)


def get_player_map(
    base_url: str, username: str, mapid: str, *, timeout=DEFAULT_TIMEOUT
) -> PlayerResult:
    """One map from a player's side (`GET /api/player/<name>/map/<mapid>`)."""
    if not base_url:
        return PlayerResult(error=PlayerError.NOT_CONFIGURED)
    if not username or len(username) > MAX_USERNAME_LENGTH or not str(mapid).isdigit():
        return PlayerResult(error=PlayerError.NOT_FOUND)

    url, params = _player_url(base_url, username, f"/map/{mapid}")
    try:
        response = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("replays api (map): unreachable: %s", type(exc).__name__)
        return PlayerResult(error=PlayerError.UNAVAILABLE)

    if response.status_code in (400, 404):
        return PlayerResult(error=PlayerError.NOT_FOUND)
    try:
        data = response.json()
    except ValueError:
        logger.warning("replays api (map): non-JSON reply, http=%s", response.status_code)
        return PlayerResult(error=PlayerError.UNAVAILABLE)
    if not response.ok or not isinstance(data, dict) or "games" not in data:
        logger.warning("replays api (map): http=%s", response.status_code)
        return PlayerResult(error=PlayerError.UNAVAILABLE)
    return PlayerResult(data=data)


LOOKUP_MAX = 60


def _get_json(url, params, what, timeout):
    """(data, error) for a GET that should answer with a JSON object."""
    try:
        response = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("replays api (%s): unreachable: %s", what, type(exc).__name__)
        return None, PlayerError.UNAVAILABLE
    try:
        data = response.json()
    except ValueError:
        logger.warning("replays api (%s): non-JSON reply, http=%s", what, response.status_code)
        return None, PlayerError.UNAVAILABLE
    if not response.ok or not isinstance(data, dict) or not isinstance(data.get("results"), list):
        logger.warning("replays api (%s): http=%s", what, response.status_code)
        return None, PlayerError.UNAVAILABLE
    return data, None


def lookup_players(base_url: str, names, *, timeout=DEFAULT_TIMEOUT) -> PlayerResult:
    """Replay totals for exact registered names: data is {lower name: {username,
    games, level}}; names with no replays are missing from it."""
    if not base_url:
        return PlayerResult(error=PlayerError.NOT_CONFIGURED)
    names = [n for n in dict.fromkeys(names) if n and len(n) <= MAX_USERNAME_LENGTH][:LOOKUP_MAX]
    if not names:
        return PlayerResult(data={})
    data, error = _get_json(f"{base_url}/api/players/lookup", {"names": names}, "lookup", timeout)
    if error:
        return PlayerResult(error=error)
    return PlayerResult(
        data={
            str(r["username"]).lower(): r
            for r in data["results"]
            if isinstance(r, dict) and r.get("username")
        }
    )


def search_players(base_url: str, query: str, *, timeout=DEFAULT_TIMEOUT) -> PlayerResult:
    """Up to 10 registered names starting with `query`, most played first:
    data is [{username, games, level}]. Needs at least 3 characters."""
    if not base_url:
        return PlayerResult(error=PlayerError.NOT_CONFIGURED)
    if len(query) < 3 or len(query) > MAX_USERNAME_LENGTH:
        return PlayerResult(data=[])
    data, error = _get_json(f"{base_url}/api/players", {"q": query}, "search", timeout)
    if error:
        return PlayerResult(error=error)
    return PlayerResult(
        data=[r for r in data["results"] if isinstance(r, dict) and r.get("username")]
    )


def level_distribution(base_url: str, *, timeout=(3.0, 30.0)) -> PlayerResult:
    """How many registered players have each level as their highest seen in
    replays: data is {"levels": [[level, players], ...], "players": total}.
    The replay site works this out over its whole archive, hence the long
    read timeout the first time."""
    if not base_url:
        return PlayerResult(error=PlayerError.NOT_CONFIGURED)
    try:
        response = requests.get(f"{base_url}/api/levels/distribution", timeout=timeout)
        data = response.json()
    except requests.RequestException as exc:
        logger.warning("replays api (levels): unreachable: %s", type(exc).__name__)
        return PlayerResult(error=PlayerError.UNAVAILABLE)
    except ValueError:
        logger.warning("replays api (levels): non-JSON reply, http=%s", response.status_code)
        return PlayerResult(error=PlayerError.UNAVAILABLE)
    if not response.ok or not isinstance(data, dict) or not isinstance(data.get("levels"), list):
        logger.warning("replays api (levels): http=%s", response.status_code)
        return PlayerResult(error=PlayerError.UNAVAILABLE)
    return PlayerResult(data=data)


def get_player_configured(username: str) -> PlayerResult:
    """`get_player` against settings.BONKVERSE_REPLAYS_URL."""
    from django.conf import settings

    return get_player(settings.BONKVERSE_REPLAYS_URL, username)


def get_player_map_configured(username: str, mapid: str) -> PlayerResult:
    """`get_player_map` against settings.BONKVERSE_REPLAYS_URL."""
    from django.conf import settings

    return get_player_map(settings.BONKVERSE_REPLAYS_URL, username, mapid)


def lookup_players_configured(names) -> PlayerResult:
    """`lookup_players` against settings.BONKVERSE_REPLAYS_URL."""
    from django.conf import settings

    return lookup_players(settings.BONKVERSE_REPLAYS_URL, names)


def search_players_configured(query: str) -> PlayerResult:
    """`search_players` against settings.BONKVERSE_REPLAYS_URL."""
    from django.conf import settings

    return search_players(settings.BONKVERSE_REPLAYS_URL, query)


def level_distribution_configured() -> PlayerResult:
    """`level_distribution` against settings.BONKVERSE_REPLAYS_URL."""
    from django.conf import settings

    return level_distribution(settings.BONKVERSE_REPLAYS_URL)
