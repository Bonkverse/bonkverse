import uuid
import re
import os
import base64
from django_ratelimit.decorators import ratelimit
import requests

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.conf import settings
from django.urls import reverse
from django.contrib import messages

from skins.events import log_event
from skins.models import Skin, SkinImage


bonk_url_pattern = r"^https://bonkleagues\.io/s/([A-Za-z0-9]{7})$"
skin_name_pattern = r"^[A-Za-z0-9_ ]+$"

BLSKIN_FETCHER_URL = getattr(
    settings,
    "BLSKIN_FETCHER_URL",
    "https://blskinfetcher-production.up.railway.app/api/getSkin"
)


@login_required(login_url="/login/")
@ratelimit(key="ip", rate="10/m", block=True)
def upload_skin(request):
    if request.method == "POST":
        skin_name = request.POST.get("skin_name", "").strip()
        bonkleagues_link = request.POST.get("bonkleagues_link", "").strip()

        # --- Validation ---
        if not skin_name or not bonkleagues_link:
            messages.error(request, "❌ All fields are required.")
            return render(request, "skins/upload.html")

        if not re.match(skin_name_pattern, skin_name):
            messages.error(
                request,
                "❌ Skin name can only contain letters, numbers, spaces, and underscores."
            )
            return render(request, "skins/upload.html")

        if not re.match(bonk_url_pattern, bonkleagues_link):
            messages.error(request, "❌ Invalid Bonkleagues link format.")
            return render(request, "skins/upload.html")

        if Skin.objects.filter(link=bonkleagues_link).exists():
            messages.error(request, "❌ This Bonkleagues link has already been submitted!")
            return redirect("upload_skin")

        if len(skin_name) > 1000:
            messages.error(request, "❌ Skin name must be under 1000 characters.")
            return render(request, "skins/upload.html")

        # --- Step 1: Ask BLSkinFetcher for skin data + rendered media ---
        try:
            fetch_res = requests.get(
                BLSKIN_FETCHER_URL,
                params={
                    "link": bonkleagues_link,
                    "media": "true",
                },
                timeout=30,
            )
            fetch_res.raise_for_status()
            data = fetch_res.json()
        except Exception as e:
            messages.error(request, f"❌ Could not fetch/render skin: {e}")
            return render(request, "skins/upload.html")

        skin_code = data.get("skinCode")
        media = data.get("media") or {}

        svg_content = media.get("svg")
        png_base64 = media.get("pngBase64")
        thumb_base64 = media.get("thumbnailBase64")

        if not skin_code:
            messages.error(request, "❌ Skin Fetcher did not return a skin code.")
            return render(request, "skins/upload.html")

        if not svg_content or not png_base64:
            messages.error(request, "❌ Skin Fetcher did not return rendered SVG/PNG media.")
            return render(request, "skins/upload.html")

        # --- Step 2: Decode PNG/thumbnail from base64 ---
        try:
            png_content = base64.b64decode(png_base64)

            if thumb_base64:
                thumb_content = base64.b64decode(thumb_base64)
            else:
                thumb_content = png_content

        except Exception as e:
            messages.error(request, f"❌ Could not decode rendered media: {e}")
            return render(request, "skins/upload.html")

        # --- Step 3: Create DB entry first ---
        skin = Skin.objects.create(
            name=skin_name,
            creator=request.user.username,
            link=bonkleagues_link,
            image_url="",
            uuid=uuid.uuid4(),
            skin_code=skin_code
        )

        skin_dir = os.path.join(settings.MEDIA_ROOT, "skins")
        os.makedirs(skin_dir, exist_ok=True)

        svg_rel_path = f"skins/{skin.id}.svg"
        png_rel_path = f"skins/{skin.id}.png"
        thumb_rel_path = f"skins/{skin.id}_thumb.png"

        svg_path = os.path.join(settings.MEDIA_ROOT, svg_rel_path)
        png_path = os.path.join(settings.MEDIA_ROOT, png_rel_path)
        thumb_path = os.path.join(settings.MEDIA_ROOT, thumb_rel_path)

        # --- Step 4: Save SVG + PNG + thumbnail from Skin Fetcher ---
        try:
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)

            with open(png_path, "wb") as f:
                f.write(png_content)

            with open(thumb_path, "wb") as f:
                f.write(thumb_content)

            skin.image_url = f"{settings.MEDIA_URL}{svg_rel_path}"
            skin.save()

        except Exception as e:
            messages.error(request, f"❌ Failed to save rendered media: {e}")

            for file_path in (svg_path, png_path, thumb_path):
                if os.path.exists(file_path):
                    os.remove(file_path)

            skin.delete()
            return render(request, "skins/upload.html")

        # --- Step 5: Save SkinImage records ---
        try:
            SkinImage.objects.bulk_create([
                SkinImage(skin=skin, kind="svg", path=svg_rel_path),
                SkinImage(skin=skin, kind="png", path=png_rel_path),
                SkinImage(skin=skin, kind="thumbnail", path=thumb_rel_path),
            ])
        except Exception as e:
            messages.error(request, f"❌ Failed to save skin image records: {e}")

            for file_path in (svg_path, png_path, thumb_path):
                if os.path.exists(file_path):
                    os.remove(file_path)

            skin.delete()
            return render(request, "skins/upload.html")

        messages.success(request, "✅ Skin uploaded successfully!")
        log_event(request.user, "skin_uploaded", skin=skin, source="bonkleagues")
        return redirect(reverse("search_skins") + f"?q={skin_name}")

    return render(request, "skins/upload.html")