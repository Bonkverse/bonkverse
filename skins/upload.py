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
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.conf import settings
from django.urls import reverse
from django.contrib import messages
from skins.models import Skin
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

        # --- Fetch SVG directly from Bonkleagues ---
        svg_url = f"{bonkleagues_link}.svg"
        try:
            r = requests.get(svg_url, timeout=10)
            r.raise_for_status()
        except Exception:
            messages.error(request, "❌ Could not fetch SVG for this skin.")
            return render(request, "skins/upload.html")

        svg_content = r.content

        # --- Ensure media directory exists ---
        skin_dir = os.path.join(settings.MEDIA_ROOT, "skins")
        os.makedirs(skin_dir, exist_ok=True)

        # Temporary ID for filenames (DB pk will be assigned after save)
        temp_id = Skin.objects.count() + 1

        # File paths
        svg_path = os.path.join(skin_dir, f"{temp_id}.svg")
        png_path = os.path.join(skin_dir, f"{temp_id}.png")
        thumb_path = os.path.join(skin_dir, f"{temp_id}_thumb.png")

        # Save SVG
        with open(svg_path, "wb") as f:
            f.write(svg_content)

        # Convert to PNG (512px)
        cairosvg.svg2png(bytestring=svg_content, write_to=png_path, output_width=512, output_height=512)

        # Convert to thumbnail (128px)
        cairosvg.svg2png(bytestring=svg_content, write_to=thumb_path, output_width=128, output_height=128)

        # --- Save skin in DB ---
        skin = Skin.objects.create(
            name=skin_name,
            creator=request.user.username,
            link=bonkleagues_link,
            image_url=f"{settings.MEDIA_URL}skins/{temp_id}.png"  # main PNG as preview
        )

        messages.success(request, "✅ Skin uploaded successfully!")
        return redirect(reverse("search_skins") + f"?q={skin_name}")

    return render(request, "skins/upload.html")
