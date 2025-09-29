# skins/api.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
from datetime import timedelta
from django_ratelimit.decorators import ratelimit
import json
from .models import PlayerWin

# Blacklisted map keywords
BLACKLISTED_KEYWORDS = ["xp", "farm"]

def add_cors_headers(response):
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@csrf_exempt
@ratelimit(key="ip", rate="10/m", block=False)  # ⚠️ don't auto-block
def record_win(request):
    try:
        if request.method == "OPTIONS":
            return add_cors_headers(JsonResponse({"success": True}))

        if request.method == "POST":
            # ✅ handle ratelimit manually
            if getattr(request, "limited", False):
                return add_cors_headers(JsonResponse(
                    {"success": False, "reason": "You're being rate limited: Too many wins per minute"}, status=429
                ))

            data = json.loads(request.body)
            print("DEBUG record_win got:", data)

            username = data.get("username")
            map_name = (data.get("map_name") or "").strip()

            if not username:
                return add_cors_headers(JsonResponse(
                    {"success": False, "reason": "Missing username"}, status=400
                ))

            # Reject blacklisted maps
            if any(bad in map_name.lower() for bad in BLACKLISTED_KEYWORDS):
                return add_cors_headers(JsonResponse(
                    {"success": False, "reason": "XP farming maps not allowed"}, status=400
                ))

            # Reject too-fast wins (<5s apart)
            last_win = PlayerWin.objects.filter(username=username).order_by("-created_at").first()
            if last_win and (now() - last_win.created_at).total_seconds() < 5:
                return add_cors_headers(JsonResponse(
                    {"success": False, "reason": "Suspicious win: Won too soon after previous win"}, status=400
                ))

            # Save to DB
            win = PlayerWin.objects.create(username=username)
            return add_cors_headers(JsonResponse(
                {"success": True, "id": win.id}
            ))

        return add_cors_headers(JsonResponse(
            {"success": False, "reason": "Invalid method"}, status=405
        ))

    except Exception as e:
        import traceback
        traceback.print_exc()
        return add_cors_headers(JsonResponse(
            {"success": False, "reason": str(e)}, status=500
        ))

def leaderboard(request, period="all"):
    """Return top players by wins (today, week, month, all)."""
    from django.db.models import Count
    from django.utils.timezone import now, timedelta

    qs = PlayerWin.objects.all()
    now_ts = now()

    if period == "today":
        qs = qs.filter(created_at__date=now_ts.date())
    elif period == "week":
        week_start = now_ts - timedelta(days=now_ts.weekday())
        qs = qs.filter(created_at__gte=week_start)
    elif period == "month":
        qs = qs.filter(created_at__year=now_ts.year, created_at__month=now_ts.month)

    leaderboard_data = (
        qs.values("username")
          .annotate(total=Count("id"))
          .order_by("-total")[:20]
    )

    return JsonResponse(list(leaderboard_data), safe=False)
