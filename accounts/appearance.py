"""Saving a signed-in player's appearance (theme and seasonal switch) to
their account, so it follows them to other devices.

Owns: the account's theme, seasonal and appearance_at fields, and keeping
them in step with the Bonkverse/ui cookies.
Does not own: applying the theme (Bonkverse/ui theme.js does that, before
the page paints, from the cookies).

How it works. The choice lives in cookies on .bonkverse.io that every
Bonkverse site shares: bv-theme, bv-season ("on" or "off") and
bv-appearance-at, the time of the choice in milliseconds, which theme.js
stamps on every change (on any site). On each signed-in request to
bonkverse.io, AppearanceMiddleware compares that time with the account's:

- the cookie is newer: the account takes the cookie's choice;
- the account is newer (or this browser has no choice yet): the response
  sets the cookies from the account, so theme.js on this very page applies
  it (a browser processes Set-Cookie before it runs the page's scripts).

So a choice made on the replay site or the docs reaches the account the
next time that browser loads a bonkverse.io page (or asks /api/me/, which
those sites' headers do on every page).
"""

import logging

from django.db import DatabaseError

logger = logging.getLogger(__name__)

THEME_COOKIE = "bv-theme"
SEASON_COOKIE = "bv-season"
AT_COOKIE = "bv-appearance-at"
ONE_YEAR = 60 * 60 * 24 * 365


def _cookie_at(request) -> int:
    try:
        return int(request.COOKIES.get(AT_COOKIE, ""))
    except ValueError:
        return 0


def from_cookies(request, user) -> bool:
    """Save the browser's choice to the account if it's newer. Returns True
    when the account changed."""
    at = _cookie_at(request)
    if not at or at <= (user.appearance_at or 0):
        return False
    theme = request.COOKIES.get(THEME_COOKIE, "")
    season = request.COOKIES.get(SEASON_COOKIE, "")
    user.theme = theme if theme in user.THEMES else user.theme
    if season in ("on", "off"):
        user.seasonal = season == "on"
    user.appearance_at = at
    user.save(update_fields=["theme", "seasonal", "appearance_at"])
    return True


def needs_cookies(request, user) -> bool:
    """The account holds a choice this browser doesn't have yet."""
    return bool(user.appearance_at) and user.appearance_at > _cookie_at(request)


def set_cookies(request, response, user) -> None:
    """Give this browser the account's choice, on every Bonkverse site."""
    host = request.get_host().split(":")[0]
    domain = ".bonkverse.io" if host == "bonkverse.io" or host.endswith(".bonkverse.io") else None
    values = {
        SEASON_COOKIE: "on" if user.seasonal else "off",
        AT_COOKIE: str(user.appearance_at),
    }
    if user.theme:
        values[THEME_COOKIE] = user.theme
    for name, value in values.items():
        # Not HttpOnly: theme.js reads them before the page paints.
        response.set_cookie(
            name,
            value,
            max_age=ONE_YEAR,
            domain=domain,
            samesite="Lax",
            secure=request.is_secure(),
        )


def for_api(user) -> dict:
    """The account's appearance, for /api/me/."""
    return {
        "theme": user.theme or None,
        "seasonal": user.seasonal,
        "at": user.appearance_at,
    }


class AppearanceMiddleware:
    """Keeps the signed-in account and the browser's appearance cookies in
    step (see the module docstring). Runs after AuthenticationMiddleware.
    Never breaks a page: a failed save is logged and skipped."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        signed_in = user is not None and user.is_authenticated
        if signed_in and request.method == "GET":
            try:
                from_cookies(request, user)
            except DatabaseError:  # never block the page over a preference
                logger.exception("appearance: not saved for user=%s", user.pk)
        response = self.get_response(request)
        if signed_in and request.method == "GET" and needs_cookies(request, user):
            set_cookies(request, response, user)
        return response
