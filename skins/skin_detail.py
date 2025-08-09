# skins/views.py
from django.shortcuts import render, get_object_or_404
from .models import Skin

# skins/skin_detail.py
from django.shortcuts import render, get_object_or_404
from .models import Skin

def skin_detail(request, skin_id):
    skin = get_object_or_404(Skin, id=skin_id)

    page_url = request.build_absolute_uri()  # absolute URL to this skin page

    # Use the stored image URL (already absolute if it’s bonkleagues). If you ever
    # serve local images, make it absolute:
    image_url = skin.image_url
    if image_url and not image_url.startswith('http'):
        image_url = request.build_absolute_uri(image_url)

    # Nice description (fallbacks if none)
    desc = (skin.description or f"{skin.name} by {skin.creator} on Bonkverse.")
    desc = desc.strip()[:200]  # keep it short for cards

    og = {
        "title": f"{skin.name} by {skin.creator} — Bonkverse",
        "description": desc,
        "url": page_url,
        "image": image_url,
        "site_name": "Bonkverse",
    }

    return render(request, "skins/skin_detail.html", {"skin": skin, "og": og})
