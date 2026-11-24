"""The bot's bonk.io account: the one people send friend requests to.

Owns: its name (BONK_BOT_USERNAME), signing it in to bonk.io with its
password (BONK_BOT_PASSWORD) as rarely as possible, and handing out a usable
session token.
Does not own: what is done with the token (link_claims.py reads and deletes
friend requests).

It's the same account BonxBot uses for /link (RFC-0003 phase 6 decisions),
so players learn one name. Each logs in separately; a second login doesn't
end the first (lab, 2026-11-24).

Logins are what bonk.io limits per IP, and this IP is shared with every
player's login. So the first login asks for a remember-me token, and later
sessions come from login_auto.php, which isn't counted. Tokens are kept in
the cache, encrypted (core.token_crypto). A wrong password or a refused
remember-me token stops password logins for WRONG_PASSWORD_WAIT, so a bad
setting can't use up the login budget.
"""

from __future__ import annotations

import logging
import time

from django.conf import settings
from django.core.cache import cache

from core import token_crypto
from core.bonk import BonkUsername
from core.bonk.tokens import token_expiry
from integrations.bonk_api import BonkError, get_client

logger = logging.getLogger(__name__)

_TOKEN_KEY = "bonk_bot:token"  # encrypted session token
_REMEMBER_KEY = "bonk_bot:remember"  # encrypted remember-me token
_HOLD_KEY = "bonk_bot:password_hold"  # set after a refused password
# Long enough to keep the bot's remember-me token between deploys; it's also
# renewed every time it's used.
REMEMBER_SECONDS = 60 * 24 * 3600
WRONG_PASSWORD_WAIT = 30 * 60
# A token this close to its exp is treated as expired.
EXPIRY_MARGIN = 120


def bot_name() -> str | None:
    """The bot account's bonk.io name, as players must spell it, or None
    when friend-request linking isn't set up here."""
    return getattr(settings, "BONK_BOT_USERNAME", "") or None


def configured() -> bool:
    return bool(bot_name() and getattr(settings, "BONK_BOT_PASSWORD", ""))


def token() -> str | None:
    """A usable session token for the bot account, or None if bonk.io can't
    be reached, is pausing logins, or the bot isn't set up. Logs in only when
    no stored token works."""
    if not configured():
        return None
    stored = _read(_TOKEN_KEY)
    if stored and _fresh(stored):
        return stored
    return _from_remember_me() or _from_password()


def forget_token() -> None:
    """bonk.io refused the session token ("token"): get a new one next time."""
    cache.delete(_TOKEN_KEY)


def _fresh(session_token: str) -> bool:
    exp = token_expiry(session_token)
    return exp is None or exp - EXPIRY_MARGIN > time.time()


def _from_remember_me() -> str | None:
    remember = _read(_REMEMBER_KEY)
    if not remember:
        return None
    result = get_client().login_auto(remember)
    if result.ok:
        _keep(result.token, remember)
        return result.token
    if result.error in (BonkError.NOT_FOUND, BonkError.TOKEN_REJECTED, BonkError.REJECTED):
        logger.warning("bot account: remember-me token refused (%s); dropping it", result.error)
        cache.delete(_REMEMBER_KEY)
    return None


def _from_password() -> str | None:
    if cache.get(_HOLD_KEY):
        return None
    result = get_client().login(
        BonkUsername(bot_name()).value, settings.BONK_BOT_PASSWORD, remember=True
    )
    if result.ok:
        logger.info("bot account: signed in to bonk.io")
        _keep(result.token, result.remember_token)
        return result.token
    if result.error in (BonkError.WRONG_PASSWORD, BonkError.UNKNOWN_USERNAME):
        logger.error(
            "bot account: bonk.io refused BONK_BOT_USERNAME/BONK_BOT_PASSWORD (%s); "
            "not retrying for %s min",
            result.error,
            WRONG_PASSWORD_WAIT // 60,
        )
        cache.set(_HOLD_KEY, 1, WRONG_PASSWORD_WAIT)
    else:
        logger.warning("bot account: login failed (%s)", result.error)
    return None


def _keep(session_token: str | None, remember: str | None) -> None:
    if session_token:
        exp = token_expiry(session_token)
        ttl = max(60, int(exp - time.time())) if exp else 3600
        cache.set(_TOKEN_KEY, token_crypto.encrypt(session_token), ttl)
    if remember:
        cache.set(_REMEMBER_KEY, token_crypto.encrypt(remember), REMEMBER_SECONDS)


def _read(key: str) -> str | None:
    stored = cache.get(key)
    if not stored:
        return None
    try:
        return token_crypto.decrypt(stored)
    except Exception:
        # Encrypted under a key that's gone (rotated): start over.
        cache.delete(key)
        return None
