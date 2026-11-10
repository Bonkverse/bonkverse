"""Celery tasks for the players app (standards: docs/architecture/background-work.md).

sync_replays: hourly (CELERY_BEAT_SCHEDULE, REPLAY_SYNC_INTERVAL_SECONDS)
names in and DBIDs out between Bonkverse and the replay archive
(players/replay_sync.py).
"""

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from . import replay_sync

logger = logging.getLogger(__name__)


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
