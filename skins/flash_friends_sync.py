"""Storing a player's Flash-era friends from the bonk.io login reply.

Owns: reading `legacyFriends` (names separated by "#") and the FlashFriend
and FlashFriendship rows for them.
Does not own: the login itself (skins/sign_in.py) or regular bonk.io
friends (friends_sync.py).

Runs inside the login request, so it uses a fixed number of queries however
long the list is (a player can have hundreds of Flash friends).
"""

import logging

from django.db import transaction

from .models import BonkUser, FlashFriend, FlashFriendship

logger = logging.getLogger(__name__)


def read_legacy_friends(raw: str | None) -> tuple[list[str], int]:
    """The names in a `legacyFriends` value, and how many empty segments it had.

    Names are kept exactly as bonk.io sends them, no trimming: a name that is
    only spaces is a real old Bonk name. Only empty segments (between or
    around "#") are dropped; they're parsing artifacts.
    """
    segments = raw.split("#") if raw else []
    names = [segment for segment in segments if segment != ""]
    return names, len(segments) - len(names)


@transaction.atomic
def sync_flash_friends_for_user(*, user: BonkUser, legacy_friends: str | None) -> dict:
    """Link `user` to a FlashFriend row for each name in `legacy_friends`.

    Adds links only; a name missing from a later login keeps its link (the
    Flash-era list doesn't change). A name with an existing FlashFriend row
    reuses the oldest one, resolved to a BonkPlayer or not.

    Returns:
        {"flash_added": new links, "flash_skipped": names already linked,
         "flash_total": names in the list}
    """
    names, dropped_empty = read_legacy_friends(legacy_friends)
    if dropped_empty:
        logger.warning(
            "dropped %s empty legacyFriends segment(s) for user %s", dropped_empty, user.pk
        )
    unique_names = list(dict.fromkeys(names))
    if not unique_names:
        return {"flash_added": 0, "flash_skipped": 0, "flash_total": 0}

    friend_ids = _flash_friend_ids(unique_names)
    linked = set(
        FlashFriendship.objects.filter(
            user=user, flash_friend_id__in=friend_ids.values()
        ).values_list("flash_friend_id", flat=True)
    )
    new_links = [
        FlashFriendship(user=user, flash_friend_id=friend_id)
        for friend_id in friend_ids.values()
        if friend_id not in linked
    ]
    if new_links:
        FlashFriendship.objects.bulk_create(new_links, ignore_conflicts=True)

    added = len(new_links)
    return {"flash_added": added, "flash_skipped": len(names) - added, "flash_total": len(names)}


def _flash_friend_ids(names: list[str]) -> dict[str, int]:
    """{name: FlashFriend id} for each name, creating unresolved rows for new ones.

    Three queries at most: existing rows, the missing ones created
    (ignore_conflicts covers a concurrent login creating the same name), and
    the ids of those.
    """
    ids: dict[str, int] = {}
    for name, friend_id in (
        FlashFriend.objects.filter(name__in=names).order_by("pk").values_list("name", "pk")
    ):
        ids.setdefault(name, friend_id)  # oldest row for a name wins

    missing = [name for name in names if name not in ids]
    if missing:
        FlashFriend.objects.bulk_create(
            [FlashFriend(name=name) for name in missing], ignore_conflicts=True
        )
        for name, friend_id in (
            FlashFriend.objects.filter(name__in=missing).order_by("pk").values_list("name", "pk")
        ):
            ids.setdefault(name, friend_id)
    return ids
