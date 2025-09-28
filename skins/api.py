# skins/api.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
import json
from .models import PlayerWin

@csrf_exempt
def record_win(request):
    try:
        if request.method == "OPTIONS":
            response = JsonResponse({"status": "ok"})
            response["Access-Control-Allow-Origin"] = "*"
            response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type"
            return response

        if request.method == "POST":
            import json
            data = json.loads(request.body)
            print("DEBUG record_win got:", data)  # 👈 log to terminal

            username = data.get("username")
            if not username:
                return JsonResponse({"error": "Missing username"}, status=400)

            # Save to DB
            from .models import PlayerWin
            win = PlayerWin.objects.create(username=username)

            return JsonResponse({"status": "ok", "id": win.id})

        return JsonResponse({"error": "Invalid method"}, status=405)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)



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
