"""Logging in to bonk.io for a player, with Bonkverse's own limit on wrong passwords.

Owns: the one way the site tries a bonk.io username and password (the /login/
page and the in-page login on wear both call `attempt_login`), the limit on
failed logins per bonk.io account and per visitor, and the log line for every
attempt.
Does not own: the bonk.io call (integrations/bonk_api.py) or bonk.io's own
pause after a "ratelimited" (the cooldown there), the sentences players see
(skins/login.py), or the per-IP request tier on the login views
(core/ratelimits.py, "login").

Why (measured 2026-11-10, docs/bonk/login-rate-limit.md): bonk.io limits
login_legacy.php by IP. From a datacenter IP like Railway's, it answers about
4 wrong passwords and then "ratelimited" to every login from that IP, correct
passwords included, for about 15 minutes. Every Bonkverse login comes from the
server's IP, so those 4 wrong passwords are shared by everyone on the site,
and one player's typos lock everyone out. Holding a player's next try here,
before bonk.io sees it, keeps any one person from using up that budget.

Every attempt is logged with a pseudonym for the account and the visitor
(core/pseudonym.py), never the name or IP, so a run of wrong passwords and the
rate limit that follows can be traced to one person.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from django.core.cache import cache

from core.client_ip import client_ip
from core.pseudonym import pseudonym
from integrations.bonk_api import (
    LOGIN_SCRIPT,
    BonkError,
    BonkLoginResult,
    get_client,
    rate_limit_cooldowns,
)

# The attempt lines keep the logger name they had in skins/login.py, so Railway
# searches like @logger:skins.login still find them.
logger = logging.getLogger("skins.login")

# Bonkverse's own refusal: this account or visitor has used up its wrong
# passwords for now, so we didn't ask bonk.io. Not a BonkError: bonk.io never
# saw the attempt.
TOO_MANY_ATTEMPTS = "too_many_attempts"

# Failures that count: bonk.io answered and said the login was wrong. Rate
# limits and network errors aren't the player's fault and don't count.
COUNTED_FAILURES = {BonkError.WRONG_PASSWORD, BonkError.UNKNOWN_USERNAME}
# Only wrong passwords count per account: bonk.io answered 20 unknown
# usernames in a row without limiting (2026-11-10). Unknown usernames still
# count per visitor, so nobody can guess names through Bonkverse.
ACCOUNT_COUNTED_FAILURES = {BonkError.WRONG_PASSWORD}

# How long failures are remembered, counted from the first one.
FAILURE_WINDOW = 15 * 60
# Wrong passwords allowed per account from one visitor (name + visitor IP)
# before the next try is held. bonk.io allows about 4 for the whole site, so
# this leaves room for someone else's typo. Keyed on the visitor too, so a
# stranger typing someone's name with wrong passwords holds only the stranger.
ACCOUNT_FAILURES_ALLOWED = 2
# Per visitor, across accounts: below bonk.io's 4, so one visitor can't use up
# the site's budget by switching names.
CLIENT_FAILURES_ALLOWED = 3
# How long a hold lasts once the allowance is used up.
HOLD_SECONDS = 15 * 60
# When bonk.io answers "ratelimited" to someone who already had a wrong
# password, hold them at least this long, and never less than the site-wide
# pause (17 min, integrations/bonk_api.py), so their retry isn't the first
# call when the pause ends. A request during bonk.io's block restarts it.
TRIGGER_HOLD_SECONDS = 30 * 60


@dataclass(frozen=True)
class LoginAttempt:
    """What happened when a player tried to log in.

    `result` is bonk.io's answer, or None when Bonkverse held the attempt
    without asking bonk.io (`error` is then TOO_MANY_ATTEMPTS).
    `retry_after` is the seconds to wait when waiting will help: bonk.io's
    pause, a hold, or a wrong password that used up the last try.
    """

    result: BonkLoginResult | None
    error: str | None = None
    retry_after: int | None = None

    @property
    def ok(self) -> bool:
        return self.result is not None and self.result.ok


def normalize_username(username: str) -> str:
    """The form we count failures under: bonk.io names are case-insensitive."""
    return (username or "").strip().lower()


class _Tracker:
    """Failure counts and holds for one subject (an account from a visitor, or
    a visitor).

    Kept in Django's cache (Redis in production) so every gunicorn worker sees
    the same counts. If the cache fails, logins go ahead unlimited: this is a
    courtesy to bonk.io, and it must never be the reason a player can't log in.
    """

    def __init__(self, kind: str, key: str, allowed: int):
        self.kind = kind
        self.allowed = allowed
        self._failures_key = f"login:failures:{kind}:{key}"
        self._hold_key = f"login:hold:{kind}:{key}"

    def _cache(self, method: str, *args, **kwargs):
        try:
            return getattr(cache, method)(*args, **kwargs)
        except Exception:
            logger.warning("login attempt cache failed (%s); not limiting this login", method)
            return None

    def hold_remaining(self) -> int:
        until = self._cache("get", self._hold_key)
        try:
            return max(0, math.ceil(float(until) - time.time())) if until else 0
        except (TypeError, ValueError):
            return 0

    def failures(self) -> int:
        value = self._cache("get", self._failures_key)
        return value if isinstance(value, int) else 0

    def hold(self, seconds: float) -> None:
        """Hold this subject for at least `seconds` (never shortens a hold)."""
        seconds = math.ceil(seconds)
        if seconds > self.hold_remaining():
            self._cache("set", self._hold_key, time.time() + seconds, timeout=seconds)

    def record_failure(self) -> int:
        """Count one wrong try; hold the subject once its allowance is used up.

        Returns the failures counted in the current window.
        """
        self._cache("add", self._failures_key, 0, timeout=FAILURE_WINDOW)
        count = self._cache("incr", self._failures_key)
        if not isinstance(count, int):
            return 0
        if count >= self.allowed:
            self.hold(HOLD_SECONDS)
        return count

    def clear(self) -> None:
        self._cache("delete_many", [self._failures_key, self._hold_key])


def attempt_login(request, username: str, password: str, *, via: str) -> LoginAttempt:
    """Try a bonk.io login unless this account or visitor is being held.

    Args:
        request: The Django request (for the visitor's IP).
        username: As the player typed it; sent to bonk.io unchanged.
        password: Sent to bonk.io only; never logged or stored.
        via: Which form it came from, for the log line ("page" or "wear").

    Returns:
        A LoginAttempt. On a hold, bonk.io isn't called.
    """
    name = normalize_username(username)
    ip = client_ip(request)
    account_tag = pseudonym("account", name)
    client_tag = pseudonym("client", ip)
    # The account count is per name AND visitor: nobody else's wrong
    # passwords can hold your account.
    account = _Tracker(
        "account", pseudonym("account_client", f"{name}\n{ip}"), ACCOUNT_FAILURES_ALLOWED
    )
    visitor = _Tracker("client", client_tag, CLIENT_FAILURES_ALLOWED)
    tags = f"account={account_tag} | client={client_tag} | via={via}"

    held_for = max(account.hold_remaining(), visitor.hold_remaining())
    if held_for:
        logger.info(
            "bonk login held | %s | account_failures=%s | client_failures=%s | retry_after=%s",
            tags,
            account.failures(),
            visitor.failures(),
            held_for,
        )
        return LoginAttempt(result=None, error=TOO_MANY_ATTEMPTS, retry_after=held_for)

    result = get_client().login(username, password)
    # Outcome only: a success holds the player's token, username, id and avatar.
    logger.info(
        "bonk login response | result=%s | error=%s | bonk_error=%s | %s",
        "success" if result.ok else "fail",
        result.error,
        result.bonk_error,
        tags,
    )

    if result.ok:
        account.clear()
        return LoginAttempt(result=result)

    if result.error in COUNTED_FAILURES:
        if result.error in ACCOUNT_COUNTED_FAILURES:
            account.record_failure()
        visitor.record_failure()
        # If that was their last try for now, say so on this page already,
        # rather than letting them find out on the next one.
        held_for = max(account.hold_remaining(), visitor.hold_remaining())
        return LoginAttempt(result=result, error=result.error, retry_after=held_for or None)

    if result.error == BonkError.RATE_LIMITED:
        site_wide = math.ceil(rate_limit_cooldowns.remaining(LOGIN_SCRIPT))
        # bonk_error is set only when bonk.io itself just said "ratelimited"
        # to this attempt; empty means we answered from the pause.
        if result.bonk_error:
            _hold_whoever_set_it_off(account, visitor, site_wide, tags)
        return LoginAttempt(result=result, error=result.error, retry_after=site_wide or None)

    return LoginAttempt(result=result, error=result.error)


def _hold_whoever_set_it_off(account: _Tracker, visitor: _Tracker, site_wide: int, tags: str):
    """bonk.io just limited this attempt. If the account or visitor had wrong
    passwords in the window, they most likely set it off: hold them past the
    site-wide pause so someone else's login is the first one bonk.io sees."""
    account_failures = account.failures()
    visitor_failures = visitor.failures()
    if not (account_failures or visitor_failures):
        logger.warning(
            "bonk.io rate-limited a login with no recent wrong passwords from it | %s", tags
        )
        return
    seconds = max(TRIGGER_HOLD_SECONDS, site_wide)
    if account_failures:
        account.hold(seconds)
    if visitor_failures:
        visitor.hold(seconds)
    logger.warning(
        "bonk.io rate-limited a login after wrong passwords; holding it for %ss | %s"
        " | account_failures=%s | client_failures=%s",
        seconds,
        tags,
        account_failures,
        visitor_failures,
    )
