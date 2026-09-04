# skins/flash_friends_sync.py

from typing import Dict, Any
from django.db import transaction
import logging

from .models import FlashFriend, FlashFriendship, BonkUser

logger = logging.getLogger(__name__)


@transaction.atomic
def sync_flash_friends_for_user(*, user: BonkUser, friends_json: Dict[str, Any]) -> dict:
    """
    Parse the `legacyFriends` field (string of names separated by '#')
    and upsert FlashFriend + FlashFriendship rows.

    Names are preserved exactly as bonk.io sends them — no trimming.
    A segment that is only whitespace is a legitimate historical Bonk
    name and is kept as-is; only genuinely empty segments (an empty
    string between/around '#' delimiters) are dropped, since those are
    parsing artifacts rather than real names.
    """
    raw = friends_json.get("legacyFriends") or ""
    segments = raw.split("#") if raw else []
    names = [n for n in segments if n != ""]
    dropped_empty = len(segments) - len(names)

    added = 0
    skipped = 0

    for name in names:
        flash_friend, _ = FlashFriend.objects.get_or_create(name=name)
        _, created = FlashFriendship.objects.get_or_create(user=user, flash_friend=flash_friend)
        if created:
            added += 1
        else:
            skipped += 1

    if dropped_empty:
        logger.warning(
            "[bonkverse] dropped %s empty legacyFriends segment(s) for user %s",
            dropped_empty, user.username,
        )

    return {"flash_added": added, "flash_skipped": skipped, "flash_total": len(names)}