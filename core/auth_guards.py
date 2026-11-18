# core/auth_guards.py
# One auth contract for all JSON API endpoints. Returns machine-readable 401s
# the editor branches on: auth="bonkverse" → site sign-in, auth="bonk" → bonk token.
import hmac
from functools import wraps

from django.conf import settings

from django.http import JsonResponse

from core.token_crypto import bonk_session


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
        if not bonk_session(request).token:
            return JsonResponse({"ok": False, "auth": "bonk"}, status=401)
        return view(request, *args, **kwargs)

    return wrapped


def bonxbot_authorized(request) -> bool:
    """Whether the request carries BonxBot's shared secret (Authorization: Bearer <token>).

    Always False while BONXBOT_API_TOKEN is unset, so an empty header never passes.
    """
    expected = settings.BONXBOT_API_TOKEN
    given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())
