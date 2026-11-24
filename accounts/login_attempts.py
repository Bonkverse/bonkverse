"""Logging in to bonk.io for a player, with Bonkverse's guards on the shared budget.

Owns: the one way the site tries a bonk.io username and password (the /login/
page and the in-page login on wear both call `attempt_login`), the guards in
front of that call, and the log line for every attempt.
Does not own: the bonk.io call (integrations/bonk_api.py) or bonk.io's own
pause after a "ratelimited" (the cooldown there), the sentences players see
(login_messages.py), or the per-IP request tier on the login views
(core/ratelimits.py, "login").

Why (docs/bonk/login-rate-limit.md, RFC-0003 Part 1): bonk.io limits
login_legacy.php by IP, and every Bonkverse login leaves from the server's
one IP. From there bonk.io blocks every login, correct passwords included, for
about 15 minutes after roughly 3 wrong passwords site-wide (2026-11-10, three
trips after exactly 3), or after a fast burst of logins even with none wrong
(2026-11-10 00:40, a bot logging in 10 alts 17 times in 100 s from rotating
IPs). So the budget is shared by everyone on the site, and per-visitor limits
alone can't protect it.

The guards, checked in this order before bonk.io sees anything:
1. Holds: this account (from this visitor) or this visitor used up its wrong
   passwords, or its unknown usernames, or was held when bonk.io limited us.
2. The site-wide wrong-password budget: after BONK_LOGIN_LIMITS
   site_wrong_passwords wrong passwords in 15 minutes, new logins wait until
   the oldest ages out, instead of one of them spending bonk.io's third.
3. The "not a bot" check (Cloudflare Turnstile, bot_check.py), when this
   visitor or the site looks risky (looks_risky).
4. One login at a time per account and visitor, so a double submit is one try.
5. Caps on logins sent per minute: per bonk.io account, then site-wide.
When bonk.io answers "ratelimited" anyway, every account and visitor with a
wrong password in the window is held past the pause, not whoever came next.

Each limit is a setting (BONK_LOGIN_LIMITS) so it can be tuned from the logs.

Every attempt is logged with a pseudonym for the account and the visitor
(core/pseudonym.py), never the name or IP, so a run of wrong passwords and the
rate limit that follows can be traced to one person.
"""

from __future__ import annotations

import logging
import math
import time
from contextlib import contextmanager
from dataclasses import dataclass

from django.conf import settings
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

# The attempt lines keep the logger name they had before this module moved to
# accounts/ (RFC-0001 5.5), so Railway searches like @logger:skins.login still
# find old and new lines alike.
logger = logging.getLogger("skins.login")

# Bonkverse's own refusals: bonk.io never saw the attempt. Not BonkErrors.
# This account or visitor has used up its wrong passwords for now.
TOO_MANY_ATTEMPTS = "too_many_attempts"
# Enough wrong passwords were typed on the site lately that one more could
# make bonk.io pause logins for everyone; new logins wait.
SITE_WAIT = "site_wait"
# More logins this minute than the site (or this account) sends to bonk.io.
BUSY = "busy"
# The login needed the "not a bot" check (bot_check.py) and didn't pass it.
BOT_CHECK = "bot_check"
# This account and visitor already have a login waiting on bonk.io.
IN_PROGRESS = "login_in_progress"

# Failures that count: bonk.io answered and said the login was wrong. Rate
# limits and network errors aren't the player's fault and don't count.
COUNTED_FAILURES = {BonkError.WRONG_PASSWORD, BonkError.UNKNOWN_USERNAME}

# How long failures are remembered, counted from the first one. bonk.io's own
# window looks like 15 minutes (docs/bonk/login-rate-limit.md).
FAILURE_WINDOW = 15 * 60
# How long a hold lasts once an allowance is used up, and at least how long
# everyone with a recent wrong password is held when bonk.io limits us.
HOLD_SECONDS = 15 * 60
# Longest a login can hold its account's in-flight lock: longer than the
# bonk.io (connect + read) timeout, so a stuck call can't lock an account.
IN_FLIGHT_SECONDS = 15
# How long BUSY asks to wait when the cache can't say.
BUSY_RETRY_SECONDS = 60
# When bonk.io limits us, everyone with a recent wrong password is held this
# much longer than bonk.io's pause, so none of their retries is the first
# login bonk.io sees when it ends (a request during the block restarts it).
AFTER_PAUSE_SECONDS = 5 * 60
# Where the site's recent wrong passwords are kept (who and when).
_SITE_FAILURES_KEY = "login:site_failures"


def _now() -> float:
    """The current Unix time. One place, so tests can move the clock."""
    return time.time()


def limits() -> dict[str, int]:
    """The current guard settings (settings.BONK_LOGIN_LIMITS)."""
    return settings.BONK_LOGIN_LIMITS


@dataclass(frozen=True)
class LoginAttempt:
    """What happened when a player tried to log in.

    `result` is bonk.io's answer, or None when Bonkverse turned the attempt
    away without asking bonk.io (`error` is then one of TOO_MANY_ATTEMPTS,
    SITE_WAIT, BUSY or IN_PROGRESS).
    `retry_after` is the seconds to wait when waiting will help: bonk.io's
    pause, a hold, the site-wide wait, or a wrong password that used up the
    last try.
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


def _cache(method: str, *args, **kwargs):
    """Call Django's cache (Redis in production); None if it failed.

    If the cache fails, logins go ahead unguarded: the guards are a courtesy
    to bonk.io, and must never be the reason a player can't log in.
    """
    try:
        return getattr(cache, method)(*args, **kwargs)
    except Exception:
        logger.warning("login attempt cache failed (%s); not limiting this login", method)
        return None


class _Tracker:
    """Failure counts and holds for one subject (an account from a visitor, a
    visitor's wrong passwords, or a visitor's unknown usernames).

    Kept in the cache so every gunicorn worker sees the same counts.
    """

    def __init__(self, kind: str, key: str, allowed: int):
        self.kind = kind
        self.key = key
        self.allowed = allowed
        self._failures_key = f"login:failures:{kind}:{key}"
        self._hold_key = f"login:hold:{kind}:{key}"

    def hold_remaining(self) -> int:
        until = _cache("get", self._hold_key)
        try:
            return max(0, math.ceil(float(until) - _now())) if until else 0
        except (TypeError, ValueError):
            return 0

    def failures(self) -> int:
        value = _cache("get", self._failures_key)
        return value if isinstance(value, int) else 0

    def hold(self, seconds: float) -> None:
        """Hold this subject for at least `seconds` (never shortens a hold)."""
        seconds = math.ceil(seconds)
        if seconds > self.hold_remaining():
            _cache("set", self._hold_key, _now() + seconds, timeout=seconds)

    def record_failure(self) -> int:
        """Count one wrong try; hold the subject once its allowance is used up.

        Returns the failures counted in the current window.
        """
        _cache("add", self._failures_key, 0, timeout=FAILURE_WINDOW)
        count = _cache("incr", self._failures_key)
        if not isinstance(count, int):
            return 0
        if count >= self.allowed:
            self.hold(HOLD_SECONDS)
        return count

    def clear(self) -> None:
        _cache("delete_many", [self._failures_key, self._hold_key])


class _SiteFailures:
    """The site's wrong passwords in the last FAILURE_WINDOW: when, and whose.

    One list in the cache of (time, account key, visitor key). Read and
    written without a lock: logins are a few a minute, and a lost entry only
    means one wrong password goes uncounted, the same as the cache being down.
    """

    def _entries(self) -> list[tuple[float, str, str]]:
        value = _cache("get", _SITE_FAILURES_KEY)
        if not isinstance(value, list):
            return []
        cutoff = _now() - FAILURE_WINDOW
        return [entry for entry in value if _valid_entry(entry) and entry[0] > cutoff]

    def wait(self) -> int:
        """Seconds new logins must wait, 0 if the budget allows one more."""
        entries = self._entries()
        budget = limits()["site_wrong_passwords"]
        if budget <= 0 or len(entries) < budget:
            return 0
        # Wait until enough have aged out that one more fits.
        times = sorted(entry[0] for entry in entries)
        frees_at = times[len(times) - budget] + FAILURE_WINDOW
        return max(1, math.ceil(frees_at - _now()))

    def record(self, account_key: str, visitor_key: str) -> None:
        entries = self._entries()
        entries.append((_now(), account_key, visitor_key))
        _cache("set", _SITE_FAILURES_KEY, entries, timeout=FAILURE_WINDOW)

    def who(self) -> list[tuple[str, str]]:
        """(account key, visitor key) for every wrong password in the window."""
        return [(entry[1], entry[2]) for entry in self._entries()]


def _valid_entry(entry) -> bool:
    return (
        isinstance(entry, (list, tuple))
        and len(entry) == 3
        and isinstance(entry[0], (int, float))
        and isinstance(entry[1], str)
        and isinstance(entry[2], str)
    )


def _seconds_to_next_minute() -> int:
    return 60 - int(_now()) % 60


def _over_cap(key: str, cap: int) -> bool:
    """Count one login in this minute's bucket for `key`; True if over `cap`.

    Fixed one-minute buckets. A cap of 0 or less turns the cap off.
    """
    if cap <= 0:
        return False
    bucket = f"login:cap:{key}:{int(_now()) // 60}"
    _cache("add", bucket, 0, timeout=120)
    count = _cache("incr", bucket)
    return isinstance(count, int) and count > cap


@contextmanager
def _in_flight(account_key: str):
    """Hold this account-and-visitor's one-login-at-a-time lock.

    Yields True if this request holds it (or the cache is down), False if
    another login for the same account from the same visitor is still waiting
    on bonk.io. cache.add is atomic (Redis SET NX).
    """
    key = f"login:inflight:{account_key}"
    added = _cache("add", key, 1, timeout=IN_FLIGHT_SECONDS)
    if added is False:
        yield False
        return
    try:
        yield True
    finally:
        if added:
            _cache("delete", key)


def attempt_login(request, username: str, password: str, *, via: str) -> LoginAttempt:
    """Try a bonk.io login unless one of the guards turns it away.

    Args:
        request: The Django request (for the visitor's IP).
        username: As the player typed it; sent to bonk.io unchanged.
        password: Sent to bonk.io only; never logged or stored.
        via: Which form it came from, for the log line ("page" or "wear").

    Returns:
        A LoginAttempt. When a guard turns it away, bonk.io isn't called.
    """
    name = normalize_username(username)
    ip = client_ip(request)
    account_tag = pseudonym("account", name)
    client_tag = pseudonym("client", ip)
    config = limits()
    # The account count is per name AND visitor: nobody else's wrong
    # passwords can hold your account.
    account_key = pseudonym("account_client", f"{name}\n{ip}")
    account = _Tracker("account", account_key, config["account_wrong_passwords"])
    visitor = _Tracker("client", client_tag, config["visitor_wrong_passwords"])
    guesses = _Tracker("client_names", client_tag, config["visitor_unknown_usernames"])
    site = _SiteFailures()
    tags = f"account={account_tag} | client={client_tag} | via={via}"

    held_for = max(account.hold_remaining(), visitor.hold_remaining(), guesses.hold_remaining())
    if held_for:
        logger.info(
            "bonk login held | %s | account_failures=%s | client_failures=%s | retry_after=%s",
            tags,
            account.failures(),
            visitor.failures(),
            held_for,
        )
        return LoginAttempt(result=None, error=TOO_MANY_ATTEMPTS, retry_after=held_for)

    paused = rate_limit_cooldowns.login_paused()
    if not paused:
        wait = site.wait()
        if wait:
            logger.info("bonk login waiting for the site budget | %s | retry_after=%s", tags, wait)
            return LoginAttempt(result=None, error=SITE_WAIT, retry_after=wait)

    from . import bot_check  # imports this module

    if bot_check.wanted(request) and not bot_check.passes(request):
        logger.info("bonk login needs the bot check | %s", tags)
        return LoginAttempt(result=None, error=BOT_CHECK)

    with _in_flight(account_key) as acquired:
        if not acquired:
            logger.info("bonk login already in flight | %s", tags)
            return LoginAttempt(result=None, error=IN_PROGRESS, retry_after=5)

        # During bonk.io's pause the client answers without calling it, so the
        # caps don't count those tries.
        if not paused and (
            _over_cap(f"account:{account_tag}", config["account_per_minute"])
            or _over_cap("site", config["site_per_minute"])
        ):
            retry_after = _seconds_to_next_minute() or BUSY_RETRY_SECONDS
            logger.info("bonk login busy | %s | retry_after=%s", tags, retry_after)
            return LoginAttempt(result=None, error=BUSY, retry_after=retry_after)

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

    if result.error == BonkError.WRONG_PASSWORD:
        account.record_failure()
        visitor.record_failure()
        site.record(account.key, visitor.key)
        # If that was their last try for now, say so on this page already,
        # rather than letting them find out on the next one.
        held_for = max(account.hold_remaining(), visitor.hold_remaining())
        return LoginAttempt(result=result, error=result.error, retry_after=held_for or None)

    if result.error == BonkError.UNKNOWN_USERNAME:
        # bonk.io doesn't count these against the IP, so only the visitor's
        # looser count does, and only to stop guessing names through us.
        guesses.record_failure()
        return LoginAttempt(
            result=result, error=result.error, retry_after=guesses.hold_remaining() or None
        )

    if result.error == BonkError.RATE_LIMITED:
        site_wide = math.ceil(rate_limit_cooldowns.remaining(LOGIN_SCRIPT))
        # bonk_error is set only when bonk.io itself just said "ratelimited"
        # to this attempt; empty means we answered from the pause.
        if result.bonk_error:
            _hold_everyone_who_spent_it(site, site_wide, tags)
        return LoginAttempt(result=result, error=result.error, retry_after=site_wide or None)

    return LoginAttempt(result=result, error=result.error)


def looks_risky(request) -> bool:
    """Whether a login from this visitor now should pass the bot check.

    True when the visitor had a wrong password or unknown username in the
    window, the site is one wrong password from its budget, or this minute's
    logins are one short of the site-wide cap.
    """
    client_tag = pseudonym("client", client_ip(request))
    if (
        _Tracker("client", client_tag, 1).failures()
        or _Tracker("client_names", client_tag, 1).failures()
    ):
        return True
    config = limits()
    budget = config["site_wrong_passwords"]
    if budget > 0 and len(_SiteFailures().who()) >= max(budget - 1, 1):
        return True
    cap = config["site_per_minute"]
    if cap > 1:
        count = _cache("get", f"login:cap:site:{int(_now()) // 60}")
        if isinstance(count, int) and count >= cap - 1:
            return True
    return False


def _hold_everyone_who_spent_it(site: _SiteFailures, site_wide: int, tags: str) -> None:
    """bonk.io just limited the site. Hold every account and visitor with a
    wrong password in the window past the pause, so none of them is the first
    login bonk.io sees when it ends.

    Not just whoever's login got the "ratelimited": on 2026-11-10 that was
    often an innocent login that came next, while the visitors who spent the
    budget weren't held.
    """
    who = site.who()
    if not who:
        logger.warning("bonk.io rate-limited a login with no recent wrong passwords | %s", tags)
        return
    seconds = max(HOLD_SECONDS, site_wide + AFTER_PAUSE_SECONDS)
    allowed = 1  # only holds are set here; the allowance doesn't matter
    for account_key, visitor_key in set(who):
        _Tracker("account", account_key, allowed).hold(seconds)
        _Tracker("client", visitor_key, allowed).hold(seconds)
    logger.warning(
        "bonk.io rate-limited logins after %s wrong passwords; holding %s visitors for %ss | %s",
        len(who),
        len({visitor_key for _, visitor_key in who}),
        seconds,
        tags,
    )
