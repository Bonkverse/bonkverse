# from django.contrib.auth.decorators import login_required
# from django.shortcuts import render, redirect
# from django.http import JsonResponse
# from django.conf import settings
# from django.urls import reverse
# from django.contrib import messages
# from skins.models import Skin
# from skins.utils.fetch_skin_image_url import fetch_skin_image_url  # You should have this as a separate utility
# import re

# bonk_url_pattern = r"^https://bonkleagues\.io/s/([A-Za-z0-9]{7})$"
# skin_name_pattern = r"^[A-Za-z0-9_ ]+$"

# @login_required(login_url='/login/')
# def upload_skin(request):
#     if request.method == "POST":
#         skin_name = request.POST.get("skin_name", "").strip()
#         bonkleagues_link = request.POST.get("bonkleagues_link", "").strip()

#         if not skin_name or not bonkleagues_link:
#             messages.error(request, "❌ All fields are required.")
#             return render(request, "skins/upload.html")

#         if not re.match(skin_name_pattern, skin_name):
#             messages.error(request, "❌ Skin name can only contain letters, numbers, spaces, and underscores.")
#             return render(request, "skins/upload.html")

#         if not re.match(bonk_url_pattern, bonkleagues_link):
#             messages.error(request, "❌ Invalid Bonkleagues link format.")
#             return render(request, "skins/upload.html")

#         if Skin.objects.filter(link=bonkleagues_link).exists():
#             messages.error(request, "❌ This Bonkleagues link has already been submitted!")
#             return redirect("upload_skin")

#         if len(skin_name) > 1000:
#             messages.error(request, "❌ Skin name must be under 1000 characters.")
#             return render(request, "skins/upload.html")

#         # Fetch image
#         skin_image_url = fetch_skin_image_url(bonkleagues_link)
#         if not skin_image_url:
#             messages.error(request, "❌ Could not fetch skin image from Bonkleagues.")
#             return render(request, "skins/upload.html")

#         # Save with logged-in user's username
#         Skin.objects.create(
#             name=skin_name,
#             creator=request.user.username,
#             link=bonkleagues_link,
#             image_url=skin_image_url
#         )

#         messages.success(request, "✅ Skin uploaded successfully!")
#         return redirect(reverse("search_skins") + f"?q={skin_name}")

#     return render(request, "skins/upload.html")

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.conf import settings
from django.urls import reverse
from django.contrib import messages
from skins.models import Skin, SkinImage
from skins.utils.fetch_skin_image_url import fetch_skin_image_url
import re
import os
import requests
import cairosvg

# Patterns for validation
bonk_url_pattern = r"^https://bonkleagues\.io/s/([A-Za-z0-9]{7})$"
skin_name_pattern = r"^[A-Za-z0-9_ ]+$"


@login_required(login_url='/login/')
def upload_skin(request):
    if request.method == "POST":
        skin_name = request.POST.get("skin_name", "").strip()
        bonkleagues_link = request.POST.get("bonkleagues_link", "").strip()

        # --- Validation ---
        if not skin_name or not bonkleagues_link:
            messages.error(request, "❌ All fields are required.")
            return render(request, "skins/upload.html")

        if not re.match(skin_name_pattern, skin_name):
            messages.error(request, "❌ Skin name can only contain letters, numbers, spaces, and underscores.")
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

        # --- Step 1: Fetch preview image (fallback check) ---
        skin_image_url = fetch_skin_image_url(bonkleagues_link)
        if not skin_image_url:
            messages.error(request, "❌ Could not fetch preview image from Bonkleagues.")
            return render(request, "skins/upload.html")

        # --- Step 2: Try fetching the raw SVG ---
        svg_url = f"{bonkleagues_link}.svg"
        try:
            r = requests.get(svg_url, timeout=10)
            r.raise_for_status()
            svg_content = r.content
        except Exception:
            messages.error(request, "❌ Could not fetch SVG for this skin. Upload cancelled.")
            return render(request, "skins/upload.html")

        # --- Step 3: Save files locally ---
        skin_dir = os.path.join(settings.MEDIA_ROOT, "skins")
        os.makedirs(skin_dir, exist_ok=True)

        # Temporarily reserve filenames using count+1 (safe once DB saves skin.id)
        temp_id = Skin.objects.count() + 1
        svg_path = os.path.join(skin_dir, f"{temp_id}.svg")
        png_path = os.path.join(skin_dir, f"{temp_id}.png")
        thumb_path = os.path.join(skin_dir, f"{temp_id}_thumb.png")

        try:
            # Save SVG
            with open(svg_path, "wb") as f:
                f.write(svg_content)

            # Convert PNG + thumbnail
            cairosvg.svg2png(bytestring=svg_content, write_to=png_path, output_width=512, output_height=512)
            cairosvg.svg2png(bytestring=svg_content, write_to=thumb_path, output_width=128, output_height=128)

        except Exception as e:
            messages.error(request, f"❌ Failed to generate PNG/thumbnail: {e}")
            # Clean up half-written files
            for path in (svg_path, png_path, thumb_path):
                if os.path.exists(path):
                    os.remove(path)
            return render(request, "skins/upload.html")

        # --- Step 4: Save skin in DB ---
        skin = Skin.objects.create(
            name=skin_name,
            creator=request.user.username,
            link=bonkleagues_link,
            image_url=f"{settings.MEDIA_URL}skins/{temp_id}.png"
        )

        # --- Step 5: Save SkinImage entries ---
        SkinImage.objects.bulk_create([
            SkinImage(skin=skin, kind="svg", path=f"skins/{skin.id}.svg"),
            SkinImage(skin=skin, kind="png", path=f"skins/{skin.id}.png"),
            SkinImage(skin=skin, kind="thumbnail", path=f"skins/{skin.id}_thumb.png"),
        ])

        messages.success(request, "✅ Skin uploaded successfully!")
        return redirect(reverse("search_skins") + f"?q={skin_name}")

    return render(request, "skins/upload.html")
