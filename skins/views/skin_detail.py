from django.shortcuts import render, get_object_or_404
from core.ratelimits import limit
from skins.models import Skin
from skins.selectors import vote_state
from django.conf import settings


@limit("browse")
def skin_detail(request, skin_id):
    skin = get_object_or_404(Skin, id=skin_id)

    # The page's own address without any query string: what Copy link copies
    # and what link previews point at.
    page_url = request.build_absolute_uri(skin.get_absolute_url())
    editor_url = f"{settings.BONKVERSE_EDITOR_URL}?skin={skin.skin_code}"
    png_path = f"{settings.MEDIA_URL}skins/{skin.id}.png"
    image_url = request.build_absolute_uri(png_path)

    # Descriptions and tags stay behind the scenes (search and moderation),
    # so link previews say the same thing the page does.
    name_and_creator = f"{skin.name} by {skin.creator}" if skin.creator else skin.name
    desc = f"{name_and_creator} on Bonkverse."[:200]

    og = {
        "title": f"{name_and_creator} · Bonkverse",
        "description": desc,
        "url": page_url,
        "image": image_url,
        "site_name": "Bonkverse",
    }

    share_url = page_url

    # ── Pre-compute favorite state + count in the view ────────────
    #
    # skin_detail.html previously called skin.favorited_by.all twice and
    # skin.favorited_by.count once — 3 separate queries for one page.
    # We do it here in 2 queries and pass the results as plain variables.

    fav_count = skin.favorited_by.count()  # 1 query: COUNT(*)
    is_favorited = False

    if request.user.is_authenticated:
        # .exists() → SELECT 1 LIMIT 1, not a full fetch
        is_favorited = skin.favorited_by.filter(pk=request.user.pk).exists()

    return render(
        request,
        "skins/skin_detail.html",
        {
            "skin": skin,
            "og": og,
            "editor_url": editor_url,
            "share_url": share_url,
            "fav_count": fav_count,
            "is_favorited": is_favorited,
            # The person's vote (one per group) and why they can't vote, if so.
            "vote": vote_state(request.user, skin),
        },
    )
