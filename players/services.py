"""The players app's public write operations, for its own views and other apps.

Owns: who sees what on a profile, and the entry points other apps use to
store friends (the Flash-friend list from a login reply, adopting names the
replay archive knew, and queueing the regular friend sync on the worker) and
to record the skin a player wears (worn_skins.py), and finding or adding a
player by name (`player_named`).
"""

from __future__ import annotations

from django.core.cache import cache

from core.background import enqueue

from .flash_friends_sync import sync_flash_friends_for_user
from .friends_sync import adopt_replay_names
from .models import BonkPlayer, ProfileVisibility, WornSkinSource
from .tasks import sync_friends
from .worn_skins import record_replay_skins, record_worn_skin

__all__ = [
    "adopt_replay_names",
    "WornSkinSource",
    "forget_user_skin",
    "player_named",
    "queue_friend_sync",
    "record_replay_skins",
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


def forget_user_skin(user) -> None:
    """Drop the cached site-header avatar (selectors.user_skin_avatars) for
    `user`, after their worn skin may have changed. Never raises."""
    try:
        cache.delete(f"players:user_skin:{user.pk}")
    except Exception:
        pass


def player_named(username: str) -> BonkPlayer:
    """The player called `username`, added by name only if Bonkverse hasn't seen them.

    Matched ignoring case but not spaces, like bonk.io names (ADR 0007); the
    oldest row wins if several match. A new row has no bonk.io id yet, the same
    as names first seen in replays; the friend sync fills the id in later.
    """
    player = BonkPlayer.objects.filter(username__iexact=username).order_by("pk").first()
    return player or BonkPlayer.objects.create(bonk_id=None, username=username)
