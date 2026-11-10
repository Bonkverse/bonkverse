"""The /login/ and /logout/ pages, and what a failed bonk.io login says.

Owns: the login and logout views and the sentences shown when bonk.io (or
our limit on wrong passwords) turns a login down.
Does not own: trying the bonk.io login and the limit on wrong passwords
(login_attempts.py), what a successful login does (sign_in.py: site
account, account link, Flash friends, queueing the friend sync), or talking
to bonk.io (integrations/bonk_api.py).
"""

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.bonk import BonkSession
from core.ratelimits import describe_wait, limit
from integrations.bonk_api import BonkError

from .forms import LoginForm
from .login_attempts import COUNTED_FAILURES, TOO_MANY_ATTEMPTS, attempt_login
from .sign_in import sign_in

# What a player sees when bonk.io turns a login down, by BonkError code.
# Also used by the in-page bonk.io login on wear (wear_skin.py).
LOGIN_FAILURE_MESSAGES = {
    BonkError.WRONG_PASSWORD: "Wrong password.",
    BonkError.UNKNOWN_USERNAME: "No bonk.io account has that username.",
    BonkError.RATE_LIMITED: (
        "bonk.io is limiting logins from Bonkverse right now. Try again in {wait}."
    ),
    # Held by Bonkverse (login_attempts.py) before bonk.io saw it. Says why, so
    # it doesn't read as the site being broken.
    TOO_MANY_ATTEMPTS: (
        "Too many wrong passwords. Wait {wait} before trying again, so bonk.io "
        "doesn't block logins for everyone on Bonkverse."
    ),
    BonkError.REJECTED: "bonk.io didn't accept that login.",
    BonkError.UNAVAILABLE: "Network error talking to bonk.io. Try again in a minute.",
}

# Added to "Wrong password." when it used up the player's tries for now.
LAST_TRY_MESSAGE = (
    "That was your last try for now: wait {wait} before trying again, so bonk.io "
    "doesn't block logins for everyone on Bonkverse."
)


def login_failure_message(error: str | None, retry_after: int | None = None) -> str:
    """The user-facing sentence for a failed bonk.io login.

    `retry_after` is the seconds to wait, for the sentences that say how long
    ("a few minutes" when unknown).
    """
    message = LOGIN_FAILURE_MESSAGES.get(error, LOGIN_FAILURE_MESSAGES[BonkError.REJECTED])
    if error in COUNTED_FAILURES and retry_after:
        # That wrong try was the last one for now (login_attempts.py).
        message = f"{message} {LAST_TRY_MESSAGE}"
    if "{wait}" in message:
        wait = describe_wait(retry_after) if retry_after else "a few minutes"
        message = message.format(wait=wait)
    return message


@limit("login", method="POST")
def login_view(request):
    if request.method != "POST":
        return render(request, "skins/login.html", {"form": LoginForm()})

    form = LoginForm(request.POST)
    if not form.is_valid():
        return render(request, "skins/login.html", {"form": form})

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
        return render(request, "skins/login.html", {"form": form, "retry_after": retry_after})

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
