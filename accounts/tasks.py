"""Celery tasks for accounts (standards: docs/architecture/background-work.md).

check_link_claims: every 30 s (CELERY_BEAT_SCHEDULE). Friend-request linking
(link_claims.py): one query when nothing is pending; otherwise one read of
the bot account's friend requests for every pending claim.

end_other_sessions: once, when a password reclaims an account someone had
claimed by friend request (sign_in._reclaim, ADR 0024).
"""

import logging

from celery import shared_task

from . import link_claims, sessions

logger = logging.getLogger(__name__)


# Safe to repeat or skip: a missed run only means the next one finds the
# request 30 s later. Short limits so a slow bonk.io can't pile runs up.
@shared_task(soft_time_limit=20, time_limit=25)
def check_link_claims() -> dict:
    return link_claims.check_pending()


# Safe to repeat: a second run finds nothing more to end.
@shared_task(soft_time_limit=60, time_limit=90)
def end_other_sessions(user_id: int, keep_key: str | None) -> int:
    ended = sessions.end_other_sessions(user_id, keep_key)
    logger.info("reclaim | ended other sessions | user=%s | sessions=%s", user_id, ended)
    return ended
