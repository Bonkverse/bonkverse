"""Discord's public invite API: looking up a server from an invite code.

Owns: the invite request (`GET /invites/{code}?with_counts&with_expiration`,
no auth), checking the code before it goes into the URL, the timeout,
reading the reply into a `DiscordInvite`, and Discord's 404 / 429 answers.
Every call returns an `InviteResult` instead of raising.
Does not own: how often to call (the caller paces itself; see
communities/tasks.py), database rows, or messages people see.

Free of Django at import time. Unauthenticated calls share Discord's per-IP
limits, so callers must honour `retry_after` on RATE_LIMITED.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://discord.com/api/v10"
DEFAULT_TIMEOUT = (3.0, 10.0)  # (connect, read) seconds
# Invite codes are letters, digits and dashes; DiscordServer.invite_code holds 32.
_INVITE_CODE = re.compile(r"^[A-Za-z0-9-]{1,32}$")


class InviteError:
    """`InviteResult.error` codes."""

    INVALID_CODE = "invalid_code"  # not an invite code; nothing was sent
    NOT_FOUND = "not_found"  # Discord: unknown, revoked or expired invite
    RATE_LIMITED = "rate_limited"  # Discord: 429; see `retry_after`
    UNAVAILABLE = "unavailable"  # no usable answer (network, 5xx, not JSON)


@dataclass(frozen=True)
class DiscordInvite:
    code: str
    guild_id: str
    name: str
    description: str
    icon_hash: str
    splash_hash: str
    member_count: int
    online_count: int
    expires_at: str | None  # ISO time, or None for a permanent invite


@dataclass(frozen=True)
class InviteResult:
    invite: DiscordInvite | None = None
    error: str | None = None
    retry_after: float | None = None  # seconds, only with RATE_LIMITED


def is_invite_code(code: str) -> bool:
    return bool(_INVITE_CODE.match(code or ""))


def fetch_invite(code: str, *, base_url: str = API_BASE, timeout=DEFAULT_TIMEOUT) -> InviteResult:
    """Look up one invite. The code goes into the URL path, so it is checked first."""
    if not is_invite_code(code):
        return InviteResult(error=InviteError.INVALID_CODE)

    try:
        response = requests.get(
            f"{base_url}/invites/{code}",
            params={"with_counts": "true", "with_expiration": "true"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning("discord invite lookup: unreachable: %s", type(exc).__name__)
        return InviteResult(error=InviteError.UNAVAILABLE)

    if response.status_code == 404:
        return InviteResult(error=InviteError.NOT_FOUND)
    if response.status_code == 429:
        retry_after = _retry_after(response)
        logger.warning("discord invite lookup: rate limited, retry after %.1fs", retry_after)
        return InviteResult(error=InviteError.RATE_LIMITED, retry_after=retry_after)

    try:
        data = response.json()
    except ValueError:
        data = None
    if response.status_code != 200 or not isinstance(data, dict):
        logger.warning("discord invite lookup: unusable reply, http=%s", response.status_code)
        return InviteResult(error=InviteError.UNAVAILABLE)

    return InviteResult(invite=_parse(code, data))


def _parse(code: str, data: dict) -> DiscordInvite:
    guild = data.get("guild") or {}
    # `profile` is newer and not in Discord's docs; the approximate_* counts
    # are documented. Prefer profile (what Bonkverse always read), fall back.
    profile = data.get("profile") or {}
    return DiscordInvite(
        code=code,
        guild_id=str(guild.get("id") or data.get("guild_id") or ""),
        name=guild.get("name") or profile.get("name") or "",
        description=guild.get("description") or profile.get("description") or "",
        icon_hash=guild.get("icon") or profile.get("icon_hash") or "",
        splash_hash=guild.get("splash") or "",
        member_count=_count(profile.get("member_count"), data.get("approximate_member_count")),
        online_count=_count(profile.get("online_count"), data.get("approximate_presence_count")),
        expires_at=data.get("expires_at"),
    )


def _count(*values) -> int:
    for value in values:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _retry_after(response) -> float:
    """Seconds to wait, from the JSON body (Discord's own field) or the header."""
    try:
        return float(response.json().get("retry_after"))
    except (ValueError, TypeError, AttributeError):
        pass
    try:
        return float(response.headers.get("Retry-After"))
    except (TypeError, ValueError):
        return 5.0
