"""Read queries for the Discord server directory pages.

Owns: which servers the directory lists and how they're filtered and
ordered, the tag list, a server's recent snapshots, and when the next
refresh is expected. Does not own: writes (`services.py`, `tasks.py`).
"""

from datetime import timedelta

from django.db.models import Q
from django_celery_beat.models import PeriodicTask

from skins.models import DiscordServer, DiscordTag

# The refresh task's registered name (kept from when it lived in skins/, so
# saved schedules and queued runs keep working).
REFRESH_TASK = "skins.tasks.refresh_discord_servers"

# How often the refresh runs (CELERY_BEAT_SCHEDULE "refresh-discord-servers").
REFRESH_INTERVAL = timedelta(hours=1)


def listed_servers(query: str = "", tag_names: list[str] | None = None):
    """Active servers, biggest first, filtered by text in the name or
    description and by any of the given tag names."""
    servers = DiscordServer.objects.filter(status="active")
    if query:
        servers = servers.filter(Q(name__icontains=query) | Q(description__icontains=query))
    if tag_names:
        servers = servers.filter(tags__name__in=tag_names).distinct()
    return servers.order_by("-member_count")


def all_tags():
    """Every directory tag, grouped by category."""
    return DiscordTag.objects.all().order_by("category", "name")


def next_refresh_at():
    """When the next hourly refresh is expected, or None before the first run."""
    task = PeriodicTask.objects.filter(task=REFRESH_TASK).first()
    if task and task.last_run_at:
        return task.last_run_at + REFRESH_INTERVAL
    return None


def recent_snapshots(server, limit: int = 30) -> list:
    """The server's last `limit` snapshots, oldest first (for the chart)."""
    return list(server.snapshots.order_by("-recorded_at")[:limit])[::-1]
