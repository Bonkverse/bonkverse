"""The players app's public write operations, for its own views and other apps.

Owns: who sees what on a profile, and the entry points other apps use to
store friends (the Flash-friend list from a login reply, adopting names the
replay archive knew, and queueing the regular friend sync on the worker) and
to record the skin a player wears (worn_skins.py).
"""

from __future__ import annotations

from core.background import enqueue

from .flash_friends_sync import sync_flash_friends_for_user
from .friends_sync import adopt_replay_names
from .models import ProfileVisibility, WornSkinSource
from .tasks import sync_friends
from .worn_skins import record_worn_skin

__all__ = [
    "adopt_replay_names",
    "WornSkinSource",
    "queue_friend_sync",
    "record_worn_skin",
    "sync_flash_friends_for_user",
    "update_visibility",
]


def update_visibility(user, shown: dict[str, bool]) -> ProfileVisibility:
    """Save the user's switches. Sections missing from `shown` become hidden,
    which is how an unticked checkbox arrives from a form."""
    values = {field: bool(shown.get(field)) for field, _, _ in ProfileVisibility.SECTIONS}
    visibility, _ = ProfileVisibility.objects.update_or_create(user=user, defaults=values)
    return visibility


def queue_friend_sync(account_link_id: int) -> bool:
    """Queue the regular friend sync (friends.php) for this account link on the
    worker. Returns whether it was queued (enqueue never raises)."""
    return enqueue(sync_friends, account_link_id)
