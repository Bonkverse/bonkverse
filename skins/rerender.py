# import os
# import base64
# import requests

# from django.http import JsonResponse
# from django.views.decorators.http import require_POST
# from django.conf import settings
# from django.contrib.auth.decorators import login_required

# from skins.models import Skin, SkinImage

# SKIN_EDITOR_URL = getattr(
#     settings,
#     "BONKVERSE_EDITOR_URL",
#     "https://editor.bonkverse.io"  # set this in your Railway env vars
# )


# def staff_required(view_func):
#     @login_required(login_url="/login/")
#     def wrapper(request, *args, **kwargs):
#         if not getattr(request.user, "is_staff", False):
#             return JsonResponse({"error": "Forbidden"}, status=403)
#         return view_func(request, *args, **kwargs)
#     return wrapper


# @staff_required
# @require_POST
# def rerender_skin(request, skin_id):
#     try:
#         skin = Skin.objects.get(id=skin_id)
#     except Skin.DoesNotExist:
#         return JsonResponse({"error": "Skin not found"}, status=404)

#     if not skin.skin_code:
#         return JsonResponse({"error": "No skin_code stored for this skin"}, status=400)

#     # POST to /api/render-bundle with the stored skin_code
#     try:
#         fetch_res = requests.post(
#             f"{SKIN_EDITOR_URL}/api/render-bundle",
#             json={"skinCode": skin.skin_code, "size": 512},
#             timeout=30,
#         )
#         fetch_res.raise_for_status()
#         data = fetch_res.json()
#     except Exception as e:
#         return JsonResponse({"error": f"Render service error: {e}"}, status=502)

#     if not data.get("ok"):
#         return JsonResponse({"error": data.get("error", "render_failed")}, status=502)

#     svg_content  = data.get("svg")
#     png_base64   = data.get("pngBase64")
#     thumb_base64 = data.get("thumbnailBase64")

#     if not svg_content or not png_base64:
#         return JsonResponse({"error": "Render bundle missing SVG/PNG"}, status=502)

#     try:
#         png_content   = base64.b64decode(png_base64)
#         thumb_content = base64.b64decode(thumb_base64) if thumb_base64 else png_content
#     except Exception as e:
#         return JsonResponse({"error": f"Decode error: {e}"}, status=500)

#     # Overwrite files on disk
#     skin_dir = os.path.join(settings.MEDIA_ROOT, "skins")
#     os.makedirs(skin_dir, exist_ok=True)

#     svg_rel   = f"skins/{skin.id}.svg"
#     png_rel   = f"skins/{skin.id}.png"
#     thumb_rel = f"skins/{skin.id}_thumb.png"

#     try:
#         with open(os.path.join(settings.MEDIA_ROOT, svg_rel), "w", encoding="utf-8") as f:
#             f.write(svg_content)
#         with open(os.path.join(settings.MEDIA_ROOT, png_rel), "wb") as f:
#             f.write(png_content)
#         with open(os.path.join(settings.MEDIA_ROOT, thumb_rel), "wb") as f:
#             f.write(thumb_content)
#     except Exception as e:
#         return JsonResponse({"error": f"File write error: {e}"}, status=500)

#     skin.image_url = f"{settings.MEDIA_URL}{svg_rel}"
#     skin.save(update_fields=["image_url"])

#     for kind, rel_path in [("svg", svg_rel), ("png", png_rel), ("thumbnail", thumb_rel)]:
#         SkinImage.objects.update_or_create(
#             skin=skin, kind=kind,
#             defaults={"path": rel_path}
#         )

#     return JsonResponse({
#         "ok": True,
#         "image_url": skin.image_url,
#         "skin_id": skin.id,
#     })

import os
import base64
import urllib.parse
import requests

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.conf import settings
from django.contrib.auth.decorators import login_required

from skins.models import Skin, SkinImage

SKIN_EDITOR_URL = getattr(
    settings,
    "BONKVERSE_EDITOR_URL",
    "https://editor.bonkverse.io"
)


def staff_required(view_func):
    @login_required(login_url="/login/")
    def wrapper(request, *args, **kwargs):
        if not getattr(request.user, "is_staff", False):
            return JsonResponse({"error": "Forbidden"}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper


def purge_cloudflare_cache(paths: list):
    """Purge specific file paths from Cloudflare's edge cache."""
    zone_id   = getattr(settings, "CLOUDFLARE_ZONE_ID", "")
    api_token = getattr(settings, "CLOUDFLARE_API_TOKEN", "")

    if not zone_id or not api_token:
        return  # not configured — skip silently

    base_url = getattr(settings, "BONKVERSE_BASE_URL", "https://bonkverse.io")
    files = [f"{base_url}{path}" for path in paths]

    try:
        requests.post(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache",
            headers={"Authorization": f"Bearer {api_token}"},
            json={"files": files},
            timeout=10,
        )
    except Exception:
        pass  # non-fatal — cache will expire on its own eventually


@staff_required
@require_POST
def rerender_skin(request, skin_id):
    try:
        skin = Skin.objects.get(id=skin_id)
    except Skin.DoesNotExist:
        return JsonResponse({"error": "Skin not found"}, status=404)

    if not skin.skin_code:
        return JsonResponse({"error": "No skin_code stored for this skin"}, status=400)

    # Skin codes from BonkLeagues imports may be double URL-encoded
    # (%252F instead of %2F). Decode until clean base64.
    skin_code = urllib.parse.unquote(skin.skin_code)
    if "%" in skin_code:
        skin_code = urllib.parse.unquote(skin_code)

    try:
        fetch_res = requests.post(
            f"{SKIN_EDITOR_URL}/api/render-bundle",
            json={"skinCode": skin_code, "size": 512},
            timeout=30,
        )
    except Exception as e:
        return JsonResponse({"error": f"Could not reach render service: {e}"}, status=502)

    if not fetch_res.ok:
        try:
            editor_error = fetch_res.json()
        except Exception:
            editor_error = fetch_res.text
        return JsonResponse({
            "error": f"Render service returned {fetch_res.status_code}",
            "detail": editor_error,
        }, status=502)

    data = fetch_res.json()

    if not data.get("ok"):
        return JsonResponse({"error": data.get("error", "render_failed")}, status=502)

    svg_content  = data.get("svg")
    png_base64   = data.get("pngBase64")
    thumb_base64 = data.get("thumbnailBase64")

    if not svg_content or not png_base64:
        return JsonResponse({"error": "Render bundle missing SVG/PNG"}, status=502)

    try:
        png_content   = base64.b64decode(png_base64)
        thumb_content = base64.b64decode(thumb_base64) if thumb_base64 else png_content
    except Exception as e:
        return JsonResponse({"error": f"Decode error: {e}"}, status=500)

    # Overwrite files on disk (Railway volume — persists across deploys)
    skin_dir = os.path.join(settings.MEDIA_ROOT, "skins")
    os.makedirs(skin_dir, exist_ok=True)

    svg_rel   = f"skins/{skin.id}.svg"
    png_rel   = f"skins/{skin.id}.png"
    thumb_rel = f"skins/{skin.id}_thumb.png"

    try:
        with open(os.path.join(settings.MEDIA_ROOT, svg_rel), "w", encoding="utf-8") as f:
            f.write(svg_content)
        with open(os.path.join(settings.MEDIA_ROOT, png_rel), "wb") as f:
            f.write(png_content)
        with open(os.path.join(settings.MEDIA_ROOT, thumb_rel), "wb") as f:
            f.write(thumb_content)
    except Exception as e:
        return JsonResponse({"error": f"File write error: {e}"}, status=500)

    skin.image_url = f"{settings.MEDIA_URL}{svg_rel}"
    skin.save(update_fields=["image_url"])

    for kind, rel_path in [("svg", svg_rel), ("png", png_rel), ("thumbnail", thumb_rel)]:
        SkinImage.objects.update_or_create(
            skin=skin, kind=kind,
            defaults={"path": rel_path}
        )

    # Purge Cloudflare's cached copies so the new files are served immediately
    purge_cloudflare_cache([
        f"/media/{svg_rel}",
        f"/media/{png_rel}",
        f"/media/{thumb_rel}",
    ])

    return JsonResponse({
        "ok": True,
        "image_url": skin.image_url,
        "skin_id": skin.id,
    })