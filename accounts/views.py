"""The /login/ and /logout/ pages and /api/me/.

Owns: the login, logout and who-am-I views.
Does not own: the sentences shown when a login is turned down
(login_messages.py), trying the bonk.io login and the limit on wrong
passwords (login_attempts.py), what a successful login does (sign_in.py:
site account, account link, Flash friends, queueing the friend sync), or
talking to bonk.io (integrations/bonk_api.py).
"""

from django.contrib import messages
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.token_crypto import bonk_session
from core.ratelimits import limit
from players import selectors as player_selectors

from . import appearance, bot_check
from .forms import LoginForm
from .login_attempts import attempt_login
from .login_messages import login_failure_message
from .sign_in import sign_in


@limit("login", method="POST")
def login_view(request):
    if request.method != "POST":
        return _render_login(request, LoginForm())

    form = LoginForm(request.POST)
    if not form.is_valid():
        return _render_login(request, form)

    remember = form.cleaned_data["remember"]
    attempt = attempt_login(
        request,
        form.cleaned_data["username"],
        form.cleaned_data["password"],
        via="page",
        remember=remember,
    )
    if not attempt.ok:
        retry_after = attempt.retry_after
        messages.error(
            request,
            f"Bonk.io login failed: {login_failure_message(attempt.error, retry_after)}",
        )
        # The page keeps the Login button off until the wait ends, so players
        # don't resubmit into it (6 tries in a minute on 2026-11-09).
        return _render_login(request, form, retry_after=retry_after)

    sign_in(request, attempt.result, remember=remember)
    messages.success(request, "Logged in successfully!")

    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("players:player_profile", request.user.username)


def _render_login(request, form, *, retry_after=None):
    """The login page, with the "not a bot" check when this visitor's next
    try needs it (bot_check.py)."""
    return render(
        request,
        "accounts/login.html",
        {
            "form": form,
            "retry_after": retry_after,
            "turnstile_site_key": bot_check.site_key_if_wanted(request),
        },
    )


@require_POST
@limit("write")
def logout_view(request):
    """POST only (the header's Log out is a form), so another site can't
    sign people out with a link or an <img>."""
    bonk_session(request).clear()
    logout(request)
    messages.success(request, "Logged out!")
    return redirect("site_pages:home")


@limit("browse")
def me(request):
    """Who is signed in, for the skin editor and the shared header on the
    replay and docs sites (401 when nobody is). `avatar` is the absolute URL
    of their worn skin's thumbnail, the picture bonkverse.io's own header
    shows, or null before a skin has been seen."""
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)

    thumbnail = player_selectors.user_skin_avatars(request.user).get("thumbnail")
    return JsonResponse(
        {
            "authenticated": True,
            "user": {
                "id": request.user.id,
                "username": request.user.username,
                "avatar": request.build_absolute_uri(thumbnail) if thumbnail else None,
                "appearance": appearance.for_api(request.user),
            },
            "permissions": {
                "publish_skins": True,
            },
        }
    )
