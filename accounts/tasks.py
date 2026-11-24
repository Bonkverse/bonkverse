"""Celery tasks for accounts (standards: docs/architecture/background-work.md).

check_link_claims: every 30 s (CELERY_BEAT_SCHEDULE). Friend-request linking
(link_claims.py): one query when nothing is pending; otherwise one read of
the bot account's friend requests for every pending claim.
"""

import logging

from celery import shared_task

from . import link_claims

logger = logging.getLogger(__name__)


# Safe to repeat or skip: a missed run only means the next one finds the
# request 30 s later. Short limits so a slow bonk.io can't pile runs up.
@shared_task(soft_time_limit=20, time_limit=25)
def check_link_claims() -> dict:
    return link_claims.check_pending()
