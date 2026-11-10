"""Signing in to Bonkverse with a bonk.io account, and signing out.

Owns: the /login/ and /logout/ views, finding or creating the site account
for a bonk.io name, linking it to its BonkPlayer, syncing Flash friends from
the login reply, and queueing the regular friend sync on the worker.
Does not own: trying the bonk.io login and the limit on wrong passwords
(login_attempts.py), talking to bonk.io (integrations/bonk_api.py), the bonk.io
session rules (core/bonk/session.py) or friend storage (friends_sync.py,
flash_friends_sync.py).
"""

import logging

from django.conf import settings
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.background import enqueue
from core.bonk import BonkSession, BonkUsername
from core.ratelimits import describe_wait, limit
from integrations.bonk_api import BonkError, BonkLoginResult
from skins.events import log_event

from .flash_friends_sync import sync_flash_friends_for_user
from .forms import LoginForm
from .friends_sync import adopt_replay_names
from .login_attempts import COUNTED_FAILURES, TOO_MANY_ATTEMPTS, attempt_login
from .models import BonkAccountLink, BonkPlayer, BonkUser
from .tasks import sync_friends

logger = logging.getLogger(__name__)

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


def site_account_for(username: BonkUsername) -> BonkUser:
    """The site account for a bonk.io name, created on first login.

    Matched case-insensitively because bonk.io names are unique that way
    (docs/bonk/accounts.md), so "the saucy tulip" and "The Saucy Tulip" are
    one account. An exact-spelling match wins if older data holds more than
    one. An existing account keeps its stored spelling: skins and other rows
    refer to it by that name.
    """
    matches = list(BonkUser.objects.filter(username__iexact=username.value).order_by("pk"))
    if len(matches) > 1:
        # No names in the log line; the count and ids are enough to find them.
        logger.warning(
            "site accounts %s match one bonk.io name case-insensitively",
            [user.pk for user in matches],
        )
    for user in matches:
        if user.username == username.value:
            return user
    if matches:
        return matches[0]
    return BonkUser.objects.create_user(username=username.value)


def _link_bonk_player(user: BonkUser, result: BonkLoginResult) -> BonkAccountLink:
    """Create or refresh the BonkPlayer and its link to the site account."""
    adopt_replay_names({result.bonk_id: result.username.value})
    player, created = BonkPlayer.objects.get_or_create(
        bonk_id=result.bonk_id,
        defaults={"username": result.username.value},
    )
    if not created and player.username != result.username.value:
        # bonk_id is the real identity; a different name here means our stored
        # copy is stale (e.g. stripped by an old bug), so correct it.
        logger.warning(
            "BonkPlayer username for bonk_id=%s differed from login response; corrected",
            result.bonk_id,
        )
        player.username = result.username.value
        player.save(update_fields=["username", "updated_at"])
    if result.xp is not None:
        player.xp = result.xp
        player.xp_seen_at = timezone.now()
        player.save(update_fields=["xp", "xp_seen_at", "updated_at"])
    link, _ = BonkAccountLink.objects.update_or_create(
        user=user,
        bonk_player=player,
        defaults={
            "token_encrypted": BonkAccountLink.sign_token(result.token),
            "scopes": {"friends": True},
            "active": True,
        },
    )
    return link


def _queue_friend_sync(request, link_id: int) -> None:
    """Hand the regular friend sync (friends.php) to the worker.

    The profile page shows a toast that polls /api/friends-sync-status/ until
    the task logs `friends_synced`; it's only shown when the sync was queued.
    """
    if enqueue(sync_friends, link_id):
        request.session["show_friend_sync_toast"] = True


def _sign_in(request, result: BonkLoginResult) -> None:
    """Everything a successful bonk.io login does on our side."""
    bonk = BonkSession(request.session)
    bonk.store_token(result.token)
    bonk.store_identity(result.username.value, result.bonk_id)
    # Remember the active slot so wear works immediately without the modal.
    bonk.store_active_slot(result.active_slot)

    user = site_account_for(result.username)
    login(request, user)
    log_event(user, "user_logged_in")

    link = None
    if result.bonk_id is not None:
        try:
            link = _link_bonk_player(user, result)
        except Exception:
            logger.exception("Could not persist account link")

    try:
        flash_stats = sync_flash_friends_for_user(
            user=user, friends_json={"legacyFriends": result.legacy_friends}
        )
        log_event(user, "flash_friends_synced", **flash_stats)
    except Exception:
        logger.exception("flash friends sync at login failed")

    # Regular friends come from a second bonk.io call, so they sync on the
    # worker; the task reads the token from the link, never from the queue.
    # Requests run in autocommit (no ATOMIC_REQUESTS; a test pins it), so the
    # link is committed already and the worker can't run before it exists.
    if settings.SYNC_FRIENDS_ON_LOGIN and link is not None:
        _queue_friend_sync(request, link.id)


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

    _sign_in(request, attempt.result)
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
