from django.shortcuts import render
from django.db.models import Count
from skins.models import Skin

def most_upvoted_skins(request):
    skins = Skin.objects.order_by("-upvotes")[:50]
    return render(request, "leaderboards/leaderboards_upvoted.html", {"skins": skins})

def most_downvoted_skins(request):
    skins = Skin.objects.order_by("-downvotes")[:50]
    return render(request, "leaderboards/leaderboards_downvoted.html", {"skins": skins})

def most_favorited_skins(request):
    skins = (
        Skin.objects.annotate(favorites_count=Count("favorited_by"))
        .order_by("-favorites_count")[:50]
    )
    return render(request, "leaderboards/leaderboards_favorited.html", {"skins": skins})
