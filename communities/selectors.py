"""Read queries for the Discord server directory pages.

Owns: which servers the directory lists and how they're filtered and
ordered, the tag list and its filter links, a server's recent snapshots and
their growth chart, and when the next refresh is expected. Does not own:
writes (`services.py`, `tasks.py`).
"""

from datetime import timedelta
from urllib.parse import urlencode

from django.db.models import Q
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from .models import DiscordServer, DiscordTag

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
    return servers.prefetch_related("tags").order_by("-member_count")


def all_tags():
    """Every directory tag, grouped by category."""
    return DiscordTag.objects.all().order_by("category", "name")


def tag_filters(tags, active: list[str], query: str = "") -> list[dict]:
    """A chip per tag: {"name", "on", "href"}, where href is the list with
    that tag switched on or off (the search text kept). Plain links, so the
    filters work without JavaScript."""
    active_set = set(active)
    chips = []
    for tag in tags:
        on = tag.name in active_set
        names = [n for n in active if n != tag.name] if on else [*active, tag.name]
        params = ([("q", query)] if query else []) + [("tag", n) for n in names]
        chips.append({"name": tag.name, "on": on, "href": "?" + urlencode(params)})
    return chips


def minutes_to_refresh(now=None) -> int | None:
    """Whole minutes until the next hourly refresh (0 when it's due), or None
    before the first run."""
    when = next_refresh_at()
    if when is None:
        return None
    seconds = (when - (now or timezone.now())).total_seconds()
    return max(0, int(seconds // 60))


def growth_chart(snapshots, width: int = 640, height: int = 160) -> dict | None:
    """An SVG line of member counts over `snapshots` (oldest first): the
    polyline's points in a width × height box, the lowest and highest count,
    the first and last time, and the change. None with fewer than two."""
    if len(snapshots) < 2:
        return None
    counts = [s.member_count for s in snapshots]
    low, high = min(counts), max(counts)
    spread = (high - low) or 1
    pad = 8  # keep the line off the box's edges
    step = (width - 2 * pad) / (len(counts) - 1)
    points = " ".join(
        f"{pad + i * step:.1f},{pad + (high - c) / spread * (height - 2 * pad):.1f}"
        for i, c in enumerate(counts)
    )
    return {
        "points": points,
        "width": width,
        "height": height,
        "low": low,
        "high": high,
        "first": snapshots[0].recorded_at,
        "last": snapshots[-1].recorded_at,
        "change": counts[-1] - counts[0],
        "change_size": abs(counts[-1] - counts[0]),
    }


def next_refresh_at():
    """When the next hourly refresh is expected, or None before the first run."""
    task = PeriodicTask.objects.filter(task=REFRESH_TASK).first()
    if task and task.last_run_at:
        return task.last_run_at + REFRESH_INTERVAL
    return None


def recent_snapshots(server, limit: int = 30) -> list:
    """The server's last `limit` snapshots, oldest first (for the chart)."""
    return list(server.snapshots.order_by("-recorded_at")[:limit])[::-1]
