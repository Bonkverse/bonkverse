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

from core.bonk import BonkSession
from core.ratelimits import limit

from .forms import LoginForm
from .login_attempts import attempt_login
from .login_messages import login_failure_message
from .sign_in import sign_in


@limit("login", method="POST")
def login_view(request):
    if request.method != "POST":
        return render(request, "accounts/login.html", {"form": LoginForm()})

    form = LoginForm(request.POST)
    if not form.is_valid():
        return render(request, "accounts/login.html", {"form": form})

    attempt = attempt_login(
        request, form.cleaned_data["username"], form.cleaned_data["password"], via="page"
    )
    if not attempt.ok:
        retry_after = attempt.retry_after
        messages.error(
            request,
            f"Bonk.io login failed: {login_failure_message(attempt.error, retry_after)}",
        )
        # The page keeps the Login button off until the wait ends, so players
        # don't resubmit into it (6 tries in a minute on 2026-11-09).
        return render(request, "accounts/login.html", {"form": form, "retry_after": retry_after})

    sign_in(request, attempt.result)
    messages.success(request, "Logged in successfully!")

    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("my_profile")


@require_POST
@limit("write")
def logout_view(request):
    """POST only (the header's Log out is a form), so another site can't
    sign people out with a link or an <img>."""
    BonkSession(request.session).clear()
    logout(request)
    messages.success(request, "Logged out!")
    return redirect("home")


@limit("browse")
def me(request):
    """Who is signed in, for the skin editor (401 when nobody is)."""
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)

    return JsonResponse(
        {
            "authenticated": True,
            "user": {
                "id": request.user.id,
                "username": request.user.username,
            },
            "permissions": {
                "publish_skins": True,
            },
        }
    )
