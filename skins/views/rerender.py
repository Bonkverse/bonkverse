"""The staff Re-render button: POST /skins/<id>/rerender/.

Replies are JSON for the button on the search page, which shows `error` to
staff as-is, so `error` is always a readable sentence. Service details go to
the server log only. The re-render itself is skins/rerender.py.
"""

import functools

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.ratelimits import limit
from integrations.cloudflare import purge_media_paths
from skins.events import log_event
from skins.models import Skin
from skins.rerender import RerenderError, rerender
from skins.svg_sanitizer import TOO_LARGE_MESSAGE


def staff_required(view_func):
    @functools.wraps(view_func)
    @login_required(login_url="/login/")
    def wrapper(request, *args, **kwargs):
        if not getattr(request.user, "is_staff", False):
            return JsonResponse({"error": "Forbidden"}, status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


# What staff see on the search page for each failure, and the HTTP status.
_ERROR_REPLIES = {
    RerenderError.NO_CODE: ("This skin has no stored skin code to render.", 400),
    RerenderError.RENDER_FAILED: (
        "The render service couldn't render this skin. Try again later.",
        502,
    ),
    RerenderError.TOO_LARGE: (TOO_LARGE_MESSAGE, 422),
    RerenderError.UNSAFE: (
        "The rendered image failed the SVG safety check; nothing was changed.",
        422,
    ),
    RerenderError.STORAGE_FAILED: ("Couldn't save the new images. Try again later.", 500),
}


def _error(message: str, status: int) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


@staff_required
@require_POST
@limit("write")
def rerender_skin(request, skin_id):
    try:
        skin = Skin.objects.get(id=skin_id)
    except Skin.DoesNotExist:
        return _error("Skin not found.", 404)

    result = rerender(skin)
    if result.error:
        return _error(*_ERROR_REPLIES[result.error])

    # Drop Cloudflare's cached copies so the new files show immediately. A
    # failure is logged by the client; the copies expire on their own anyway.
    purge = purge_media_paths([f"/media/{rel_path}" for rel_path in result.paths.values()])

    log_event(request.user, "skin_rerendered", skin=skin)
    return JsonResponse(
        {
            "ok": True,
            "image_url": skin.image_url,
            "skin_id": skin.id,
            "cache_purged": purge.ok,
        }
    )
