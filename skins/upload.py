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

        # --- Step 1: Fetch preview image (always reliable) ---
        skin_image_url = fetch_skin_image_url(bonkleagues_link)
        if not skin_image_url:
            messages.error(request, "❌ Could not fetch preview image from Bonkleagues.")
            return render(request, "skins/upload.html")

        # --- Step 2: Save skin DB entry first ---
        skin = Skin.objects.create(
            name=skin_name,
            creator=request.user.username,
            link=bonkleagues_link,
            image_url=skin_image_url  # fallback preview, will update if PNG is saved
        )

        # --- Step 3: Try fetching the raw SVG ---
        svg_url = f"{bonkleagues_link}.svg"
        try:
            r = requests.get(svg_url, timeout=10)
            r.raise_for_status()
            svg_content = r.content

            # Ensure media dir
            skin_dir = os.path.join(settings.MEDIA_ROOT, "skins")
            os.makedirs(skin_dir, exist_ok=True)

            # Paths
            svg_path = os.path.join(skin_dir, f"{skin.id}.svg")
            png_path = os.path.join(skin_dir, f"{skin.id}.png")
            thumb_path = os.path.join(skin_dir, f"{skin.id}_thumb.png")

            # Save SVG
            with open(svg_path, "wb") as f:
                f.write(svg_content)

            # Convert PNG + thumbnail
            cairosvg.svg2png(bytestring=svg_content, write_to=png_path, output_width=512, output_height=512)
            cairosvg.svg2png(bytestring=svg_content, write_to=thumb_path, output_width=128, output_height=128)

            # Update skin to point to our PNG instead of Bonkleagues
            skin.image_url = f"{settings.MEDIA_URL}skins/{skin.id}.png"
            skin.save(update_fields=["image_url"])

            # --- Step 4: Create SkinImage rows ---
            SkinImage.objects.create(skin=skin, kind="svg", file=f"skins/{skin.id}.svg")
            SkinImage.objects.create(skin=skin, kind="png", file=f"skins/{skin.id}.png")
            SkinImage.objects.create(skin=skin, kind="thumbnail", file=f"skins/{skin.id}_thumb.png")

        except Exception as e:
            # If SVG fetch fails, we still keep the preview URL (no crash)
            print(f"SVG fetch/convert failed: {e}")

        messages.success(request, "✅ Skin uploaded successfully!")
        return redirect(reverse("search_skins") + f"?q={skin_name}")

    return render(request, "skins/upload.html")
