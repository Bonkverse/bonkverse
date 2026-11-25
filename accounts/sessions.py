"""How long a Bonkverse sign-in lasts: 90 days, renewed as the player visits.

Owns: renewing a signed-in player's session as they use the site.
Does not own: the session itself (Django's, settings.SESSION_COOKIE_AGE) or
the bonk.io connection inside it (core/bonk/session.py), which has its own,
much shorter life.

Why (RFC-0003 phase 2): Django ends a session 2 weeks after it was last
saved, and getting back in meant typing a bonk.io password: another call on
the server's shared login budget. Signing in to Bonkverse now lasts 90 days
from the last visit; browsing, favorites, votes and settings don't need
bonk.io at all.

A session is only re-saved once a day (RENEW_EVERY_SECONDS), so a visit
doesn't write the session row on every request. Logging in counts as a
renewal (mark_renewed_on_login): the login saves the session anyway, so the
first page after it doesn't write again.
"""

import time

# Session key: when this session was last renewed (Unix seconds).
RENEWED_AT = "session_renewed_at"
RENEW_EVERY_SECONDS = 24 * 60 * 60


def mark_renewed_on_login(sender, request, user, **kwargs):
    """user_logged_in receiver (accounts/apps.py): a fresh login is a fresh
    90 days, so the next renewal is due a day from now."""
    if request is not None and hasattr(request, "session"):
        request.session[RENEWED_AT] = time.time()


class SessionRenewalMiddleware:
    """Push a signed-in player's session expiry forward, at most once a day.

    Marking the session modified makes SessionMiddleware save it with a fresh
    expiry and send the cookie again with a fresh max-age.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            renewed = request.session.get(RENEWED_AT)
            now = time.time()
            if not isinstance(renewed, (int, float)) or now - renewed >= RENEW_EVERY_SECONDS:
                request.session[RENEWED_AT] = now
        return self.get_response(request)


def end_other_sessions(user_id: int, keep_key: str | None) -> int:
    """Sign every other browser out of `user_id`: sessions where it's the
    account in use or one of the browser's signed-in or unlocked accounts
    (groups.py). Used when a password reclaims an account someone else had
    claimed by friend request (sign_in._reclaim). Scans live sessions, so
    it runs on the worker. Returns how many sessions ended."""
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    ended = 0
    live = Session.objects.filter(expire_date__gt=timezone.now())
    if keep_key:
        live = live.exclude(session_key=keep_key)
    for session in live.iterator():
        try:
            data = session.get_decoded()
        except Exception:  # an unreadable session can't hold the account
            continue
        holds = str(data.get("_auth_user_id")) == str(user_id) or any(
            user_id in (data.get(key) or []) for key in ("bv_signed_in", "bv_unlocked")
        )
        if holds:
            session.delete()
            ended += 1
    return ended
