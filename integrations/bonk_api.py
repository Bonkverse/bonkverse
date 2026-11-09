"""bonk.io's account API: logging in, reading friends and changing an avatar.

Owns: the one correct request shape for each bonk.io account script
(`login_legacy.php`, `friends.php`, `avatar_update.php`), headers, timeouts,
JSON parsing, turning bonk.io's error codes into Bonkverse ones, and keeping
tokens out of logs. Every call returns a typed result and never raises for
bonk.io being down or saying no.
Does not own: the site session (core/bonk/session.py), database writes
(friend sync, site accounts) or the messages users see.

Free of Django at import time so it can become part of a bonk.io SDK
(RFC-0001, "Path to an SDK"); `get_client()` builds a client from settings.
Endpoint reference and quirks: docs/bonk/api.md. Recorded responses:
tests/fixtures/bonk/.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field

import requests

from core.bonk import AvatarSlot, BonkUsername, InvalidUsername

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://bonk2.io/scripts"
DEFAULT_TIMEOUT = (4.0, 8.0)  # (connect, read) seconds

LOGIN_SCRIPT = "login_legacy.php"
FRIENDS_SCRIPT = "friends.php"
AVATAR_UPDATE_SCRIPT = "avatar_update.php"

# Sent on every call so bonk.io sees the same request its own web client makes.
# BONK: the account scripts are called cross-origin from https://bonk.io.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    ),
    "Origin": "https://bonk.io",
    "Referer": "https://bonk.io/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


class BonkError:
    """Bonkverse's error codes for bonk.io results (`result.error`).

    bonk.io's own code, when it sent one, is kept separately in
    `result.bonk_error` for logs.
    """

    # bonk.io answered and said no.
    WRONG_PASSWORD = "wrong_password"
    UNKNOWN_USERNAME = "unknown_username"
    TOKEN_REJECTED = "token_rejected"  # expired or invalid token: log in again
    AVATAR_TOO_BIG = "avatar_too_big"  # the skin is over bonk.io's size limit
    # bonk.io is limiting requests. It appears to limit by IP, and every
    # Bonkverse user reaches bonk.io from the server's IP, which Railway may
    # share with others. See RATE_LIMIT_COOLDOWN.
    RATE_LIMITED = "rate_limited"
    REJECTED = "rejected"  # a refusal code we don't recognise (see bonk_error)
    # bonk.io didn't give a usable answer: connection failed, timed out,
    # HTTP error (e.g. a Cloudflare challenge) or a body that isn't JSON.
    # The value is the one the wear endpoints already returned.
    UNAVAILABLE = "network_error"


# BONK: refusals come back as HTTP 200 with {"r": "fail", "e": <code>}. Codes
# seen in production logs or recorded fixtures (docs/bonk/api.md).
_REFUSALS = {
    "password": BonkError.WRONG_PASSWORD,
    "username_fail": BonkError.UNKNOWN_USERNAME,
    "token": BonkError.TOKEN_REJECTED,
    "avatar_too_big": BonkError.AVATAR_TOO_BIG,
    "ratelimited": BonkError.RATE_LIMITED,
}

# After bonk.io says "ratelimited", Bonkverse makes no bonk.io calls for this
# many seconds and answers RATE_LIMITED itself, so we don't add requests while
# bonk.io is limiting the IP. Bursts have been logged since at least
# 2026-10-30, mostly when Bonkverse itself sent little (docs/bonk/api.md).
RATE_LIMIT_COOLDOWN = 120.0

# Cache key holding the wall-clock time (epoch seconds) until which no process
# may call bonk.io. See _Cooldown.
COOLDOWN_STORE_KEY = "bonk:cooldown_until"


class _Cooldown:
    """A "don't call bonk.io until" time shared by every server process.

    The time is kept in this process and, when a `store` is attached, in a
    shared cache (Redis in production) so that one worker hearing
    "ratelimited" pauses all of them. Before 2026-11-09 it lived only in the
    process: with 4 gunicorn workers the other 3 kept calling bonk.io during
    the pause, and a recycled worker forgot it, which kept extending bonk.io's
    limit (incident 2026-11-09).

    `store` is anything with Django-cache-style get/set/delete. If it fails or
    is unreachable, the in-process time still applies.

    Times are wall-clock (time.time) because monotonic clocks differ between
    processes.
    """

    def __init__(self, clock=time.time, store=None):
        self._clock = clock
        self._until = 0.0
        self._lock = threading.Lock()
        self._store = store

    def use_store(self, store) -> None:
        """Share the pause through `store` (e.g. django.core.cache.cache)."""
        self._store = store

    def _shared_until(self) -> float:
        if self._store is None:
            return 0.0
        try:
            value = self._store.get(COOLDOWN_STORE_KEY)
        except Exception:  # the store being down must never break bonk.io calls
            logger.warning("bonk.io cooldown store unreadable; using this process only")
            return 0.0
        try:
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def remaining(self) -> float:
        """Seconds left in the pause (0 when bonk.io may be called)."""
        until = max(self._until, self._shared_until())
        return max(0.0, until - self._clock())

    def active(self) -> bool:
        return self.remaining() > 0

    def start(self, seconds: float) -> None:
        until = self._clock() + seconds
        with self._lock:
            self._until = max(self._until, until)
        if self._store is None:
            return
        try:
            if until > self._shared_until():
                self._store.set(COOLDOWN_STORE_KEY, until, timeout=math.ceil(seconds))
        except Exception:
            logger.warning("bonk.io cooldown store unwritable; pausing this process only")

    def reset(self) -> None:
        with self._lock:
            self._until = 0.0
        if self._store is None:
            return
        try:
            self._store.delete(COOLDOWN_STORE_KEY)
        except Exception:
            pass


rate_limit_cooldown = _Cooldown()


@dataclass(frozen=True)
class BonkLoginResult:
    """What `login_legacy.php` said.

    On success `token`, `username` and (normally) `bonk_id` are set.
    `username` is the account's name exactly as bonk.io spells it, which can
    differ in capitalization from what the player typed.
    """

    ok: bool
    token: str | None = field(default=None, repr=False)
    active_slot: AvatarSlot | None = None
    error: str | None = None
    bonk_error: str | None = None
    username: BonkUsername | None = None
    bonk_id: int | None = None
    # BONK: Flash-era friends arrive in the login response as one string of
    # names separated by "#", not from friends.php.
    legacy_friends: str = field(default="", repr=False)
    # BONK: the account's total XP ("xp"); its level is core.bonk.levels.
    xp: int | None = None


@dataclass(frozen=True)
class BonkFriend:
    """One entry in a friends.php list.

    `name` is exactly as bonk.io sent it, or None when it sent no usable name
    (the id still counts as a friend).
    """

    bonk_id: int
    name: str | None


@dataclass(frozen=True)
class BonkFriendsResult:
    """What `friends.php` said: confirmed friends and incoming requests."""

    ok: bool
    friends: tuple[BonkFriend, ...] = ()
    requests: tuple[BonkFriend, ...] = ()
    error: str | None = None
    bonk_error: str | None = None


@dataclass(frozen=True)
class BonkAvatarUpdateResult:
    """What `avatar_update.php` said."""

    ok: bool
    error: str | None = None
    bonk_error: str | None = None


class _Unavailable(Exception):
    """bonk.io gave no usable answer. Internal: callers get a result instead."""


class _CoolingDown(Exception):
    """bonk.io rate-limited us recently; no call was made. Internal."""


# Matches "token":"<anything up to the next quote>" so a token can be removed
# from a logged snippet without parsing it (snippets may be cut mid-JSON).
_TOKEN_PATTERN = re.compile(r'("token"\s*:\s*")[^"]*(")')
_SNIPPET_LENGTH = 300


def redact(text: str) -> str:
    """`text` with any bonk.io token replaced, for logging response snippets."""
    return _TOKEN_PATTERN.sub(r"\1***REDACTED***\2", text)


class BonkApi:
    """A client for bonk.io's account scripts.

    Args:
        base_url: Where the scripts live, without a trailing slash.
        timeout: (connect, read) timeout in seconds for every call.
        http: Anything with a `requests`-style `post`; a `requests.Session`
            to reuse connections. Defaults to the `requests` module.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout=DEFAULT_TIMEOUT,
        http=None,
        cooldown: _Cooldown | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http = http or requests
        self._cooldown = cooldown or rate_limit_cooldown

    def login(self, username: str, password: str) -> BonkLoginResult:
        """Exchange a bonk.io username and password for a token.

        Args:
            username: As the player typed it; sent unchanged.
            password: Sent to bonk.io only; never logged or stored.

        Returns:
            A BonkLoginResult. `error` is a BonkError code when `ok` is False.
        """
        try:
            # BONK: bonk.io's own web client sends these three fields
            # (docs/bonk/api.md). Bonkverse's wear login used to add
            # task=legacy; the client doesn't, so neither do we.
            data = self._post(
                LOGIN_SCRIPT,
                {"username": username, "password": password, "remember": "false"},
            )
        except _Unavailable:
            return BonkLoginResult(ok=False, error=BonkError.UNAVAILABLE)
        except _CoolingDown:
            return BonkLoginResult(ok=False, error=BonkError.RATE_LIMITED)

        if data.get("r") != "success" or not data.get("token"):
            code = _bonk_code(data)
            return BonkLoginResult(ok=False, error=_refusal(code), bonk_error=code)

        try:
            # BONK: the response carries the account's own spelling of the name.
            canonical = BonkUsername(data.get("username") or username)
        except InvalidUsername:
            logger.warning("bonk.io login succeeded but returned an unusable username")
            return BonkLoginResult(ok=False, error=BonkError.UNAVAILABLE)

        return BonkLoginResult(
            ok=True,
            token=data["token"],
            # BONK: the key is activeAvatarNumber; the lowercase spelling is
            # accepted too because older Bonkverse code expected it.
            active_slot=AvatarSlot.parse(
                data.get("activeAvatarNumber") or data.get("activeavatarnumber")
            ),
            username=canonical,
            bonk_id=_int_or_none(data.get("id")),
            legacy_friends=data.get("legacyFriends") or "",
            xp=_int_or_none(data.get("xp")),
        )

    def get_friends(self, token: str) -> BonkFriendsResult:
        """The player's current bonk.io friends and incoming friend requests.

        Entries whose id isn't a number are dropped; entries without a usable
        name are kept with `name=None`.
        """
        try:
            data = self._post(FRIENDS_SCRIPT, {"token": token, "task": "getfriends"})
        except _Unavailable:
            return BonkFriendsResult(ok=False, error=BonkError.UNAVAILABLE)
        except _CoolingDown:
            return BonkFriendsResult(ok=False, error=BonkError.RATE_LIMITED)

        if data.get("r") != "success":
            code = _bonk_code(data)
            return BonkFriendsResult(ok=False, error=_refusal(code), bonk_error=code)

        return BonkFriendsResult(
            ok=True,
            friends=_parse_friends(data.get("friends")),
            requests=_parse_friends(data.get("requests")),
        )

    def update_avatar(self, token: str, slot: AvatarSlot, skin_code: str) -> BonkAvatarUpdateResult:
        """Put `skin_code` in avatar `slot` of the token's account.

        Only TOKEN_REJECTED means logging in to bonk.io again will help.
        AVATAR_TOO_BIG, RATE_LIMITED, REJECTED (an unknown code) and
        UNAVAILABLE won't be fixed by a new token. Asking for one anyway is
        what made the login modal reappear (2026-11-05 logs).
        """
        try:
            data = self._post(
                AVATAR_UPDATE_SCRIPT,
                {
                    "task": "updateavatar",
                    "token": token,
                    "newavatarslot": str(slot),
                    "newavatar": skin_code,
                },
            )
        except _Unavailable:
            return BonkAvatarUpdateResult(ok=False, error=BonkError.UNAVAILABLE)
        except _CoolingDown:
            return BonkAvatarUpdateResult(ok=False, error=BonkError.RATE_LIMITED)

        if data.get("r") != "success":
            code = _bonk_code(data)
            logger.warning(
                "bonk.io refused avatar update | bonk_error=%s | slot=%s | skin_code_len=%s",
                code,
                slot,
                len(skin_code or ""),
            )
            return BonkAvatarUpdateResult(ok=False, error=_refusal(code), bonk_error=code)
        return BonkAvatarUpdateResult(ok=True)

    def _post(self, script: str, form: dict) -> dict:
        """POST `form` to a bonk.io script and return its JSON object.

        Raises:
            _CoolingDown: bonk.io rate-limited us recently; nothing was sent.
            _Unavailable: no answer, an HTTP error status, or a body that
                isn't a JSON object.
        """
        if self._cooldown.active():
            raise _CoolingDown
        url = f"{self.base_url}/{script}"
        try:
            response = self._http.post(
                url, data=form, headers=BROWSER_HEADERS, timeout=self.timeout
            )
        except requests.RequestException as exc:
            logger.warning("bonk.io %s unreachable: %s", script, type(exc).__name__)
            raise _Unavailable from exc

        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code >= 400 or not isinstance(data, dict):
            snippet = redact(response.text[:_SNIPPET_LENGTH].replace("\n", " "))
            logger.warning(
                "bonk.io %s gave no usable answer | http=%s | body=%s",
                script,
                response.status_code,
                snippet,
            )
            raise _Unavailable
        if _bonk_code(data) == "ratelimited":
            logger.warning(
                "bonk.io rate-limited %s; pausing bonk.io calls for %ss",
                script,
                RATE_LIMIT_COOLDOWN,
            )
            self._cooldown.start(RATE_LIMIT_COOLDOWN)
        return data


def get_client() -> BonkApi:
    """A BonkApi configured from Django settings (base URL and timeouts).

    Also points the process-wide cooldown at Django's cache, so a "ratelimited"
    heard by one gunicorn worker pauses every worker (Redis in production).
    """
    from django.conf import settings
    from django.core.cache import cache

    rate_limit_cooldown.use_store(cache)
    return BonkApi(
        settings.BONK_API_BASE_URL,
        timeout=(settings.BONK_CONNECT_TIMEOUT, settings.BONK_READ_TIMEOUT),
    )


def _bonk_code(data: dict) -> str | None:
    """bonk.io's error code from a failure body.

    # BONK: failures use the key "e"; "error" is accepted in case a script
    # differs, since none of this is documented by bonk.io.
    """
    code = data.get("e") or data.get("error")
    return str(code) if code else None


def _refusal(code: str | None) -> str:
    """Bonkverse's error code for bonk.io's refusal code."""
    return _REFUSALS.get(code, BonkError.REJECTED)


def _int_or_none(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_friends(entries) -> tuple[BonkFriend, ...]:
    parsed = []
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        bonk_id = _int_or_none(entry.get("id"))
        if bonk_id is None:
            continue
        name = entry.get("name")
        parsed.append(BonkFriend(bonk_id, name if isinstance(name, str) and name else None))
    return tuple(parsed)
