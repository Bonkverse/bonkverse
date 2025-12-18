# skins/win_leaderboards.py
from django.shortcuts import render
from django.db.models import Count
from django.utils.timezone import now, timedelta
from .models import PlayerWin

from django.utils import timezone
from datetime import timedelta
from django_ratelimit.decorators import ratelimit

def _get_queryset(period):
    qs = PlayerWin.objects.all()
    now_utc = timezone.now()

    if period == "today":
        start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        qs = qs.filter(created_at__gte=start, created_at__lt=end)

    elif period == "week":
        # Start of the current week (Monday)
        week_start = now_utc - timedelta(days=now_utc.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

        # End of the current week (next Monday)
        week_end = week_start + timedelta(days=7)

        qs = qs.filter(created_at__gte=week_start, created_at__lt=week_end)

    elif period == "month":
        start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        qs = qs.filter(created_at__gte=start, created_at__lt=end)

    return (
        qs.values("username")
          .annotate(total=Count("id"))
          .order_by("-total")[:50]
    )


def wins_hub(request, period="today"):
    leaderboard = _get_queryset(period)
    title_map = {
        "today": "Daily Wins Leaderboard",
        "week": "Weekly Wins Leaderboard",
        "month": "Monthly Wins Leaderboard",
        "all": "All-Time Wins Leaderboard",
    }
    return render(request, "skins/wins_hub.html", {
        "leaderboard": leaderboard,
        "period": period,
        "title": title_map.get(period, "Wins Leaderboard"),
    })
