# skins/players.py
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from .models import BonkPlayer, Friendship
from .friends_sync import sync_friends_for_player
import requests

@login_required
def players_page(request):
    """Render the search UI page."""
    total_players = BonkPlayer.objects.count()
    return render(request, "skins/players.html", {"total_players": total_players})

@login_required
def search_players_view(request):
    q = (request.GET.get("q") or "").strip()
    qs = BonkPlayer.objects.none()
    if not q:
        qs = BonkPlayer.objects.order_by("-last_seen")[:25]
    elif q.isdigit():
        qs = BonkPlayer.objects.filter(bonk_id=int(q))[:25]
    else:
        qs = BonkPlayer.objects.filter(username__icontains=q)[:25]

    return JsonResponse({
        "results": [
            {
                "bonk_id": p.bonk_id,
                "username": p.username,
                "last_friend_count": p.last_friend_count,
                "last_seen": p.last_seen.isoformat() if getattr(p, "last_seen", None) else None,
            }
            for p in qs
        ]
    })

@login_required
def ego_graph_json(request):
    me_bonk_id = request.session.get("bonk_user_id")
    if not me_bonk_id:
        return JsonResponse({"error": "Not connected to Bonk"}, status=400)
    try:
        me = BonkPlayer.objects.get(bonk_id=me_bonk_id)
    except BonkPlayer.DoesNotExist:
        return JsonResponse({"nodes": [], "edges": []})

    lows  = Friendship.objects.filter(player_low=me).values_list("player_high_id", flat=True)
    highs = Friendship.objects.filter(player_high=me).values_list("player_low_id", flat=True)
    friend_ids = list(lows) + list(highs)

    nodes = [{"id": me.bonk_id, "label": me.username, "me": True}]
    for f in BonkPlayer.objects.filter(id__in=friend_ids).only("bonk_id", "username"):
        nodes.append({"id": f.bonk_id, "label": f.username})

    edges = [{"from": me.bonk_id, "to": BonkPlayer.objects.get(id=pk).bonk_id} for pk in friend_ids]
    return JsonResponse({"nodes": nodes, "edges": edges})

@require_POST
@login_required
def resync_friends_view(request):
    token = request.session.get("bonk_token")
    me_bonk_id = request.session.get("bonk_user_id")
    me_name    = request.session.get("bonk_username")
    if not token or not me_bonk_id:
        return JsonResponse({"ok": False, "error": "Not connected"}, status=400)

    r = requests.post(
        "https://bonk2.io/scripts/friends.php",
        data={"token": token, "task": "getfriends"},
        timeout=12,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("r") != "success":
        return JsonResponse({"ok": False, "error": data}, status=400)

    stats = sync_friends_for_player(me_bonk_id, me_name, data)
    return JsonResponse({"ok": True, "stats": stats})
