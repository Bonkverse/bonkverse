"""Re-rendering a gallery skin's images from its stored code (staff only).

Owns: re-rendering one skin (`rerender`, also used by the rerender_skins
command), the /skins/<id>/rerender/ endpoint, and asking Cloudflare to drop
the old cached copies of the skin's files.
Does not own: rendering (integrations/editor_render.py), writing the files and
image rows (skin_media.py), the cache purge request (integrations/cloudflare.py)
or SVG safety rules (svg_sanitizer.py).

Replies are JSON for the button on the search page, which shows `error` to
staff as-is, so `error` is always a readable sentence. Service details go to
the server log only.
"""

import functools
import logging
from dataclasses import dataclass

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.bonk import SkinCode
from core.ratelimits import limit
from integrations.cloudflare import purge_media_paths
from integrations.editor_render import render_skin_code
from skins.events import log_event
from skins.models import Skin
from skins.skin_media import RenderBundle, save_render
from skins.svg_sanitizer import (
    TOO_LARGE_MESSAGE,
    SVGTooLargeError,
    UnsafeSVGError,
    validate_svg_upload,
)

logger = logging.getLogger(__name__)


def staff_required(view_func):
    @functools.wraps(view_func)
    @login_required(login_url="/login/")
    def wrapper(request, *args, **kwargs):
        if not getattr(request.user, "is_staff", False):
            return JsonResponse({"error": "Forbidden"}, status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


class RerenderError:
    """`RerenderResult.error` codes. Every one leaves the skin's old images in place."""

    NO_CODE = "no_code"  # nothing to render from
    RENDER_FAILED = "render_failed"  # the editor's render service failed
    TOO_LARGE = "too_large"  # rendered SVG over the size limit
    UNSAFE = "unsafe_svg"  # rendered SVG failed the safety check
    STORAGE_FAILED = "storage_failed"  # couldn't write the files


@dataclass(frozen=True)
class RerenderResult:
    paths: dict[str, str] | None = None  # {kind: path under MEDIA_ROOT} on success
    error: str | None = None


def rerender(skin: Skin) -> RerenderResult:
    """Render a skin from its stored code and replace its image files and rows.

    Doesn't purge Cloudflare or log an event: the caller decides (one skin,
    or every skin with one purge at the end). Points image_url at the skin's
    own /media/ files, whatever it pointed at before.
    """
    if not skin.skin_code:
        return RerenderResult(error=RerenderError.NO_CODE)

    # Stored codes may be URL-encoded once or twice (BonkLeagues imports).
    result = render_skin_code(SkinCode(skin.skin_code).decoded)
    if result.error:
        logger.warning("rerender skin %s: render failed: %s", skin.id, result.error)
        return RerenderResult(error=RerenderError.RENDER_FAILED)
    rendered = result.skin

    # Same check as every other way a skin's SVG reaches /media/.
    try:
        validate_svg_upload(rendered.svg)
    except SVGTooLargeError:
        return RerenderResult(error=RerenderError.TOO_LARGE)
    except UnsafeSVGError as exc:
        logger.warning("rerender skin %s: rendered SVG rejected: %s", skin.id, exc)
        return RerenderResult(error=RerenderError.UNSAFE)

    # Replaces the files on the media volume; a failed write keeps the old ones.
    bundle = RenderBundle(
        svg=rendered.svg.encode("utf-8"), png=rendered.png, thumbnail=rendered.thumbnail
    )
    try:
        return RerenderResult(paths=save_render(skin, bundle))
    except OSError:
        logger.exception("rerender skin %s: could not write media files", skin.id)
        return RerenderResult(error=RerenderError.STORAGE_FAILED)


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
