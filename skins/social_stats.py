# skins/social_stats.py

import math
from django.shortcuts import render
from django.db.models import Count
from django_ratelimit.decorators import ratelimit
from django.db import connection

from .models import BonkPlayer, Friendship, FlashFriend
from .dbid_lookup import estimate_registration_date, format_registration


@ratelimit(key="ip", rate="20/m", block=True)
def social_stats(request):

    # ── Headline numbers ──────────────────────────────────────────
    total_players  = BonkPlayer.objects.filter(bonk_id__gt=0).count()
    total_edges    = Friendship.objects.count()
    total_flash    = FlashFriend.objects.count()
    synced_players = BonkPlayer.objects.filter(last_friend_count__gt=0).count()

    possible_edges = (total_players * (total_players - 1)) // 2
    density_pct    = (
        round(total_edges * 100.0 / possible_edges, 6)
        if possible_edges > 0 else 0
    )

    # ── Most connected players (with estimated reg date) ─────────
    most_connected_qs = list(
        BonkPlayer.objects
        .filter(bonk_id__gt=0)
        .order_by("-last_friend_count")
        .values("username", "bonk_id", "last_friend_count", "last_seen")[:20]
    )
    for p in most_connected_qs:
        p["est_date"] = format_registration(p["bonk_id"])

    # ── Oldest accounts (with estimated reg date) ─────────────────
    oldest_qs = list(
        BonkPlayer.objects
        .filter(bonk_id__gt=0)
        .order_by("bonk_id")
        .values("username", "bonk_id", "last_friend_count")[:20]
    )
    for p in oldest_qs:
        p["est_date"] = format_registration(p["bonk_id"], fmt="%b %Y")

    # ── Year-by-year registration breakdown ───────────────────────
    all_ids = list(
        BonkPlayer.objects
        .filter(bonk_id__gt=0)
        .values_list("bonk_id", flat=True)
    )

    year_counts: dict[int, int] = {}
    for bid in all_ids:
        d = estimate_registration_date(bid)
        if d:
            year_counts[d.year] = year_counts.get(d.year, 0) + 1

    year_distribution = [
        {"year": year, "player_count": count}
        for year, count in sorted(year_counts.items())
    ]
    year_max = max((r["player_count"] for r in year_distribution), default=1)

    # ── Friend count distribution ─────────────────────────────────
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                CASE
                    WHEN last_friend_count = 0   THEN '0 (no friends)'
                    WHEN last_friend_count < 5   THEN '1–4'
                    WHEN last_friend_count < 10  THEN '5–9'
                    WHEN last_friend_count < 50  THEN '10–49'
                    WHEN last_friend_count < 100 THEN '50–99'
                    WHEN last_friend_count < 250 THEN '100–249'
                    WHEN last_friend_count < 500 THEN '250–499'
                    WHEN last_friend_count < 700 THEN '500–699'
                    WHEN last_friend_count < 1000 THEN '700–999'
                    ELSE '1000+'
                END AS bracket,
                COUNT(*) AS player_count
            FROM skins_bonkplayer
            GROUP BY bracket
            ORDER BY MIN(last_friend_count)
        """)
        dist_rows = cursor.fetchall()

    # Log-scale bar widths — prevents the massive "0 friends" bucket from
    # making every other bar invisible when using a linear scale.
    max_count = max((row[1] for row in dist_rows), default=1)
    max_log   = math.log10(max_count + 1)

    friend_distribution = [
        {
            "bracket":      row[0],
            "player_count": row[1],
            "bar_width":    round(math.log10(row[1] + 1) / max_log * 100, 1),
        }
        for row in dist_rows
    ]

    # ── Most popular flash friend names ───────────────────────────
    top_flash = list(
        FlashFriend.objects
        .annotate(times_listed=Count("friend_of"))
        .filter(times_listed__gt=1)
        .order_by("-times_listed")
        .values("name", "times_listed")[:15]
    )

    # ── Biggest single-session friend gains ───────────────────────
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                p.username,
                p.bonk_id,
                fch.captured_at,
                fch.count,
                fch.count - LAG(fch.count)
                    OVER (PARTITION BY fch.player_id ORDER BY fch.captured_at) AS gained
            FROM skins_friendcounthistory fch
            JOIN skins_bonkplayer p ON p.id = fch.player_id
            ORDER BY gained DESC NULLS LAST
            LIMIT 10
        """)
        gain_rows = cursor.fetchall()

    biggest_gains = [
        {
            "username":    row[0],
            "bonk_id":     row[1],
            "captured_at": row[2],
            "count":       row[3],
            "gained":      row[4],
            "est_date":    format_registration(row[1]),
        }
        for row in gain_rows
        if row[4] is not None
    ]

    return render(request, "skins/social_stats.html", {
        "total_players":       total_players,
        "total_edges":         total_edges,
        "total_flash":         total_flash,
        "synced_players":      synced_players,
        "density_pct":         density_pct,
        "possible_edges":      possible_edges,

        "most_connected":      most_connected_qs,
        "oldest_accounts":     oldest_qs,
        "biggest_gains":       biggest_gains,
        "top_flash":           top_flash,

        "year_distribution":   year_distribution,
        "year_max":            year_max,
        "friend_distribution": friend_distribution,
    })