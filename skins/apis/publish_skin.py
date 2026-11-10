"""Publishing a skin from the Bonkverse skin editor (POST /api/skins/publish/).

Owns: the endpoint, its validation and its JSON reply.
Does not own: SVG safety rules (svg_sanitizer.py) or writing the files and
image rows (skin_media.py).
"""

import logging
import re
import uuid

from django.http import HttpResponseNotAllowed, JsonResponse
from django.urls import reverse

from core.ratelimits import limit
from skins.events import log_event
from skins.models import Skin
from skins.skin_media import bundle_from_svg, save_render
from skins.auth_guards import api_login_required
from skins.svg_sanitizer import (
    TOO_LARGE_MESSAGE,
    SVGTooLargeError,
    UnsafeSVGError,
    validate_svg_upload,
)

logger = logging.getLogger(__name__)

# Validation
SKIN_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _]+$")


@api_login_required
@limit("upload")
def publish_skin(request):
    """
    Publish a skin from the Bonkverse skin editor.
    Expected POST (multipart/form-data): skin_name, skin_code, svg.
    `creator` is the authenticated user's username; a `creator` field is ignored.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"], "Invalid request method")

    skin_name = request.POST.get("skin_name", "").strip()
    skin_code = request.POST.get("skin_code", "").strip()
    # The signed-in account's bonk.io name, exactly as spelled: never trimmed
    # (spaces are part of real names), and never taken from the form.
    creator = request.user.username

    svg_file = request.FILES.get("svg")
    svg_text = request.POST.get("svg")

    if not skin_name or not skin_code:
        return JsonResponse({"error": "skin_name and skin_code are required"}, status=422)
    if not creator:
        return JsonResponse({"error": "could not determine creator"}, status=400)
    if not SKIN_NAME_PATTERN.match(skin_name):
        return JsonResponse(
            {"error": "Skin name can only contain letters, numbers, spaces, and underscores"},
            status=422,
        )
    if len(skin_name) > 1000:
        return JsonResponse({"error": "Skin name must be under 1000 characters"}, status=422)
    if not svg_file and not svg_text:
        return JsonResponse({"error": "SVG content is required"}, status=422)

    try:
        svg_content = svg_file.read() if svg_file else svg_text.encode("utf-8")
    except Exception as e:
        return JsonResponse({"error": f"Failed to read SVG content: {e}"}, status=400)

    # Reject active content (script, event handlers, javascript:/data: URIs,
    # foreignObject, ...) before anything is written to disk or the DB.
    try:
        validate_svg_upload(svg_content)
    except SVGTooLargeError:
        return JsonResponse({"error": TOO_LARGE_MESSAGE}, status=422)
    except UnsafeSVGError as e:
        return JsonResponse({"error": f"Unsafe SVG rejected: {e}"}, status=422)

    # The editor sends only the SVG; the PNG and thumbnail are drawn here.
    try:
        bundle = bundle_from_svg(svg_content)
    except Exception as e:
        return JsonResponse({"error": f"Failed to generate skin images: {e}"}, status=500)

    skin = Skin.objects.create(
        name=skin_name,
        creator=creator,
        skin_code=skin_code,
        image_url="",
        uuid=uuid.uuid4(),
    )
    try:
        save_render(skin, bundle)
    except OSError as e:
        logger.exception("publish skin %s: could not write media files", skin.id)
        skin.delete()
        return JsonResponse({"error": f"Failed to generate skin images: {e}"}, status=500)

    share_url = request.build_absolute_uri(
        reverse("share_skin", kwargs={"skin_id": skin.id, "uuid": skin.uuid})
    )

    log_event(request.user, "skin_uploaded", skin=skin, source="editor")
    return JsonResponse(
        {
            "success": True,
            "skin": {
                "id": skin.id,
                "uuid": str(skin.uuid),
                "name": skin.name,
                "creator": skin.creator,
                "image_url": skin.image_url,
                "share_url": share_url,
            },
        },
        status=201,
    )
