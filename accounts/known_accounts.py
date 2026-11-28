"""The login page's "Choose an account": accounts used on this browser.

Owns: the list of bonk.io accounts that signed in on this browser and how
each last did (password or room code; "friend" entries are from before
friend requests were removed on 2026-11-27 and open the room-code way),
kept after signing out so the login page can offer them, like Google's
account chooser.
Does not own: signing in (past the one-click window, choosing one still
needs its password or a room code; see choose_account.html).

The list is a signed, HttpOnly cookie in the browser (no server copy): at
most MAX_ACCOUNTS names, newest first, each dropped after KEEP_DAYS unused.
It holds names and the way in, nothing secret. "Sign out of all accounts"
with "Also forget this device" clears it; each entry has a Remove.
`KnownAccountsMiddleware` writes the cookie when the list changed.
"""

from __future__ import annotations

import json
import time

COOKIE = "bv_known"
COOKIE_SALT = "accounts.known_accounts"
MAX_ACCOUNTS = 8
KEEP_DAYS = 90

PASSWORD = "password"
FRIEND_REQUEST = "friend"
ROOM_CODE = "room"  # experimental, ADR 0026
WAYS = (PASSWORD, FRIEND_REQUEST, ROOM_CODE)


class KnownAccountsMiddleware:
    """Reads the list (`request.bv_known`) and writes the cookie back when
    `remember`, `forget` or `forget_all` changed it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.bv_known = _read(request)
        request.bv_known_changed = False
        response = self.get_response(request)
        if request.bv_known_changed:
            if request.bv_known:
                response.set_signed_cookie(
                    COOKIE,
                    json.dumps(request.bv_known, separators=(",", ":")),
                    salt=COOKIE_SALT,
                    max_age=KEEP_DAYS * 24 * 3600,
                    secure=request.is_secure(),
                    httponly=True,
                    samesite="Lax",
                )
            else:
                response.delete_cookie(COOKIE, samesite="Lax")
        return response


def _read(request) -> list[dict]:
    raw = request.get_signed_cookie(COOKIE, default=None, salt=COOKIE_SALT)
    if not raw:
        return []
    try:
        entries = json.loads(raw)
    except ValueError:
        return []
    cutoff = time.time() - KEEP_DAYS * 24 * 3600
    known = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name, via, at = entry.get("u"), entry.get("via"), entry.get("at")
        if isinstance(name, str) and name and via in WAYS and isinstance(at, int | float):
            if at >= cutoff:
                known.append({"u": name[:64], "via": via, "at": int(at)})
    return known[:MAX_ACCOUNTS]


def accounts(request) -> list[dict]:
    """[{"username", "via"}], newest first."""
    return [{"username": e["u"], "via": e["via"]} for e in getattr(request, "bv_known", [])]


def remember(request, username: str, via: str) -> None:
    """`username` just signed in on this browser by `via`: put it first."""
    if not hasattr(request, "bv_known"):
        return
    key = username.casefold()
    rest = [e for e in request.bv_known if e["u"].casefold() != key]
    request.bv_known = [{"u": username, "via": via, "at": int(time.time())}] + rest
    request.bv_known = request.bv_known[:MAX_ACCOUNTS]
    request.bv_known_changed = True


def forget(request, username: str) -> None:
    """Take one account off this browser's list."""
    if not hasattr(request, "bv_known"):
        return
    key = username.casefold()
    request.bv_known = [e for e in request.bv_known if e["u"].casefold() != key]
    request.bv_known_changed = True


def forget_all(request) -> None:
    """Clear the list ("Also forget this device")."""
    if hasattr(request, "bv_known"):
        request.bv_known = []
        request.bv_known_changed = True


def way_in(request, username: str) -> str | None:
    """How `username` last signed in on this browser, or None."""
    key = username.casefold()
    for entry in getattr(request, "bv_known", []):
        if entry["u"].casefold() == key:
            return entry["via"]
    return None
