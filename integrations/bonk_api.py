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

from core.bonk import DEFAULT_SKIN_CODE, AvatarSlot, BonkUsername, InvalidUsername

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://bonk2.io/scripts"
DEFAULT_TIMEOUT = (4.0, 8.0)  # (connect, read) seconds

LOGIN_SCRIPT = "login_legacy.php"
# Remember-me (RFC-0003 Part 2, measured 2026-11-24, docs/bonk/api.md): a
# remember-me token for a fresh session token, and revoking one.
LOGIN_AUTO_SCRIPT = "login_auto.php"
CLEARAUTO_SCRIPT = "login_clearauto.php"
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
    # bonk.io is limiting requests from this IP. Every Bonkverse user reaches
    # bonk.io from the server's IP, so this is everyone's limit. See
    # docs/bonk/login-rate-limit.md, LOGIN_RATE_LIMIT_PAUSE and _Cooldown.
    RATE_LIMITED = "rate_limited"
    # login_auto.php: the remember-me token was revoked or never existed.
    NOT_FOUND = "not_found"
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
    "not_found": BonkError.NOT_FOUND,
}

# After bonk.io says "ratelimited" for a script, Bonkverse stops calling that
# script and answers RATE_LIMITED itself, so we don't add requests while bonk.io
# is limiting the IP.
#
# login_legacy.php: one fixed pause, no checks inside it. Measured on
# 2026-11-10 (docs/bonk/login-rate-limit.md): bonk.io's block lasts about 15
# minutes after the LAST request it saw from the IP, and every request during
# the block, even a correct password, starts the 15 minutes over. A correct
# login every minute stayed blocked for 45 minutes; one single login after 20
# minutes worked. The old 2/4/8/16-minute checks each landed inside the block
# and restarted it, which is why 2026-11-09 had outages of over an hour.
# 17 minutes leaves room for clock and network differences.
LOGIN_RATE_LIMIT_PAUSE = 17 * 60.0

# Other scripts (friends.php, avatar_update.php) haven't been measured, so
# they keep the doubling pause: 2, 4, 8, 16 minutes, then 30 at most, starting
# over once bonk.io answers that script normally.
RATE_LIMIT_COOLDOWN = 120.0  # the first pause
RATE_LIMIT_COOLDOWN_MAX = 1800.0
# How long a run of limits is remembered. A limit after this much quiet starts
# again at RATE_LIMIT_COOLDOWN.
RATE_LIMIT_STRIKE_MEMORY = 3600


def backoff_seconds(strikes: int, script: str | None = None) -> float:
    """The pause after `strikes` limits in a row for `script`.

    login_legacy.php: always LOGIN_RATE_LIMIT_PAUSE. Others: 120, 240, 480, ...
    up to 1800.
    """
    if script == LOGIN_SCRIPT:
        return LOGIN_RATE_LIMIT_PAUSE
    return min(RATE_LIMIT_COOLDOWN * 2 ** max(strikes - 1, 0), RATE_LIMIT_COOLDOWN_MAX)


class _Cooldown:
    """A "don't call this bonk.io script until" time, shared by every process.

    One per script: bonk.io seems to limit each script on its own. On
    2026-11-09 login_legacy.php and friends.php answered normally one second
    before avatar_update.php said "ratelimited", while a shared pause had been
    turning away logins that would have worked.

    The pause and the count of limits in a row live in this process and, when
    a `store` is attached, in a shared cache (Redis in production), so one
    worker hearing "ratelimited" pauses all of them (before 2026-11-09 the
    other workers kept calling). `store` is anything with Django-cache-style
    get/set/add/incr/touch/delete; if it fails, this process's copy still
    applies.

    Times are wall-clock (time.time) because monotonic clocks differ between
    processes.
    """

    def __init__(self, scope: str, clock=time.time, store=None):
        self.scope = scope
        self._clock = clock
        self._store = store
        self._until = 0.0
        self._strikes = 0
        self._lock = threading.Lock()
        self._until_key = f"bonk:cooldown_until:{scope}"
        self._strikes_key = f"bonk:cooldown_strikes:{scope}"

    def use_store(self, store) -> None:
        self._store = store

    def _store_call(self, method: str, *args, **kwargs):
        """Call the shared store; None if there is none or it failed."""
        if self._store is None:
            return None
        try:
            return getattr(self._store, method)(*args, **kwargs)
        except Exception:  # the store being down must never break bonk.io calls
            logger.warning("bonk.io cooldown store failed (%s); using this process only", method)
            return None

    def _shared_until(self) -> float:
        value = self._store_call("get", self._until_key)
        try:
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def remaining(self) -> float:
        """Seconds left in the pause (0 when the script may be called)."""
        until = max(self._until, self._shared_until())
        return max(0.0, until - self._clock())

    def active(self) -> bool:
        return self.remaining() > 0

    def start(self, seconds: float) -> None:
        """Pause for at least `seconds` (never shortens a longer pause)."""
        until = self._clock() + seconds
        with self._lock:
            self._until = max(self._until, until)
        if until > self._shared_until():
            self._store_call("set", self._until_key, until, timeout=math.ceil(seconds))

    def strike(self) -> tuple[float, int]:
        """bonk.io said "ratelimited": pause (see backoff_seconds).

        Returns (seconds paused, limits in a row).
        """
        with self._lock:
            self._strikes += 1
            strikes = self._strikes
        self._store_call("add", self._strikes_key, 0, timeout=RATE_LIMIT_STRIKE_MEMORY)
        shared = self._store_call("incr", self._strikes_key)
        if isinstance(shared, int) and shared > 0:
            strikes = shared
            self._store_call("touch", self._strikes_key, RATE_LIMIT_STRIKE_MEMORY)
        seconds = backoff_seconds(strikes, self.scope)
        self.start(seconds)
        return seconds, strikes

    def clear(self) -> None:
        """bonk.io answered this script normally: the next limit starts over."""
        with self._lock:
            had_local = self._strikes > 0
            self._strikes = 0
        if had_local or self._store_call("get", self._strikes_key):
            self._store_call("delete", self._strikes_key)

    def reset(self) -> None:
        with self._lock:
            self._until = 0.0
            self._strikes = 0
        self._store_call("delete", self._until_key)
        self._store_call("delete", self._strikes_key)


class _Cooldowns:
    """The cooldown for each bonk.io script, sharing one clock and store.

    With `django_cache` (the process-wide `rate_limit_cooldowns`), the first
    read or write connects to Django's cache (Redis in production), so a
    pause another process heard applies here before this process has called
    bonk.io itself. Before 2026-11-24 only `get_client()` connected it, so a
    fresh worker asking "is bonk.io paused?" first was told no.
    """

    def __init__(self, clock=time.time, store=None, *, django_cache: bool = False):
        self._clock = clock
        self._store = store
        self._django_cache = django_cache
        self._lock = threading.Lock()
        self._by_script: dict[str, _Cooldown] = {}
        for script in (
            LOGIN_SCRIPT,
            LOGIN_AUTO_SCRIPT,
            CLEARAUTO_SCRIPT,
            FRIENDS_SCRIPT,
            AVATAR_UPDATE_SCRIPT,
        ):
            self.for_script(script)

    def use_store(self, store) -> None:
        """Share every pause through `store` (e.g. django.core.cache.cache)."""
        with self._lock:
            self._store = store
            for cooldown in self._by_script.values():
                cooldown.use_store(store)

    def _connect_django_cache(self) -> None:
        """Use Django's cache as the store, once, when asked to and none is set."""
        if self._store is not None or not self._django_cache:
            return
        try:
            from django.conf import settings

            if not settings.configured:
                return
            from django.core.cache import cache
        except Exception:  # no Django here: this process's copy still applies
            return
        self.use_store(cache)

    def for_script(self, script: str) -> _Cooldown:
        # Outside the lock: use_store takes it too.
        self._connect_django_cache()
        with self._lock:
            if script not in self._by_script:
                self._by_script[script] = _Cooldown(script, self._clock, self._store)
            return self._by_script[script]

    def remaining(self, script: str) -> float:
        """Seconds until `script` may be called again (0 if it may now).

        A login pause stops every script, not just login_legacy.php: bonk.io
        restarts its login block on any request from the IP during it
        (2026-11-10, the 00:59 re-trip after two wears; RFC-0003 Part 1, item
        6). So this is the longer of the script's own pause and the login
        pause.
        """
        own = self.for_script(script).remaining()
        if script == LOGIN_SCRIPT:
            return own
        return max(own, self.for_script(LOGIN_SCRIPT).remaining())

    def login_paused(self) -> bool:
        """Whether bonk.io's login pause is on (every script waits for it)."""
        return self.for_script(LOGIN_SCRIPT).active()

    def reset(self) -> None:
        for cooldown in list(self._by_script.values()):
            cooldown.reset()


rate_limit_cooldowns = _Cooldowns(django_cache=True)


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
    # The skin code in the account's active slot: what the player wears in
    # game. An empty slot is bonk.io's default skin (DEFAULT_SKIN_CODE).
    # None only when there's no active slot or the slot held something
    # other than a string. Unchecked here; callers check it with
    # core.bonk.SkinCode.
    skin_code: str | None = field(default=None, repr=False)
    # BONK: the login answer carries the account's friend list ("friends"),
    # entries shaped like friends.php's ({id, name, roomid}); seen in the
    # owner's capture of bonk.io's own client on 2026-11-23 (1,229 friends;
    # tests/fixtures/bonk/login_success_with_friends.json). That answer had
    # no incoming requests ("requests"); the field is read in case it ever
    # appears. Each is None when the key is missing or isn't a list, and
    # callers fall back to friends.php (RFC-0003 phase 2).
    friends: tuple[BonkFriend, ...] | None = field(default=None, repr=False)
    requests: tuple[BonkFriend, ...] | None = field(default=None, repr=False)
    # BONK: with remember: true the login answer's rememberToken holds a
    # remember-me token (77 characters); with remember: false it's "". None
    # when there was none, and always None from login_auto.php, which
    # doesn't rotate it (lab, 2026-11-24).
    remember_token: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class BonkClearResult:
    """What `login_clearauto.php` said."""

    ok: bool
    error: str | None = None
    bonk_error: str | None = None


@dataclass(frozen=True)
class BonkFriend:
    """One entry in a friends.php list.

    `name` is exactly as bonk.io sent it, or None when it sent no usable name
    (the id still counts as a friend).
    """

    bonk_id: int
    name: str | None
    # Incoming requests only: when it was sent, exactly as bonk.io wrote it
    # ("2026-11-10 21:39:07", US Eastern, no zone). None for friends.
    date: str | None = None


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
    """bonk.io rate-limited this script recently; no call was made. Internal."""


# Matches "token":"..." and "rememberToken":"..." (anything up to the next
# quote) so a token can be removed from a logged snippet without parsing it
# (snippets may be cut mid-JSON).
_TOKEN_PATTERN = re.compile(r'("(?:token|rememberToken)"\s*:\s*")[^"]*(")')
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
        cooldowns: _Cooldowns | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http = http or requests
        self._cooldowns = cooldowns or rate_limit_cooldowns

    def login(self, username: str, password: str, *, remember: bool = False) -> BonkLoginResult:
        """Exchange a bonk.io username and password for a token.

        Args:
            username: As the player typed it; sent unchanged.
            password: Sent to bonk.io only; never logged or stored.
            remember: Ask for a remember-me token too (`remember_token`).

        Returns:
            A BonkLoginResult. `error` is a BonkError code when `ok` is False.
        """
        try:
            # BONK: bonk.io's own web client sends these three fields
            # (docs/bonk/api.md). Bonkverse's wear login used to add
            # task=legacy; the client doesn't, so neither do we.
            data = self._post(
                LOGIN_SCRIPT,
                {
                    "username": username,
                    "password": password,
                    "remember": "true" if remember else "false",
                },
            )
        except _Unavailable:
            return BonkLoginResult(ok=False, error=BonkError.UNAVAILABLE)
        except _CoolingDown:
            return BonkLoginResult(ok=False, error=BonkError.RATE_LIMITED)
        return _login_result(data, username)

    def login_auto(self, remember_token: str) -> BonkLoginResult:
        """Exchange a remember-me token for a fresh session token, no password.

        Answers like `login` (token, friends, xp, slot) but never with a new
        remember-me token. A revoked token is NOT_FOUND. During bonk.io's
        login pause nothing is sent (RATE_LIMITED): a request during the
        block seems to restart it (docs/bonk/login-rate-limit.md).
        """
        try:
            data = self._post(LOGIN_AUTO_SCRIPT, {"rememberToken": remember_token})
        except _Unavailable:
            return BonkLoginResult(ok=False, error=BonkError.UNAVAILABLE)
        except _CoolingDown:
            return BonkLoginResult(ok=False, error=BonkError.RATE_LIMITED)
        return _login_result(data, "")

    def clear_auto(self, remember_token: str) -> BonkClearResult:
        """Revoke one remember-me token (bonk.io's own logout does this). The
        account's other remember-me tokens keep working."""
        try:
            data = self._post(CLEARAUTO_SCRIPT, {"rememberToken": remember_token})
        except _Unavailable:
            return BonkClearResult(ok=False, error=BonkError.UNAVAILABLE)
        except _CoolingDown:
            return BonkClearResult(ok=False, error=BonkError.RATE_LIMITED)
        if data.get("r") != "success":
            code = _bonk_code(data)
            return BonkClearResult(ok=False, error=_refusal(code), bonk_error=code)
        return BonkClearResult(ok=True)

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

    def delete_friend_request(self, token: str, bonk_id: int) -> BonkClearResult:
        """Delete (not accept) the friend request `bonk_id` sent to the token's
        account. Used by friend-request linking (accounts/link_claims.py): the
        bot account never needs friends.

        BONK: task "deleterequest" with theirid; seen in the WolfRichie
        Demystify-Bonk notes and used by BonxBot since 2026-11-17.
        """
        try:
            data = self._post(
                FRIENDS_SCRIPT, {"token": token, "task": "deleterequest", "theirid": str(bonk_id)}
            )
        except _Unavailable:
            return BonkClearResult(ok=False, error=BonkError.UNAVAILABLE)
        except _CoolingDown:
            return BonkClearResult(ok=False, error=BonkError.RATE_LIMITED)
        if data.get("r") not in ("success", "delete_success", "deleterequest_success"):
            code = _bonk_code(data)
            return BonkClearResult(ok=False, error=_refusal(code), bonk_error=code)
        return BonkClearResult(ok=True)

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
            _CoolingDown: bonk.io rate-limited this script recently; nothing
                was sent.
            _Unavailable: no answer, an HTTP error status, or a body that
                isn't a JSON object.
        """
        cooldown = self._cooldowns.for_script(script)
        # The script's own pause, or the login pause, which stops every script.
        remaining = self._cooldowns.remaining(script)
        if remaining > 0:
            logger.info(
                "bonk.io %s paused for another %ss; answered rate_limited without calling it",
                script,
                math.ceil(remaining),
            )
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
            seconds, strikes = cooldown.strike()
            logger.warning(
                "bonk.io rate-limited %s (%s in a row); pausing %s calls for %ss",
                script,
                strikes,
                script,
                int(seconds),
            )
        else:
            cooldown.clear()
        return data


def get_client() -> BonkApi:
    """A BonkApi configured from Django settings (base URL and timeouts).

    Also points the process-wide cooldowns at Django's cache, so a "ratelimited"
    heard by one gunicorn worker pauses every worker (Redis in production).
    """
    from django.conf import settings
    from django.core.cache import cache

    rate_limit_cooldowns.use_store(cache)
    return BonkApi(
        settings.BONK_API_BASE_URL,
        timeout=(settings.BONK_CONNECT_TIMEOUT, settings.BONK_READ_TIMEOUT),
    )


def _login_result(data: dict, typed_username: str) -> BonkLoginResult:
    """A BonkLoginResult from a login_legacy.php or login_auto.php answer."""
    if data.get("r") != "success" or not data.get("token"):
        code = _bonk_code(data)
        return BonkLoginResult(ok=False, error=_refusal(code), bonk_error=code)

    try:
        # BONK: the response carries the account's own spelling of the name.
        canonical = BonkUsername(data.get("username") or typed_username)
    except InvalidUsername:
        logger.warning("bonk.io login succeeded but returned an unusable username")
        return BonkLoginResult(ok=False, error=BonkError.UNAVAILABLE)

    # BONK: the key is activeAvatarNumber; the lowercase spelling is
    # accepted too because older Bonkverse code expected it.
    active_slot = AvatarSlot.parse(data.get("activeAvatarNumber") or data.get("activeavatarnumber"))
    remember = data.get("rememberToken")
    return BonkLoginResult(
        ok=True,
        token=data["token"],
        active_slot=active_slot,
        username=canonical,
        bonk_id=_int_or_none(data.get("id")),
        legacy_friends=data.get("legacyFriends") or "",
        xp=_int_or_none(data.get("xp")),
        skin_code=_slot_skin_code(data, active_slot),
        friends=_friend_list_or_none(data.get("friends")),
        requests=_friend_list_or_none(data.get("requests")),
        remember_token=remember if isinstance(remember, str) and remember else None,
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


def _slot_skin_code(data: dict, slot: AvatarSlot | None) -> str | None:
    """The skin code in `slot`: bonk.io's default skin if the slot is empty,
    None if there's no slot or it held something that isn't a code."""
    if slot is None:
        return None
    # BONK: each slot's skin code is its own key, "avatar1" to "avatar5"
    # (DemystifyBonk's login notes). A slot that was never worn comes back
    # "" or null, and bonk.io shows the default skin for it.
    value = data.get(f"avatar{slot.number}")
    if value is None or value == "":
        return DEFAULT_SKIN_CODE
    return value if isinstance(value, str) else None


def _int_or_none(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _friend_list_or_none(entries) -> tuple[BonkFriend, ...] | None:
    """A friend list from a login answer, or None when there wasn't one."""
    if not isinstance(entries, list):
        return None
    return _parse_friends(entries)


def _parse_friends(entries) -> tuple[BonkFriend, ...]:
    parsed = []
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        bonk_id = _int_or_none(entry.get("id"))
        if bonk_id is None:
            continue
        name = entry.get("name")
        date = entry.get("date")
        parsed.append(
            BonkFriend(
                bonk_id,
                name if isinstance(name, str) and name else None,
                date if isinstance(date, str) and date else None,
            )
        )
    return tuple(parsed)
