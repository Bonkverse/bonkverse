"""Client for the replay site's private sync routes (ReplayRenderer
server/sync-routes.mjs).

Owns: `GET /api/internal/replay-names` (registered names seen in replays,
a batch of replays after a cursor) and `POST /api/internal/player-ids`
(name ↔ DBID pairs with the estimated join day), both authorised with
`Authorization: Bearer <BONKVERSE_SYNC_TOKEN>`, the secret both services
share.
Does not own: what Bonkverse stores or when it syncs (players/replay_sync.py).

Never raises: every call returns a SyncResult with `data` or an `error`
code. Free of Django at import time; the *_configured helpers read settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

TIMEOUT = (3.0, 60.0)  # (connect, read) seconds; a batch can take a while
MAX_PLAYERS_PER_POST = 2000  # the replay site's limit


class SyncError:
    NOT_CONFIGURED = "not_configured"  # no replay URL or no shared token
    UNAUTHORIZED = "unauthorized"  # the token doesn't match (401) or routes off (404)
    UNAVAILABLE = "unavailable"  # unreachable, 5xx, or not JSON
    BAD_REQUEST = "bad_request"  # 400


@dataclass(frozen=True)
class SyncResult:
    data: dict[str, Any] | None = None
    error: str | None = None


def _call(method, url, token, what, **kwargs):
    if not url or not token:
        return SyncResult(error=SyncError.NOT_CONFIGURED)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        logger.warning("replay sync (%s): unreachable: %s", what, type(exc).__name__)
        return SyncResult(error=SyncError.UNAVAILABLE)
    if response.status_code in (401, 403, 404):
        logger.warning("replay sync (%s): http=%s (token or routes)", what, response.status_code)
        return SyncResult(error=SyncError.UNAUTHORIZED)
    if response.status_code == 400:
        return SyncResult(error=SyncError.BAD_REQUEST)
    try:
        data = response.json()
    except ValueError:
        logger.warning("replay sync (%s): non-JSON reply, http=%s", what, response.status_code)
        return SyncResult(error=SyncError.UNAVAILABLE)
    if not response.ok or not isinstance(data, dict):
        logger.warning("replay sync (%s): http=%s", what, response.status_code)
        return SyncResult(error=SyncError.UNAVAILABLE)
    return SyncResult(data=data)


def fetch_replay_names(base_url: str, token: str, after: str = "", limit: int = 5000) -> SyncResult:
    """data: {"names": [{username, level, games, skin, skin_seen_at}],
    "avatars": {hash: {layers, bc}}, "next": "cycle:id", "done": bool}.

    `skin` and `avatars` come from ReplayRenderer since it began sending
    skins; older answers lack them, which callers treat as "no skins".
    """
    params = {"limit": limit}
    if after:
        params["after"] = after
    result = _call(
        "GET",
        f"{base_url}/api/internal/replay-names" if base_url else "",
        token,
        "names",
        params=params,
    )
    if result.data is not None and not (
        isinstance(result.data.get("names"), list) and isinstance(result.data.get("next"), str)
    ):
        return SyncResult(error=SyncError.UNAVAILABLE)
    return result


def push_player_ids(base_url: str, token: str, players: list[dict]) -> SyncResult:
    """Send up to MAX_PLAYERS_PER_POST {username, dbid, joined} rows.
    data: {"received", "written", "skipped"}."""
    if len(players) > MAX_PLAYERS_PER_POST:
        return SyncResult(error=SyncError.BAD_REQUEST)
    return _call(
        "POST",
        f"{base_url}/api/internal/player-ids" if base_url else "",
        token,
        "ids",
        json={"players": players},
    )


def _settings():
    from django.conf import settings

    return settings.BONKVERSE_REPLAYS_URL, settings.BONKVERSE_SYNC_TOKEN


def fetch_replay_names_configured(after: str = "", limit: int = 5000) -> SyncResult:
    url, token = _settings()
    return fetch_replay_names(url, token, after, limit)


def push_player_ids_configured(players: list[dict]) -> SyncResult:
    url, token = _settings()
    return push_player_ids(url, token, players)
