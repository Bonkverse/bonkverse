"""Celery tasks for the players app (standards: docs/architecture/background-work.md).

sync_friends: a player's bonk.io friend list, queued at login through
players.services.queue_friend_sync.
sync_replays: hourly (CELERY_BEAT_SCHEDULE, REPLAY_SYNC_INTERVAL_SECONDS)
names in and DBIDs out between Bonkverse and the replay archive
(players/replay_sync.py).
"""

import logging
import time

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from integrations.bonk_api import BonkError
from skins.models import BonkAccountLink

from . import replay_sync
from .friends_sync import sync_friends_for_link

logger = logging.getLogger(__name__)

SYNC_FRIENDS_TASK = "skins.tasks.sync_friends"


# At least once (the default): each batch saves its cursor, so a repeated or
# cut-off run carries on where the last one stopped. The hard limit is shorter
# than replay_sync's 30-minute lock, so a run never outlives its lock.
@shared_task(soft_time_limit=25 * 60, time_limit=28 * 60)
def sync_replays() -> dict:
    """One replay sync (run() logs what it did); skipped when another is running or it's off."""
    try:
        result = replay_sync.run()
    except SoftTimeLimitExceeded:
        logger.warning("replay sync stopped at its time limit; the next run carries on")
        return {"stopped_time_limit": True}
    if "skipped" in result:
        logger.info("replay sync skipped: %s", result["skipped"])
    return result


# Wait between retries when bonk.io was unreachable: 5 s, then 10 s. The
# profile toast stops waiting after about 12 s, but the list is still saved.
FRIEND_SYNC_RETRY_SECONDS = 5


# At least once (the default): the stored list is computed from what bonk.io
# returns now, so running twice is harmless. Retries only when bonk.io was
# unreachable; never on a refusal (rate_limited, token_rejected), which a
# retry seconds later would only repeat.
# Registered under its old name (from when it lived in skins/), so runs
# queued during a deploy keep working.
@shared_task(name=SYNC_FRIENDS_TASK, bind=True, soft_time_limit=60, time_limit=90, max_retries=2)
def sync_friends(self, account_link_id: int) -> dict:
    """Store the bonk.io friend list of the player on this account link.

    Queued by login with the link's id; the token stays in the database.
    """
    link = (
        BonkAccountLink.objects.select_related("user", "bonk_player")
        .filter(id=account_link_id, active=True)
        .first()
    )
    if link is None:
        logger.info("friends sync skipped: account link %s is gone or inactive", account_link_id)
        return {"skipped": "link_gone"}

    started = time.monotonic()
    outcome = sync_friends_for_link(link)
    if outcome.error == BonkError.UNAVAILABLE and self.request.retries < self.max_retries:
        raise self.retry(countdown=FRIEND_SYNC_RETRY_SECONDS * (self.request.retries + 1))
    if outcome.error:
        return {"error": outcome.error}

    logger.info(
        "friends sync done for bonk_id=%s: %s (%.2fs)",
        link.bonk_player.bonk_id,
        outcome.stats,
        time.monotonic() - started,
    )
    return outcome.stats
