# skins/flash_friends_sync.py

from typing import Dict, Any
from django.db import transaction
from .models import FlashFriend, FlashFriendship, BonkUser


@transaction.atomic
def sync_flash_friends_for_user(*, user: BonkUser, friends_json: Dict[str, Any]) -> dict:
    """
    Parse the `legacyFriends` field (string of names separated by '#')
    and upsert FlashFriend + FlashFriendship rows.
    """
    raw = friends_json.get("legacyFriends") or ""
    names = [n.strip() for n in raw.split("#") if n.strip()]
    added = 0
    skipped = 0

    for name in names:
        flash_friend, _ = FlashFriend.objects.get_or_create(name=name)
        _, created = FlashFriendship.objects.get_or_create(user=user, flash_friend=flash_friend)
        if created:
            added += 1
        else:
            skipped += 1

    return {"flash_added": added, "flash_skipped": skipped, "flash_total": len(names)}
