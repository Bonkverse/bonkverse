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

        # --- Step 1: Get the preview/SVG url (Bonkleagues serves the skin as SVG here) ---
        skin_image_url = fetch_skin_image_url(bonkleagues_link)
        if not skin_image_url:
            messages.error(request, "❌ Could not fetch skin image from Bonkleagues.")
            return render(request, "skins/upload.html")

        # --- Step 2: Download the SVG from skin_image_url (same as fetch_svg.py) ---
        try:
            r = requests.get(skin_image_url, timeout=10)
            r.raise_for_status()
            svg_content = r.content
        except Exception as e:
            messages.error(request, f"❌ Could not fetch SVG for this skin: {e}")
            return render(request, "skins/upload.html")

        # --- Step 3: Create DB entry first (no image_url yet) ---
        skin = Skin.objects.create(
            name=skin_name,
            creator=request.user.username,
            link=bonkleagues_link,
            image_url=""  # temporary
        )

        skin_dir = os.path.join(settings.MEDIA_ROOT, "skins")
        os.makedirs(skin_dir, exist_ok=True)

        svg_path = os.path.join(skin_dir, f"{skin.id}.svg")
        png_path = os.path.join(skin_dir, f"{skin.id}.png")
        thumb_path = os.path.join(skin_dir, f"{skin.id}_thumb.png")

        try:
            # Save SVG
            with open(svg_path, "wb") as f:
                f.write(svg_content)

            # Generate PNG + thumbnail
            cairosvg.svg2png(bytestring=svg_content, write_to=png_path, output_width=512, output_height=512)
            cairosvg.svg2png(bytestring=svg_content, write_to=thumb_path, output_width=128, output_height=128)

            # Now update Skin.image_url to point at our local SVG
            skin.image_url = f"{settings.MEDIA_URL}skins/{skin.id}.svg"
            skin.save()

        except Exception as e:
            messages.error(request, f"❌ Failed to generate PNG/thumbnail: {e}")
            # Clean up half-written files
            for path in (svg_path, png_path, thumb_path):
                if os.path.exists(path):
                    os.remove(path)
            skin.delete()
            return render(request, "skins/upload.html")

        # --- Step 4: Save SkinImage entries ---
        SkinImage.objects.bulk_create([
            SkinImage(skin=skin, kind="svg", path=f"skins/{skin.id}.svg"),
            SkinImage(skin=skin, kind="png", path=f"skins/{skin.id}.png"),
            SkinImage(skin=skin, kind="thumbnail", path=f"skins/{skin.id}_thumb.png"),
        ])

        messages.success(request, "✅ Skin uploaded successfully!")
        return redirect(reverse("search_skins") + f"?q={skin_name}")

    return render(request, "skins/upload.html")

