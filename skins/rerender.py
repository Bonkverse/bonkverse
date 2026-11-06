"""Re-rendering a gallery skin's images from its stored code (staff only).

Owns: the /skins/<id>/rerender/ endpoint, overwriting the skin's SVG, PNG and
thumbnail files, updating its image rows, and asking Cloudflare to drop the
old cached copies.
Does not own: rendering (integrations/editor_render.py), the cache purge
request (integrations/cloudflare.py) or SVG safety rules (svg_sanitizer.py).

Replies are JSON for the button on the search page, which shows `error` to
staff as-is, so `error` is always a readable sentence. Service details go to
the server log only.
"""

import functools
import logging
import os

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.bonk import SkinCode
from core.ratelimits import limit
from integrations.cloudflare import purge_media_paths
from integrations.editor_render import render_skin_code
from skins.events import log_event
from skins.models import Skin, SkinImage
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

    if not skin.skin_code:
        return _error("This skin has no stored skin code to render.", 400)

    # Stored codes may be URL-encoded once or twice (BonkLeagues imports).
    result = render_skin_code(SkinCode(skin.skin_code).decoded)
    if result.error:
        logger.warning("rerender skin %s: render failed: %s", skin.id, result.error)
        return _error("The render service couldn't render this skin. Try again later.", 502)
    rendered = result.skin

    # Same check as every other way a skin's SVG reaches /media/.
    try:
        validate_svg_upload(rendered.svg)
    except SVGTooLargeError:
        return _error(TOO_LARGE_MESSAGE, 422)
    except UnsafeSVGError as exc:
        logger.warning("rerender skin %s: rendered SVG rejected: %s", skin.id, exc)
        return _error("The rendered image failed the SVG safety check; nothing was changed.", 422)

    files = {
        "svg": (f"skins/{skin.id}.svg", rendered.svg.encode("utf-8")),
        "png": (f"skins/{skin.id}.png", rendered.png),
        "thumbnail": (f"skins/{skin.id}_thumb.png", rendered.thumbnail),
    }
    # Overwrites the files in place (Railway volume; persists across deploys).
    try:
        os.makedirs(os.path.join(settings.MEDIA_ROOT, "skins"), exist_ok=True)
        for rel_path, content in files.values():
            with open(os.path.join(settings.MEDIA_ROOT, rel_path), "wb") as f:
                f.write(content)
    except OSError:
        logger.exception("rerender skin %s: could not write media files", skin.id)
        return _error("Couldn't save the new images. Try again later.", 500)

    skin.image_url = f"{settings.MEDIA_URL}{files['svg'][0]}"
    skin.save(update_fields=["image_url"])
    for kind, (rel_path, _) in files.items():
        SkinImage.objects.update_or_create(skin=skin, kind=kind, defaults={"path": rel_path})

    # Drop Cloudflare's cached copies so the new files show immediately. A
    # failure is logged by the client; the copies expire on their own anyway.
    purge = purge_media_paths([f"/media/{rel_path}" for rel_path, _ in files.values()])

    log_event(request.user, "skin_rerendered", skin=skin)
    return JsonResponse(
        {
            "ok": True,
            "image_url": skin.image_url,
            "skin_id": skin.id,
            "cache_purged": purge.ok,
        }
    )
