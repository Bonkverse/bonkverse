# skins/win_leaderboards.py
from django.shortcuts import render
from django.db.models import Count
from django.utils.timezone import now, timedelta
from .models import PlayerWin

from django.utils import timezone
from datetime import timedelta

def _get_queryset(period):
    qs = PlayerWin.objects.all()
    now_utc = timezone.now()

    if period == "today":
        start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        qs = qs.filter(created_at__gte=start, created_at__lt=end)

    elif period == "week":
        week_start = now_utc - timedelta(days=now_utc.weekday())
        qs = qs.filter(created_at__gte=week_start)

    elif period == "month":
        qs = qs.filter(created_at__year=now_utc.year, created_at__month=now_utc.month)

    return (
        qs.values("username")
          .annotate(total=Count("id"))
          .order_by("-total")[:20]
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
