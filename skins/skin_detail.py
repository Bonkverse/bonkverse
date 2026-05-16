from django.shortcuts import render, get_object_or_404
from .models import Skin, SkinVote
from django.conf import settings
from django.urls import reverse


def skin_detail(request, skin_id):
    skin = get_object_or_404(Skin, id=skin_id)

    page_url   = request.build_absolute_uri()
    editor_url = f"{settings.BONKVERSE_EDITOR_URL}?skin={skin.skin_code}"
    png_path   = f"{settings.MEDIA_URL}skins/{skin.id}.png"
    image_url  = request.build_absolute_uri(png_path)

    desc = (skin.description or f"{skin.name} by {skin.creator} on Bonkverse.")
    desc = desc.strip()[:200]

    og = {
        "title":       f"{skin.name} by {skin.creator} — Bonkverse",
        "description": desc,
        "url":         page_url,
        "image":       image_url,
        "site_name":   "Bonkverse",
    }

    share_url = request.build_absolute_uri(
        reverse("share_skin", kwargs={"skin_id": skin_id, "uuid": skin.uuid})
    )

    # ── Pre-compute favorite state + count in the view ────────────
    #
    # skin_detail.html previously called skin.favorited_by.all twice and
    # skin.favorited_by.count once — 3 separate queries for one page.
    # We do it here in 2 queries and pass the results as plain variables.

    fav_count    = skin.favorited_by.count()   # 1 query: COUNT(*)
    is_favorited = False
    current_vote = None

    if request.user.is_authenticated:
        # .exists() → SELECT 1 LIMIT 1, not a full fetch
        is_favorited = skin.favorited_by.filter(pk=request.user.pk).exists()

        vote = SkinVote.objects.filter(user=request.user, skin=skin).first()
        current_vote = vote.vote if vote else None

    return render(request, "skins/skin_detail.html", {
        "skin":         skin,
        "og":           og,
        "editor_url":   editor_url,
        "share_url":    share_url,
        "fav_count":    fav_count,
        "is_favorited": is_favorited,
        "current_vote": current_vote,
    })