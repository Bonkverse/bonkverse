# core/auth_guards.py
# One auth contract for all JSON API endpoints (plus staff_required for staff pages). Returns machine-readable 401s
# the editor branches on: auth="bonkverse" → site sign-in, auth="bonk" → bonk token.
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import Http404, JsonResponse

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


def staff_required(view):
    """Pages for staff only. Signed out: the login page, then back. Signed in
    without staff: a plain 404, so the page's existence isn't advertised."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_staff:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapped
