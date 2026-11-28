"""Celery tasks for accounts (standards: docs/architecture/background-work.md).

end_other_sessions: once, when the owner's proof takes an account back
from a weaker one (sign_in._reclaim, ADR 0024, 0026).
"""

import logging

from celery import shared_task

from . import sessions

logger = logging.getLogger(__name__)


# Safe to repeat: a second run finds nothing more to end.
@shared_task(soft_time_limit=60, time_limit=90)
def end_other_sessions(user_id: int, keep_key: str | None) -> int:
    ended = sessions.end_other_sessions(user_id, keep_key)
    logger.info("reclaim | ended other sessions | user=%s | sessions=%s", user_id, ended)
    return ended
