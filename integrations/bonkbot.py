"""BonkBot's HTTP API: joining the matchmaking queue.

Owns: the join-matchmaking request, its timeout, and telling a usable
BonkBot answer (any status, JSON body) from no usable answer.
Does not own: matchmaking itself (the BonkBot service) or the Bonkverse
endpoint that relays it (skins/bonkbot.py).

Free of Django at import time; `join_matchmaking_configured()` reads the URL
from settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = (3.0, 10.0)  # (connect, read) seconds; a hung BonkBot used to hold a worker


@dataclass(frozen=True)
class BonkBotReply:
    """BonkBot's status and JSON body, or `ok=False` when it gave no usable answer."""

    ok: bool
    status: int | None = None
    body: Any = None


def join_matchmaking(base_url: str, payload: Any, *, timeout=DEFAULT_TIMEOUT) -> BonkBotReply:
    try:
        response = requests.post(f"{base_url}/join-matchmaking", json=payload, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("bonkbot join-matchmaking: unreachable: %s", type(exc).__name__)
        return BonkBotReply(ok=False)
    try:
        body = response.json()
    except ValueError:
        logger.warning("bonkbot join-matchmaking: non-JSON reply, http=%s", response.status_code)
        return BonkBotReply(ok=False)
    return BonkBotReply(ok=True, status=response.status_code, body=body)


def join_matchmaking_configured(payload: Any) -> BonkBotReply:
    """`join_matchmaking` against settings.BONKBOT_API_URL."""
    from django.conf import settings

    return join_matchmaking(settings.BONKBOT_API_URL, payload)
