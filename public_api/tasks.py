"""Celery tasks for the public API (standards: docs/architecture/background-work.md).

prune_api_usage: daily (CELERY_BEAT_SCHEDULE), deletes per-key usage older
than the usage page shows (public_api/usage.py, USAGE_DAYS).
"""

import logging

from celery import shared_task

from . import usage

logger = logging.getLogger(__name__)


# One DELETE; safe to repeat, so a run cut off by a deploy can simply run again.
@shared_task(acks_late=True, soft_time_limit=5 * 60, time_limit=6 * 60)
def prune_api_usage() -> dict:
    deleted = usage.prune()
    logger.info("public api: pruned %d usage rows", deleted)
    return {"deleted": deleted}
