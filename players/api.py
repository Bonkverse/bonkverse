"""JSON endpoints about players.

Owns: the player and Flash-friend search APIs used by the player search
pages, and the friend-sync status poll My Profile runs after login.
Does not own: the friend sync itself (players/friends_sync.py) or the
event log it writes to (skins.events).
"""

from datetime import timedelta

from django.db.models import Count
from django.http import JsonResponse
from django.utils import timezone

from core.ratelimits import limit
from skins.models import BonkAccountLink, BonkPlayer, FlashFriend, FlashFriendship, UserEvent


@limit("search")
def search_players_view(request):
    q = (request.GET.get("q") or "").strip()
    try:
        page = int(request.GET.get("page", 1))
        if page < 1:
            page = 1
    except (TypeError, ValueError):
        page = 1

    page_size = 50
    offset = (page - 1) * page_size

    qs = BonkPlayer.objects.none()

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
    qs = qs[offset : offset + page_size]

    # BonkPlayer -> site account (if linked)
    account_links = dict(
        BonkAccountLink.objects.filter(bonk_player__in=qs).values_list("bonk_player_id", "user_id")
    )

    # Flash friend counts for those accounts
    flash_counts = dict(
        FlashFriendship.objects.filter(user_id__in=account_links.values())
        .values("user_id")
        .annotate(c=Count("id"))
        .values_list("user_id", "c")
    )

    return JsonResponse(
        {
            "results": [
                {
                    "bonk_id": p.bonk_id,
                    "username": p.username,
                    "last_friend_count": p.last_friend_count,
                    "last_seen": p.last_seen.isoformat() if getattr(p, "last_seen", None) else None,
                    "flash_friend_count": flash_counts.get(account_links.get(p.id), 0),
                }
                for p in qs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@limit("search")
def search_flash_friends_view(request):
    q = (request.GET.get("q") or "").strip()
    page = int(request.GET.get("page", 1))
    page_size = 50
    offset = (page - 1) * page_size

    qs = FlashFriend.objects.all()
    if q:
        qs = qs.filter(name__icontains=q)

    total = qs.count()
    qs = qs.order_by("name")[offset : offset + page_size]

    return JsonResponse(
        {
            "results": [{"name": f.name, "bonk_player_id": f.bonk_player_id} for f in qs],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


# How recent a "friends_synced" event must be to count as this login's sync.
SYNC_STATUS_WINDOW = timedelta(minutes=2)


@limit("browse")
def friends_sync_status(request):
    """Report whether the background friend sync started at login has finished.

    Returns:
        401 {"ok": false} when signed out; {"status": "pending"} until the sync
        logs its event; then {"status": "done", ...counts}.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False}, status=401)

    event = (
        UserEvent.objects.filter(
            user=request.user,
            event_type="friends_synced",
            created_at__gte=timezone.now() - SYNC_STATUS_WINDOW,
        )
        .order_by("-created_at")
        .first()
    )
    if not event:
        return JsonResponse({"status": "pending"})

    return JsonResponse(
        {
            "status": "done",
            "friends_now": event.metadata.get("friends_now", 0),
            "added_edges": event.metadata.get("added_edges", 0),
            "removed_edges": event.metadata.get("removed_edges", 0),
            "corrected_usernames": event.metadata.get("corrected_usernames", []),
            "corrected_count": event.metadata.get("corrected_count", 0),
        }
    )
