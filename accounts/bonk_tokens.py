"""The token broker: the one place that reads or writes stored bonk.io tokens.

Owns: handing out a usable bonk.io session token for an account link
(`usable_token`), refreshing it with the link's remember-me token through
login_auto.php when it has expired, storing what a login gives us
(`store_login`), and disconnecting (`disconnect`).
Does not own: the bonk.io calls (integrations/bonk_api.py), the password
login and its guards (login_attempts.py), or what Wear does with the token
(skins/views/wear.py).

RFC-0003 Part 2. A player types a bonk.io password once per account and
device; after that, when "Keep me connected for Wear" was ticked, the link
keeps bonk.io's remember-me token and the broker swaps it for a fresh
24-hour session token whenever an action needs one. Measured with the lab
(2026-11-24, docs/bonk/login-rate-limit.md#remember-me-tokens):
login_auto.php doesn't count toward the login limit and doesn't rotate the
remember-me token, a second remember-me login doesn't cancel the first, and
login_clearauto.php revokes only the token it's given.

usable_token(link):
1. The stored session token if it's good for more than REFRESH_MARGIN.
   No bonk.io call.
2. Else, with an active remember-me token: one refresh per link at a time
   (a short Redis lock; others wait for it), login_auto.php, store the new
   token, its expiry, the active slot, XP, and queue the friend list from
   the answer. Return the new token.
3. login_auto.php says not_found: the remember-me token is marked revoked
   and deleted; ReconnectNeeded.
4. bonk.io is limiting us, or Bonkverse's login pause is on: Paused (with the
   seconds left). Nothing is marked revoked. During a login pause nothing is
   sent at all: a request during bonk.io's block seems to restart it.
5. bonk.io can't be reached: Unavailable.
6. No remember-me token: ReconnectNeeded (the password login).

Refreshes happen only when an action needs a token; nothing refreshes on a
schedule, so an idle account costs bonk.io nothing.

Tokens never appear in logs, task arguments, admin pages, API responses or
error messages.
"""

from __future__ import annotations

import logging
import math
import time
from contextlib import contextmanager

from django.core.cache import cache
from django.utils import timezone

from integrations.bonk_api import (
    LOGIN_AUTO_SCRIPT,
    BonkError,
    BonkLoginResult,
    get_client,
    rate_limit_cooldowns,
)

from .models import BonkAccountLink

logger = logging.getLogger(__name__)

# A stored session token closer than this to its expiry is refreshed first,
# so a wear never races the token running out on bonk.io's side.
REFRESH_MARGIN_SECONDS = 5 * 60
# Longest a refresh holds its link's lock: longer than the bonk.io (connect +
# read) timeout. Others asking for the same link wait up to this long.
REFRESH_LOCK_SECONDS = 15
REFRESH_WAIT_STEP = 0.25


class ReconnectNeeded(Exception):
    """Only the bonk.io password will do (no remember-me token, or bonk.io
    revoked it)."""


class Paused(Exception):
    """bonk.io is limiting Bonkverse; try again in `seconds`."""

    def __init__(self, seconds: int):
        super().__init__(f"paused for {seconds}s")
        self.seconds = seconds


class Unavailable(Exception):
    """bonk.io couldn't be reached."""


def active_link(request) -> BonkAccountLink | None:
    """The account link this browser acts as on bonk.io: the signed-in
    user's link to the bonk.io account the session last logged in to, else
    their most recently used link. None when they have none."""
    if not request.user.is_authenticated:
        return None
    from core.token_crypto import bonk_session

    links = BonkAccountLink.objects.select_related("bonk_player").filter(
        user=request.user, active=True
    )
    bonk_id = bonk_session(request).bonk_id
    if bonk_id is not None:
        link = links.filter(bonk_player__bonk_id=bonk_id).first()
        if link is not None:
            return link
    return links.order_by("-updated_at").first()


def usable_token(link: BonkAccountLink, *, force_refresh: bool = False) -> str:
    """A bonk.io session token for `link` that bonk.io should accept.

    Args:
        link: The account link to act as.
        force_refresh: bonk.io refused the stored token before its expiry
            (`e: "token"`); refresh once instead of trusting it. Callers do
            this at most once per action, never in a loop.

    Raises:
        ReconnectNeeded, Paused, Unavailable.
    """
    if not force_refresh:
        token = _fresh_session_token(link)
        if token:
            return token
    if link.remember_token() is None:
        raise ReconnectNeeded
    with _refresh_lock(link.pk) as holder:
        if not holder:
            # Another request is refreshing this link; use what it stored.
            link.refresh_from_db()
            token = _fresh_session_token(link)
            if token:
                return token
            raise Paused(5)
        if force_refresh is False:
            # A refresh may have finished while we waited for the lock.
            link.refresh_from_db()
            token = _fresh_session_token(link)
            if token:
                return token
        return _refresh(link)


def store_login(link: BonkAccountLink, result: BonkLoginResult, *, remember: bool) -> None:
    """Store what a successful password login gave for `link`: the session
    token, its expiry, the active slot, and the remember-me token when the
    player asked to stay connected.

    Unticking "Keep me connected" revokes a remember-me token stored before
    (login_clearauto.php), so Bonkverse keeps none.
    """
    fields = _session_fields(result)
    if remember and result.remember_token:
        fields.update(
            remember_token_encrypted=BonkAccountLink.encrypt_token(result.remember_token),
            remember_status=BonkAccountLink.REMEMBER_ACTIVE,
        )
    elif not remember:
        _revoke_stored_remember_token(link)
        fields.update(remember_token_encrypted=None, remember_status=BonkAccountLink.REMEMBER_NONE)
    _update(link, **fields)


def disconnect(link: BonkAccountLink) -> None:
    """Forget the link's bonk.io connection: revoke its remember-me token on
    bonk.io (login_clearauto.php), then delete both stored tokens. The link
    itself (who owns which bonk.io account) stays."""
    _revoke_stored_remember_token(link)
    _update(
        link,
        token_encrypted=None,
        token_expires_at=None,
        remember_token_encrypted=None,
        remember_status=BonkAccountLink.REMEMBER_NONE,
    )
    logger.info("bonk.io connection disconnected | link=%s", link.pk)


def forget_remember_token(link: BonkAccountLink) -> None:
    """Revoke the link's remember-me token on bonk.io and delete it here,
    keeping the session token (revoke_bonk_remember_tokens)."""
    _revoke_stored_remember_token(link)
    _update(link, remember_token_encrypted=None, remember_status=BonkAccountLink.REMEMBER_NONE)


def connection(link: BonkAccountLink | None) -> dict:
    """What the settings page shows for a link's connection (no secrets).

    `state` is "remembered" (stays connected, refreshed when needed),
    "connected" (until `until`), or "disconnected".
    """
    if link is None:
        return {"state": "disconnected"}
    if link.remember_status == BonkAccountLink.REMEMBER_ACTIVE:
        return {"state": "remembered", "username": link.bonk_player.username}
    if link.bonk_token() and link.token_expires_at:
        return {
            "state": "connected",
            "username": link.bonk_player.username,
            "until": link.token_expires_at,
        }
    return {"state": "disconnected", "username": link.bonk_player.username}


def _fresh_session_token(link: BonkAccountLink) -> str | None:
    token = link.bonk_token()
    if token is None:
        return None
    if link.token_expires_at is not None:
        left = (link.token_expires_at - timezone.now()).total_seconds()
        if left < REFRESH_MARGIN_SECONDS:
            return None
    return token


def _refresh(link: BonkAccountLink) -> str:
    remember = link.remember_token()
    if remember is None:
        raise ReconnectNeeded
    result = get_client().login_auto(remember)
    if result.ok:
        _update(link, **_session_fields(result), last_refreshed_at=timezone.now())
        _after_refresh(link, result)
        logger.info("bonk.io connection refreshed | link=%s", link.pk)
        return result.token
    if result.error == BonkError.RATE_LIMITED:
        seconds = math.ceil(rate_limit_cooldowns.remaining(LOGIN_AUTO_SCRIPT)) or 60
        logger.info("bonk.io refresh paused | link=%s | retry_after=%s", link.pk, seconds)
        raise Paused(seconds)
    if result.error == BonkError.UNAVAILABLE:
        raise Unavailable
    # not_found (revoked by bonk.io), or a refusal we don't know: the token is
    # no good, and only the password will do.
    _update(link, remember_token_encrypted=None, remember_status=BonkAccountLink.REMEMBER_REVOKED)
    logger.info(
        "bonk.io refused the remember-me token; marked revoked | link=%s | bonk_error=%s",
        link.pk,
        result.bonk_error,
    )
    raise ReconnectNeeded


def _after_refresh(link: BonkAccountLink, result: BonkLoginResult) -> None:
    """What a refresh answer also gives us: the friend list and XP. A failure
    here never fails the refresh."""
    try:
        from players.services import queue_login_friends

        player = link.bonk_player
        if result.xp is not None:
            player.xp = result.xp
            player.xp_seen_at = timezone.now()
            player.save(update_fields=["xp", "xp_seen_at", "updated_at"])
        if result.friends is not None:
            queue_login_friends(link.pk, result.friends, result.requests)
    except Exception:
        logger.exception("could not store what a bonk.io refresh returned | link=%s", link.pk)


def _revoke_stored_remember_token(link: BonkAccountLink) -> None:
    remember = link.remember_token()
    if remember is None:
        return
    result = get_client().clear_auto(remember)
    if not result.ok:
        # The stored copy is deleted anyway; bonk.io's copy lapses unused.
        logger.warning(
            "could not revoke a remember-me token on bonk.io | link=%s | error=%s",
            link.pk,
            result.error,
        )


def _session_fields(result: BonkLoginResult) -> dict:
    return {
        "token_encrypted": BonkAccountLink.encrypt_token(result.token),
        "token_expires_at": BonkAccountLink.expiry_for(result.token),
        "active_slot": result.active_slot.number if result.active_slot else None,
    }


def _update(link: BonkAccountLink, **fields) -> None:
    """Write `fields` to the row and to the in-memory link."""
    fields.setdefault("updated_at", timezone.now())
    BonkAccountLink.objects.filter(pk=link.pk).update(**fields)
    for name, value in fields.items():
        setattr(link, name, value)


@contextmanager
def _refresh_lock(link_id: int):
    """One refresh per link at a time, across workers (Redis SET NX).

    Yields True when this request holds the lock (or the cache is down), and
    False after waiting up to REFRESH_LOCK_SECONDS for another request's
    refresh to finish.
    """
    key = f"bonk_tokens:refresh:{link_id}"
    try:
        added = cache.add(key, 1, timeout=REFRESH_LOCK_SECONDS)
    except Exception:
        added = None
    if added is False:
        deadline = time.monotonic() + REFRESH_LOCK_SECONDS
        while time.monotonic() < deadline:
            time.sleep(REFRESH_WAIT_STEP)
            try:
                if cache.get(key) is None:
                    break
            except Exception:
                break
        yield False
        return
    try:
        yield True
    finally:
        if added:
            try:
                cache.delete(key)
            except Exception:
                pass
