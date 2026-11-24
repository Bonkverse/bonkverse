"""The players app's public write operations, for its own views and other apps.

Owns: who sees what on a profile, and the entry points other apps use to
store friends (the Flash-friend list from a login reply, adopting names the
replay archive knew, and queueing the regular friend sync on the worker) and
to record the skin a player wears (worn_skins.py).
"""

from __future__ import annotations

from django.core.cache import cache

from core.background import enqueue

from .flash_friends_sync import sync_flash_friends_for_user
from .friends_sync import adopt_replay_names
from .models import ProfileVisibility, WornSkinSource
from .tasks import sync_friends, sync_login_friends
from .worn_skins import record_replay_skins, record_worn_skin

__all__ = [
    "adopt_replay_names",
    "WornSkinSource",
    "forget_user_skin",
    "queue_friend_sync",
    "queue_login_friends",
    "record_replay_skins",
    "record_worn_skin",
    "sync_flash_friends_for_user",
    "update_visibility",
]


def copy_visibility_to(user, account_ids) -> int:
    """Give every account in `account_ids` the same profile switches as
    `user` ("Apply to all my accounts", RFC-0003 phase 5). The caller checks
    they're the user's own accounts.

    Returns:
        How many other accounts were changed.
    """
    saved = ProfileVisibility.objects.filter(user=user).first() or ProfileVisibility(user=user)
    values = saved.as_dict()
    changed = 0
    for account_id in account_ids:
        if account_id == user.pk:
            continue
        ProfileVisibility.objects.update_or_create(user_id=account_id, defaults=values)
        changed += 1
    return changed


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


def queue_login_friends(account_link_id: int, friends, requests=None) -> bool:
    """Queue storing the friend list a login answer carried (no bonk.io call).

    `friends` and `requests` are BonkFriends; `requests` None when the answer
    had none. Returns whether it was queued (enqueue never raises).
    """

    def as_json(entries):
        return [[friend.bonk_id, friend.name] for friend in entries]

    return enqueue(
        sync_login_friends,
        account_link_id,
        as_json(friends),
        as_json(requests) if requests is not None else None,
    )


def forget_user_skin(user) -> None:
    """Drop the cached site-header avatar (selectors.user_skin_avatars) for
    `user`, after their worn skin may have changed. Never raises."""
    try:
        cache.delete(f"players:user_skin:{user.pk}")
    except Exception:
        pass
