# # skins/api.py
# from django.http import JsonResponse
# from django.views.decorators.csrf import csrf_exempt
# from django.utils.timezone import now
# from datetime import timedelta
# from django_ratelimit.decorators import ratelimit
# import json, secrets

# from .models import PlayerWin, PlayerSession, validate_username
# from django.core.exceptions import ValidationError

# # Blacklisted map keywords
# BLACKLISTED_KEYWORDS = ["xp", "farm"]

# SESSION_DEFAULT_MINUTES = 30  # default lifetime for session tokens




# def add_cors_headers(response):
#     response["Access-Control-Allow-Origin"] = "*"
#     response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
#     response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
#     return response


# @csrf_exempt
# @ratelimit(key="ip", rate="5/m", block=True)   # ✅ add rate limit
# def start_tracking(request):
#     """Create a new session token for a player"""
#     if request.method == "OPTIONS":
#         return add_cors_headers(JsonResponse({"success": True}))

#     if request.method != "POST":
#         return add_cors_headers(JsonResponse(
#             {"success": False, "reason": "Invalid method"}, status=405
#         ))

#     try:
#         data = json.loads(request.body)
#         username = data.get("username")
#         if not username:
#             return add_cors_headers(JsonResponse(
#                 {"success": False, "reason": "Missing username"}, status=400
#             ))

#         # ✅ Run server-side validation
#         try:
#             validate_username(username)
#         except ValidationError as e:
#             return add_cors_headers(JsonResponse(
#                 {"success": False, "reason": str(e)}, status=400
#             ))

#         # Remove any old session for this user
#         PlayerSession.objects.filter(username=username).delete()

#         token = secrets.token_urlsafe(32)
#         PlayerSession.objects.create(
#             username=username,
#             token=token,
#             expires_at=now() + timedelta(minutes=SESSION_DEFAULT_MINUTES),
#         )
#         return add_cors_headers(JsonResponse({
#             "success": True,
#             "token": token,
#             "expires_in": SESSION_DEFAULT_MINUTES * 60,
#         }))
#     except Exception as e:
#         return add_cors_headers(JsonResponse({"success": False, "reason": str(e)}, status=500))


# @csrf_exempt
# @ratelimit(key="ip", rate="30/m", block=True)
# def heartbeat(request):
#     """Keep a session alive"""
#     if request.method == "OPTIONS":
#         return add_cors_headers(JsonResponse({"success": True}))

#     token = request.headers.get("Authorization", "").replace("Bearer ", "")
#     session = PlayerSession.objects.filter(token=token).first()
#     if not session:
#         return add_cors_headers(JsonResponse({"success": False, "reason": "Invalid session"}, status=403))
#     session.last_seen = now()
#     session.save(update_fields=["last_seen"])
#     return add_cors_headers(JsonResponse({"success": True}))


# @csrf_exempt
# @ratelimit(key="ip", rate="20/m", block=True)
# def stop_tracking(request):
#     """End a session"""
#     if request.method == "OPTIONS":
#         return add_cors_headers(JsonResponse({"success": True}))

#     token = request.headers.get("Authorization", "").replace("Bearer ", "")
#     PlayerSession.objects.filter(token=token).delete()
#     return add_cors_headers(JsonResponse({"success": True}))


# @csrf_exempt
# @ratelimit(key="ip", rate="10/m", block=False)
# def record_win(request):
#     try:
#         if request.method == "OPTIONS":
#             return add_cors_headers(JsonResponse({"success": True}))

#         if request.method == "POST":
#             # 🔑 First check session token
#             token = request.headers.get("Authorization", "").replace("Bearer ", "")
#             session = PlayerSession.objects.filter(token=token).first()
#             if not session or not session.is_active():
#                 return add_cors_headers(JsonResponse(
#                     {"success": False, "reason": "Invalid or expired session"}, status=403
#                 ))

#             # ✅ Now enforce ratelimit (only valid sessions hit the limiter)
#             if getattr(request, "limited", False):
#                 return add_cors_headers(JsonResponse(
#                     {"success": False, "reason": "You're being rate limited: Too many wins per minute"}, status=429
#                 ))

#             data = json.loads(request.body)
#             username = data.get("username")
#             map_name = (data.get("map_name") or "").strip()

#             # ✅ Validate username again here for safety
#             try:
#                 validate_username(username)
#             except ValidationError as e:
#                 return add_cors_headers(JsonResponse(
#                     {"success": False, "reason": str(e)}, status=400
#                 ))

#             # ✅ Enforce session-user binding
#             if username != session.username:
#                 return add_cors_headers(JsonResponse(
#                     {"success": False, "reason": "Username mismatch"}, status=403
#                 ))

#             # Reject blacklisted maps
#             if any(bad in map_name.lower() for bad in BLACKLISTED_KEYWORDS):
#                 return add_cors_headers(JsonResponse(
#                     {"success": False, "reason": "XP farming maps not allowed"}, status=400
#                 ))

#             # Reject too-fast wins (<5s apart)
#             last_win = PlayerWin.objects.filter(username=username).order_by("-created_at").first()
#             if last_win and (now() - last_win.created_at).total_seconds() < 5:
#                 return add_cors_headers(JsonResponse(
#                     {"success": False, "reason": "Suspicious win: Won too soon after previous win"}, status=400
#                 ))

#             # Save to DB
#             win = PlayerWin.objects.create(username=username)
#             return add_cors_headers(JsonResponse(
#                 {"success": True, "id": win.id}
#             ))

#         return add_cors_headers(JsonResponse(
#             {"success": False, "reason": "Invalid method"}, status=405
#         ))

#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#         return add_cors_headers(JsonResponse(
#             {"success": False, "reason": str(e)}, status=500
#         ))


# def leaderboard(request, period="all"):
#     """Return top players by wins (today, week, month, all)."""
#     from django.db.models import Count
#     from django.utils.timezone import now, timedelta

#     qs = PlayerWin.objects.all()
#     now_ts = now()

#     if period == "today":
#         qs = qs.filter(created_at__date=now_ts.date())
#     elif period == "week":
#         week_start = now_ts - timedelta(days=now_ts.weekday())
#         qs = qs.filter(created_at__gte=week_start)
#     elif period == "month":
#         qs = qs.filter(created_at__year=now_ts.year, created_at__month=now_ts.month)

#     leaderboard_data = (
#         qs.values("username")
#           .annotate(total=Count("id"))
#           .order_by("-total")[:20]
#     )
#     return JsonResponse(list(leaderboard_data), safe=False)

# skins/api.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
from datetime import timedelta
from django_ratelimit.decorators import ratelimit
import json, secrets, requests

from .models import PlayerWin, PlayerSession, validate_username
from django.core.exceptions import ValidationError

# ==========================
# Config
# ==========================
BLACKLISTED_KEYWORDS = ["xp", "farm"]
SESSION_DEFAULT_MINUTES = 30  # default lifetime for session tokens
BONKBOT_API_BASE = "https://bonkversebonkbotapi-production.up.railway.app"  # 🔑 replace with your Railway URL


# ==========================
# Helpers
# ==========================
def add_cors_headers(response):
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


# ==========================
# Verification Endpoints
# ==========================
@csrf_exempt
def request_verification(request):
    """Ask BonkBot service to create a verification room."""
    if request.method != "POST":
        return add_cors_headers(JsonResponse({"success": False, "reason": "Invalid method"}, status=405))

    try:
        resp = requests.post(f"{BONKBOT_API_BASE}/create_verification", timeout=10)
        data = resp.json()
        if not data.get("success"):
            return add_cors_headers(JsonResponse({"success": False, "reason": "Failed to create room"}, status=500))

        return add_cors_headers(JsonResponse({
            "success": True,
            "verification_id": data["verification_id"],
            "room_url": data["room_url"],
        }))
    except Exception as e:
        return add_cors_headers(JsonResponse({"success": False, "reason": str(e)}, status=500))


@csrf_exempt
def complete_verification(request):
    """Poll BonkBot service for verification result, issue session token if verified."""
    if request.method == "OPTIONS":
        return add_cors_headers(JsonResponse({"success": True}))  # 👈 handle preflight
    
    if request.method != "POST":
        return add_cors_headers(JsonResponse({"success": False, "reason": "Invalid method"}, status=405))

    try:
        body = json.loads(request.body)
        verification_id = body.get("verification_id")
        if not verification_id:
            return add_cors_headers(JsonResponse({"success": False, "reason": "Missing verification_id"}, status=400))

        # Poll BonkBot service
        resp = requests.get(f"{BONKBOT_API_BASE}/status/{verification_id}", timeout=10)
        data = resp.json()
        status = data.get("status")

        if status == "failed":
            return add_cors_headers(JsonResponse({
                "success": False,
                "reason": "Verification failed (guest or invalid)"
            }, status=400))

        if status == "pending":
            return add_cors_headers(JsonResponse({
                "success": False,
                "reason": "Not verified yet"
            }, status=400))

        if status == "expired":
            return add_cors_headers(JsonResponse({
                "success": False,
                "reason": "Verification expired (room closed)"
            }, status=400))

        if status != "verified":
            return add_cors_headers(JsonResponse({
                "success": False,
                "reason": f"Unknown verification state: {status}"
            }, status=400))

        # ✅ At this point, verified
        username = data.get("username")
        try:
            validate_username(username)
        except ValidationError as e:
            return add_cors_headers(JsonResponse({"success": False, "reason": str(e)}, status=400))

        # Remove any old session for this user
        PlayerSession.objects.filter(username=username).delete()

        # Issue session token
        token = secrets.token_urlsafe(32)
        PlayerSession.objects.create(
            username=username,
            token=token,
            expires_at=now() + timedelta(minutes=SESSION_DEFAULT_MINUTES),
        )

        return add_cors_headers(JsonResponse({
            "success": True,
            "username": username,
            "token": token,
            "expires_in": SESSION_DEFAULT_MINUTES * 60,
        }))
    except Exception as e:
        return add_cors_headers(JsonResponse({"success": False, "reason": str(e)}, status=500))



# ==========================
# Session + Wins Endpoints
# ==========================
# @csrf_exempt
# @ratelimit(key="ip", rate="5/m", block=True)
# def start_tracking(request):
#     """(Legacy) Directly start a session without BonkBot verification."""
#     if request.method == "OPTIONS":
#         return add_cors_headers(JsonResponse({"success": True}))
#     if request.method != "POST":
#         return add_cors_headers(JsonResponse({"success": False, "reason": "Invalid method"}, status=405))

#     try:
#         data = json.loads(request.body)
#         username = data.get("username")
#         if not username:
#             return add_cors_headers(JsonResponse({"success": False, "reason": "Missing username"}, status=400))

#         try:
#             validate_username(username)
#         except ValidationError as e:
#             return add_cors_headers(JsonResponse({"success": False, "reason": str(e)}, status=400))

#         PlayerSession.objects.filter(username=username).delete()

#         token = secrets.token_urlsafe(32)
#         PlayerSession.objects.create(
#             username=username,
#             token=token,
#             expires_at=now() + timedelta(minutes=SESSION_DEFAULT_MINUTES),
#         )
#         return add_cors_headers(JsonResponse({
#             "success": True,
#             "token": token,
#             "expires_in": SESSION_DEFAULT_MINUTES * 60,
#         }))
#     except Exception as e:
#         return add_cors_headers(JsonResponse({"success": False, "reason": str(e)}, status=500))


@csrf_exempt
@ratelimit(key="ip", rate="30/m", block=True)
def heartbeat(request):
    """Keep a session alive"""
    if request.method == "OPTIONS":
        return add_cors_headers(JsonResponse({"success": True}))

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    session = PlayerSession.objects.filter(token=token).first()
    if not session:
        return add_cors_headers(JsonResponse({"success": False, "reason": "Invalid session"}, status=403))
    session.last_seen = now()
    session.save(update_fields=["last_seen"])
    return add_cors_headers(JsonResponse({"success": True}))


@csrf_exempt
@ratelimit(key="ip", rate="20/m", block=True)
def stop_tracking(request):
    """End a session"""
    if request.method == "OPTIONS":
        return add_cors_headers(JsonResponse({"success": True}))

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    PlayerSession.objects.filter(token=token).delete()
    return add_cors_headers(JsonResponse({"success": True}))


@csrf_exempt
@ratelimit(key="ip", rate="10/m", block=False)
def record_win(request):
    try:
        if request.method == "OPTIONS":
            return add_cors_headers(JsonResponse({"success": True}))
        if request.method != "POST":
            return add_cors_headers(JsonResponse({"success": False, "reason": "Invalid method"}, status=405))

        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        session = PlayerSession.objects.filter(token=token).first()
        if not session or not session.is_active():
            return add_cors_headers(JsonResponse({"success": False, "reason": "Invalid or expired session"}, status=403))

        if getattr(request, "limited", False):
            return add_cors_headers(JsonResponse(
                {"success": False, "reason": "You're being rate limited: Too many wins per minute"}, status=429
            ))

        data = json.loads(request.body)
        username = data.get("username")
        map_name = (data.get("map_name") or "").strip()

        try:
            validate_username(username)
        except ValidationError as e:
            return add_cors_headers(JsonResponse({"success": False, "reason": str(e)}, status=400))

        if username != session.username:
            return add_cors_headers(JsonResponse({"success": False, "reason": "Username mismatch"}, status=403))

        if any(bad in map_name.lower() for bad in BLACKLISTED_KEYWORDS):
            return add_cors_headers(JsonResponse({"success": False, "reason": "XP farming maps not allowed"}, status=400))

        last_win = PlayerWin.objects.filter(username=username).order_by("-created_at").first()
        if last_win and (now() - last_win.created_at).total_seconds() < 5:
            return add_cors_headers(JsonResponse(
                {"success": False, "reason": "Suspicious win: Won too soon after previous win"}, status=400
            ))

        win = PlayerWin.objects.create(username=username)
        return add_cors_headers(JsonResponse({"success": True, "id": win.id}))

    except Exception as e:
        import traceback
        traceback.print_exc()
        return add_cors_headers(JsonResponse({"success": False, "reason": str(e)}, status=500))


# ==========================
# Leaderboard
# ==========================
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
