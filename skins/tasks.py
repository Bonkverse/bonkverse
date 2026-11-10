"""Celery tasks for the skins app (standards: docs/architecture/background-work.md).

sync_friends: a player's bonk.io friend list, queued at login (skins/login.py).
The Discord refresh lives in communities/tasks.py.
"""

import logging
import time

from celery import shared_task

from integrations.bonk_api import BonkError
from skins.friends_sync import sync_friends_for_link
from skins.models import BonkAccountLink

logger = logging.getLogger(__name__)

# Wait between retries when bonk.io was unreachable: 5 s, then 10 s. The
# profile toast stops waiting after about 12 s, but the list is still saved.
FRIEND_SYNC_RETRY_SECONDS = 5


# At least once (the default): the stored list is computed from what bonk.io
# returns now, so running twice is harmless. Retries only when bonk.io was
# unreachable; never on a refusal (rate_limited, token_rejected), which a
# retry seconds later would only repeat.
@shared_task(bind=True, soft_time_limit=60, time_limit=90, max_retries=2)
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
