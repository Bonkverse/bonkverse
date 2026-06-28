# skins/auth_guards.py
# One auth contract for all JSON API endpoints. Returns machine-readable 401s
# the editor branches on: auth="bonkverse" → site sign-in, auth="bonk" → bonk token.
import time
from functools import wraps
from django.http import JsonResponse


def api_login_required(view):
    """JSON 401 instead of a redirect when the Bonkverse session is missing."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"ok": False, "auth": "bonkverse"}, status=401)
        return view(request, *args, **kwargs)
    return wrapped


def bonk_token_required(view):
    """Requires Bonkverse session AND a live bonk.io token (for wear-type calls)."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"ok": False, "auth": "bonkverse"}, status=401)
        tok = request.session.get("bonk_token")
        exp = request.session.get("bonk_token_expires", 0)
        if not tok or time.time() >= exp:
            return JsonResponse({"ok": False, "auth": "bonk"}, status=401)
        return view(request, *args, **kwargs)
    return wrapped