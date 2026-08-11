import uuid
import os
import re
import cairosvg

from django.http import JsonResponse, HttpResponseBadRequest
from django.urls import reverse
from django.conf import settings

from skins.events import log_event
from skins.models import Skin, SkinImage
from skins.auth_guards import api_login_required

# Validation
SKIN_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _]+$")


@api_login_required
def publish_skin(request):
    """
    Publish a skin from the Bonkverse skin editor.
    Expected POST (multipart/form-data): skin_name, skin_code, svg.
    `creator` is derived from the authenticated user.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid request method")

    skin_name = request.POST.get("skin_name", "").strip()
    skin_code = request.POST.get("skin_code", "").strip()
    creator = (getattr(request.user, "username", "") or request.POST.get("creator", "")).strip()

    svg_file = request.FILES.get("svg")
    svg_text = request.POST.get("svg")

    if not skin_name or not skin_code:
        return JsonResponse({"error": "skin_name and skin_code are required"}, status=400)
    if not creator:
        return JsonResponse({"error": "could not determine creator"}, status=400)
    if not SKIN_NAME_PATTERN.match(skin_name):
        return JsonResponse(
            {"error": "Skin name can only contain letters, numbers, spaces, and underscores"},
            status=400,
        )
    if len(skin_name) > 1000:
        return JsonResponse({"error": "Skin name must be under 1000 characters"}, status=400)
    if not svg_file and not svg_text:
        return JsonResponse({"error": "SVG content is required"}, status=400)

    try:
        svg_content = svg_file.read() if svg_file else svg_text.encode("utf-8")
    except Exception as e:
        return JsonResponse({"error": f"Failed to read SVG content: {e}"}, status=400)

    skin = Skin.objects.create(
        name=skin_name,
        creator=creator,
        skin_code=skin_code,
        image_url="",
        uuid=uuid.uuid4(),
    )

    skin_dir = os.path.join(settings.MEDIA_ROOT, "skins")
    os.makedirs(skin_dir, exist_ok=True)
    svg_path = os.path.join(skin_dir, f"{skin.id}.svg")
    png_path = os.path.join(skin_dir, f"{skin.id}.png")
    thumb_path = os.path.join(skin_dir, f"{skin.id}_thumb.png")

    try:
        with open(svg_path, "wb") as f:
            f.write(svg_content)
        cairosvg.svg2png(bytestring=svg_content, write_to=png_path, output_width=512, output_height=512)
        cairosvg.svg2png(bytestring=svg_content, write_to=thumb_path, output_width=128, output_height=128)
        skin.image_url = f"{settings.MEDIA_URL}skins/{skin.id}.svg"
        skin.save()
    except Exception as e:
        for path in (svg_path, png_path, thumb_path):
            if os.path.exists(path):
                os.remove(path)
        skin.delete()
        return JsonResponse({"error": f"Failed to generate skin images: {e}"}, status=500)

    SkinImage.objects.bulk_create([
        SkinImage(skin=skin, kind="svg", path=f"skins/{skin.id}.svg"),
        SkinImage(skin=skin, kind="png", path=f"skins/{skin.id}.png"),
        SkinImage(skin=skin, kind="thumbnail", path=f"skins/{skin.id}_thumb.png"),
    ])

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