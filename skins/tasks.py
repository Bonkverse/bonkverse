"""Celery tasks.

refresh_discord_servers: hourly (django-celery-beat, "next refresh" on the
server list assumes an hour) member and online counts for every active
Discord server, with a snapshot row per server per run.
"""

import logging
import time

from celery import shared_task
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


# No autoretry: per-server failures are handled below, and retrying the whole
# batch would write a second snapshot for every server already refreshed.
# The next hourly run is the retry.
@shared_task
def refresh_discord_servers() -> dict:
    stats = {"refreshed": 0, "not_found": 0, "failed": 0, "stopped_rate_limited": False}
    servers = DiscordServer.objects.filter(status=DiscordServer.Status.ACTIVE).order_by("id")

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

    logger.info("discord refresh done: %s", stats)
    return stats


def _save_counts(server: DiscordServer, member_count: int, online_count: int) -> None:
    server.member_count = member_count
    server.online_count = online_count
    server.last_fetched_at = timezone.now()
    server.save(update_fields=["member_count", "online_count", "last_fetched_at"])
    DiscordServerSnapshot.objects.create(
        server=server, member_count=member_count, online_count=online_count
    )
