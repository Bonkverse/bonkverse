"""Template context every page gets from the players app.

Owns: `viewer_avatar`, the signed-in visitor's worn skin for the site header.
Lazy, so pages that never show it make no query. And `friend_sync_url`: set
once, on the first page after a login that started a friend sync
(accounts/sign_in.py sets the session flag), so that page shows the sync's
progress (players/js/friend_sync.js) wherever the login landed.
"""

from django.urls import reverse
from django.utils.functional import SimpleLazyObject

from . import selectors

FRIEND_SYNC_FLAG = "show_friend_sync_toast"  # set by accounts/sign_in.py


def viewer_avatar(request):
    """{"png": url, "thumbnail": url} for the signed-in visitor's skin, or {}."""
    return {"viewer_avatar": SimpleLazyObject(lambda: selectors.user_skin_avatars(request.user))}


def friend_sync(request):
    """The sync-status URL on the first page after the login, else nothing.
    Popping the flag only writes the session when it was there."""
    session = getattr(request, "session", None)
    if session is None or not session.get(FRIEND_SYNC_FLAG):
        return {}
    session.pop(FRIEND_SYNC_FLAG, None)
    return {"friend_sync_url": reverse("players:friends_sync_status")}
