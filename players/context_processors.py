"""Template context every page gets from the players app.

Owns: `viewer_avatar`, the signed-in visitor's worn skin for the site header
and My Profile. Lazy, so pages that never show it make no query.
"""

from django.utils.functional import SimpleLazyObject

from . import selectors


def viewer_avatar(request):
    """{"png": url, "thumbnail": url} for the signed-in visitor's skin, or {}."""
    return {"viewer_avatar": SimpleLazyObject(lambda: selectors.user_skin_avatars(request.user))}
