# views/search.py
from core.ratelimits import limit
from django.shortcuts import render

from skins.models import Skin


@limit("browse")
def home(request):
    # ⚠️ Adjust these to match your model fields
    recent = Skin.objects.order_by("-created_at")[:24]

    # Most favorited
    top_favs = Skin.objects.with_favorite_count().order_by("-fav_count", "-upvotes")[:24]

    # “Trending” = upvotes - downvotes (simple, fast)
    trending = Skin.objects.with_score().order_by("-score", "-created_at")[:24]

    # A light random strip (OK at small size)
    random_strip = Skin.objects.order_by("?")[:24]

    ctx = {
        "recent": recent,
        "top_favs": top_favs,
        "trending": trending,
        "random_strip": random_strip,
    }
    return render(request, "skins/home.html", ctx)
