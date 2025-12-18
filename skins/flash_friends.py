# skins/flash_friends.py
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import FlashFriend
from django_ratelimit.decorators import ratelimit


# @login_required
@ratelimit(key="ip", rate="10/m", block=True)
def flash_friends_page(request):
    total_flash = FlashFriend.objects.count()
    return render(request, "players_search/flash_friends.html", {"total_flash": total_flash})


# @login_required
@ratelimit(key="ip", rate="10/m", block=True)
def search_flash_friends_view(request):
    q = (request.GET.get("q") or "").strip()
    page = int(request.GET.get("page", 1))
    page_size = 50
    offset = (page - 1) * page_size

    qs = FlashFriend.objects.all()
    if q:
        qs = qs.filter(name__icontains=q)

    total = qs.count()
    qs = qs.order_by("name")[offset:offset + page_size]

    return JsonResponse({
        "results": [{"name": f.name, "bonk_player_id": f.bonk_player_id} for f in qs],
        "total": total,
        "page": page,
        "page_size": page_size,
    })
