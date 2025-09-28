# skins/win_leaderboards.py
from django.shortcuts import render
from django.db.models import Count
from django.utils.timezone import now, timedelta
from .models import PlayerWin

def _get_queryset(period):
    qs = PlayerWin.objects.all()
    now_ts = now()

    if period == "today":
        qs = qs.filter(created_at__date=now_ts.date())
    elif period == "week":
        week_start = now_ts - timedelta(days=now_ts.weekday())
        qs = qs.filter(created_at__gte=week_start)
    elif period == "month":
        qs = qs.filter(created_at__year=now_ts.year, created_at__month=now_ts.month)

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
