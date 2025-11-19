# skins/players.py
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from .models import BonkPlayer, FlashFriendship, BonkAccountLink
from django.db.models import Q


# @login_required
def players_page(request):
    """Render the search UI page."""
    total_players = BonkPlayer.objects.count()
    return render(request, "players_search/players.html", {"total_players": total_players})


# @login_required
def search_players_view(request):
    q = (request.GET.get("q") or "").strip()
    page = int(request.GET.get("page", 1))
    page_size = 50
    offset = (page - 1) * page_size

    qs = BonkPlayer.objects.none()
    # if not q:
    #     qs = BonkPlayer.objects.order_by("bonk_id")
    # elif q.isdigit():
    #     qs = BonkPlayer.objects.filter(bonk_id=int(q)).order_by("bonk_id")
    # else:
    #     qs = BonkPlayer.objects.filter(username__icontains=q).order_by("bonk_id")

    mode = request.GET.get("mode", "username")

    if not q:
        qs = BonkPlayer.objects.order_by("bonk_id")
    elif mode == "id":
        try:
            qs = BonkPlayer.objects.filter(bonk_id=int(q)).order_by("bonk_id")
        except ValueError:
            qs = BonkPlayer.objects.none()
    else:  # mode == "username"
        qs = BonkPlayer.objects.filter(username__icontains=q).order_by("bonk_id")


    total = qs.count()
    qs = qs[offset:offset + page_size]

    # 🔹 Map BonkPlayer → BonkUser (if linked)
    account_links = dict(
        BonkAccountLink.objects.filter(bonk_player__in=qs)
        .values_list("bonk_player_id", "user_id")
    )

    # 🔹 Count flash friendships for all relevant users
    flash_counts = dict(
        FlashFriendship.objects.filter(user_id__in=account_links.values())
        .values("user_id")
        .annotate(c=Count("id"))
        .values_list("user_id", "c")
    )

    return JsonResponse({
        "results": [
            {
                "bonk_id": p.bonk_id,
                "username": p.username,
                "last_friend_count": p.last_friend_count,
                "last_seen": p.last_seen.isoformat() if getattr(p, "last_seen", None) else None,
                # ✅ Look up the BonkUser via account_links, then flash friend count
                "flash_friend_count": flash_counts.get(account_links.get(p.id), 0),
            }
            for p in qs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    })