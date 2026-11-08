"""The replay site's player API (ReplayRenderer, replays.bonkverse.io).

Owns: the `GET /api/player/<name>` and `/api/player/<name>/map/<mapid>`
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

    url = f"{base_url}/api/player/{quote(username, safe='')}"
    try:
        response = requests.get(url, timeout=timeout)
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

    url = f"{base_url}/api/player/{quote(username, safe='')}/map/{mapid}"
    try:
        response = requests.get(url, timeout=timeout)
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


def get_player_configured(username: str) -> PlayerResult:
    """`get_player` against settings.BONKVERSE_REPLAYS_URL."""
    from django.conf import settings

    return get_player(settings.BONKVERSE_REPLAYS_URL, username)


def get_player_map_configured(username: str, mapid: str) -> PlayerResult:
    """`get_player_map` against settings.BONKVERSE_REPLAYS_URL."""
    from django.conf import settings

    return get_player_map(settings.BONKVERSE_REPLAYS_URL, username, mapid)
