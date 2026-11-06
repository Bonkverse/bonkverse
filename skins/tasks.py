"""Celery tasks for the skins app (standards: docs/architecture/background-work.md).

refresh_discord_servers: hourly (CELERY_BEAT_SCHEDULE; "next refresh" on the
server list assumes an hour) member and online counts for every active
Discord server, with a snapshot row per server per run.
"""

import logging
import time

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db.models import F
from django.utils import timezone

from integrations.discord_api import InviteError, fetch_invite
from skins.models import DiscordServer, DiscordServerSnapshot

logger = logging.getLogger(__name__)

# One lookup per second. These calls are unauthenticated, so they share
# Discord's per-IP limits with everything else on the box; the old 40/s
# was far past what Discord tolerates.
SECONDS_BETWEEN_LOOKUPS = 1.0
# Longest a 429 may pause the batch before we give up on this run.
MAX_RATE_LIMIT_WAIT = 60.0


# Runs at most once per schedule: no autoretry (per-server failures are handled
# below) and acks_late=False, so a run cut off by a deploy isn't repeated.
# Repeating would write a second snapshot for every server already refreshed;
# the next hourly run is the retry. The limits stop a run before the next one
# starts; whatever wasn't reached goes first next time (stalest first).
@shared_task(acks_late=False, soft_time_limit=45 * 60, time_limit=50 * 60)
def refresh_discord_servers() -> dict:
    stats = {
        "refreshed": 0,
        "not_found": 0,
        "failed": 0,
        "stopped_rate_limited": False,
        "stopped_time_limit": False,
    }
    # Stalest first, so a run cut short by a rate limit doesn't keep skipping
    # the same servers.
    servers = DiscordServer.objects.filter(status=DiscordServer.Status.ACTIVE).order_by(
        F("last_fetched_at").asc(nulls_first=True), "id"
    )

    try:
        _refresh_each(servers, stats)
    except SoftTimeLimitExceeded:
        stats["stopped_time_limit"] = True
        logger.warning("discord refresh stopped at its time limit: %s", stats)

    logger.info("discord refresh done: %s", stats)
    return stats


def _refresh_each(servers, stats: dict) -> None:
    for server in servers.iterator():
        result = fetch_invite(server.invite_code)
        if result.error == InviteError.RATE_LIMITED:
            wait = min(result.retry_after or 5.0, MAX_RATE_LIMIT_WAIT)
            time.sleep(wait)
            result = fetch_invite(server.invite_code)
            if result.error == InviteError.RATE_LIMITED:
                # Still limited: keep going would only extend the ban.
                logger.warning("discord refresh stopped: rate limited at server id=%s", server.id)
                stats["stopped_rate_limited"] = True
                break

        if result.error == InviteError.NOT_FOUND:
            stats["not_found"] += 1
            logger.info("discord refresh: invite gone for server id=%s", server.id)
        elif result.error:
            stats["failed"] += 1
            logger.warning("discord refresh failed for server id=%s: %s", server.id, result.error)
        else:
            _save_counts(server, result.invite.member_count, result.invite.online_count)
            stats["refreshed"] += 1

        time.sleep(SECONDS_BETWEEN_LOOKUPS)


def _save_counts(server: DiscordServer, member_count: int, online_count: int) -> None:
    server.member_count = member_count
    server.online_count = online_count
    server.last_fetched_at = timezone.now()
    server.save(update_fields=["member_count", "online_count", "last_fetched_at"])
    DiscordServerSnapshot.objects.create(
        server=server, member_count=member_count, online_count=online_count
    )
