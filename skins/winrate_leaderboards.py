# skins/winrate_leaderboards.py
from django.shortcuts import render
from django.db.models import Count, F, Q, FloatField, IntegerField
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone
from datetime import timedelta
from .models import PlayerWin, PlayerLoss
from django_ratelimit.decorators import ratelimit

@ratelimit(key="ip", rate="10/m", block=True)
def _get_queryset(period):
    now_utc = timezone.now()

    # Time filtering
    win_qs = PlayerWin.objects.all()
    loss_qs = PlayerLoss.objects.all()

    if period == "today":
        start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        win_qs = win_qs.filter(created_at__gte=start, created_at__lt=end)
        loss_qs = loss_qs.filter(created_at__gte=start, created_at__lt=end)

    elif period == "week":
        week_start = now_utc - timedelta(days=now_utc.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = week_start + timedelta(days=7)
        win_qs = win_qs.filter(created_at__gte=week_start, created_at__lt=week_end)
        loss_qs = loss_qs.filter(created_at__gte=week_start, created_at__lt=week_end)

    elif period == "month":
        start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        win_qs = win_qs.filter(created_at__gte=start, created_at__lt=end)
        loss_qs = loss_qs.filter(created_at__gte=start, created_at__lt=end)

    # Aggregate wins and losses separately
    win_counts = win_qs.values("username").annotate(wins=Count("id"))
    loss_counts = loss_qs.values("username").annotate(losses=Count("id"))

    # Merge usernames from both win + loss sets
    usernames = set([w["username"] for w in win_counts] + [l["username"] for l in loss_counts])

    leaderboard = []
    for username in usernames:
        wins = next((w["wins"] for w in win_counts if w["username"] == username), 0)
        losses = next((l["losses"] for l in loss_counts if l["username"] == username), 0)
        total = wins + losses
        winrate = (wins / total) * 100 if total > 0 else 0
        leaderboard.append({
            "username": username,
            "wins": wins,
            "losses": losses,
            "total": total,
            "winrate": round(winrate, 2),
        })

    # Sort by winrate, then by total games played
    leaderboard = sorted(leaderboard, key=lambda x: (x["winrate"], x["total"]), reverse=True)

    return leaderboard[:50]

@ratelimit(key="ip", rate="10/m", block=True)
def winrate_hub(request, period="today"):
    leaderboard = _get_queryset(period)
    title_map = {
        "today": "Daily Winrate Leaderboard",
        "week": "Weekly Winrate Leaderboard",
        "month": "Monthly Winrate Leaderboard",
        "all": "All-Time Winrate Leaderboard",
    }
    return render(request, "skins/winrate_hub.html", {
        "leaderboard": leaderboard,
        "period": period,
        "title": title_map.get(period, "Winrate Leaderboard"),
    })
