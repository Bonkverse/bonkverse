from django.shortcuts import render
from core.ratelimits import limit
from skins.models import Skin


@limit("browse")
def most_upvoted_skins(request):
    skins = Skin.objects.order_by("-upvotes")[:50]
    return render(request, "leaderboards/leaderboards_upvoted.html", {"skins": skins})


@limit("browse")
def most_downvoted_skins(request):
    skins = Skin.objects.order_by("-downvotes")[:50]
    return render(request, "leaderboards/leaderboards_downvoted.html", {"skins": skins})


@limit("browse")
def most_favorited_skins(request):
    skins = Skin.objects.with_favorite_count().order_by("-fav_count")[:50]
    return render(request, "leaderboards/leaderboards_favorited.html", {"skins": skins})
