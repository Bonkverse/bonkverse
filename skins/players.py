# skins/players.py
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import BonkPlayer


@login_required
def players_page(request):
    """Render the search UI page."""
    total_players = BonkPlayer.objects.count()
    return render(request, "skins/players.html", {"total_players": total_players})


@login_required
def search_players_view(request):
    q = (request.GET.get("q") or "").strip()
    page = int(request.GET.get("page", 1))
    page_size = 50
    offset = (page - 1) * page_size

    qs = BonkPlayer.objects.none()
    if not q:
        qs = BonkPlayer.objects.order_by("bonk_id")  # ✅ order by bonk_id
    elif q.isdigit():
        qs = BonkPlayer.objects.filter(bonk_id=int(q)).order_by("bonk_id")
    else:
        qs = BonkPlayer.objects.filter(username__icontains=q).order_by("bonk_id")

    total = qs.count()
    qs = qs[offset:offset + page_size]

    return JsonResponse({
        "results": [
            {
                "bonk_id": p.bonk_id,
                "username": p.username,
                "last_friend_count": p.last_friend_count,
                "last_seen": p.last_seen.isoformat() if getattr(p, "last_seen", None) else None,
            }
            for p in qs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    })
