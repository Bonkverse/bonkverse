"""JSON endpoints that don't belong to a bigger feature module.

Owns: the friend-sync status poll used by My Profile after login.
Does not own: the friend sync itself (skins/friends_sync.py).

The win/loss userscript API (wins, losses, heartbeat, stop_tracking,
verification, leaderboard JSON) was retired in RFC-0001 Phase 1.
"""

from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone

from core.ratelimits import limit

from .models import UserEvent

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
