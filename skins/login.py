"""Signing in to Bonkverse with a bonk.io account, and signing out.

Owns: the /login/ and /logout/ views, finding or creating the site account
for a bonk.io name, linking it to its BonkPlayer, and starting friend syncs.
Does not own: talking to bonk.io (integrations/bonk_api.py), the bonk.io
session rules (core/bonk/session.py) or friend storage (friends_sync.py,
flash_friends_sync.py).
"""

import logging
import threading
import time

from django.conf import settings
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth import login, logout
from django.core import signing
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from core.bonk import BonkSession, BonkUsername
from core.ratelimits import limit
from integrations.bonk_api import BonkError, BonkLoginResult, get_client
from skins.events import log_event

from .flash_friends_sync import sync_flash_friends_for_user
from .forms import LoginForm
from .friends_sync import adopt_replay_names, sync_friends_for_player
from .models import BonkAccountLink, BonkPlayer, BonkUser

logger = logging.getLogger(__name__)

# What a player sees when bonk.io turns a login down, by BonkError code.
# Also used by the in-page bonk.io login on wear (wear_skin.py).
LOGIN_FAILURE_MESSAGES = {
    BonkError.WRONG_PASSWORD: "Wrong password.",
    BonkError.UNKNOWN_USERNAME: "No bonk.io account has that username.",
    BonkError.RATE_LIMITED: (
        "bonk.io is limiting logins from Bonkverse right now. Try again in a few minutes."
    ),
    BonkError.REJECTED: "bonk.io didn't accept that login.",
    BonkError.UNAVAILABLE: "Network error talking to bonk.io. Try again in a minute.",
}


def login_failure_message(error: str | None) -> str:
    """The user-facing sentence for a failed bonk.io login."""
    return LOGIN_FAILURE_MESSAGES.get(error, LOGIN_FAILURE_MESSAGES[BonkError.REJECTED])


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


def _link_bonk_player(user: BonkUser, result: BonkLoginResult) -> None:
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
    BonkAccountLink.objects.update_or_create(
        user=user,
        bonk_player=player,
        defaults={
            "token_encrypted": signing.dumps({"t": result.token}, salt="bonk_token"),
            "scopes": {"friends": True},
            "active": True,
        },
    )


def _sync_friends_bg(user, current_bonk_id: int | None, current_username: str, token: str) -> None:
    """Background sync of regular friends (friends.php). Flash friends sync at login."""
    t0 = time.monotonic()
    try:
        result = get_client().get_friends(token)
        if not result.ok:
            logger.warning(
                "friends sync skipped: %s (bonk_error=%s)", result.error, result.bonk_error
            )
            return

        stats = sync_friends_for_player(
            current_bonk_id=current_bonk_id,
            current_username=current_username,
            friends=result.friends,
            requests=result.requests,
        )
        logger.info(
            "regular friends synced for bonk_id=%s: %s (%.2fs)",
            current_bonk_id,
            stats,
            time.monotonic() - t0,
        )
        log_event(user, "friends_synced", **stats)
    except Exception:
        logger.exception("background friends sync failed for bonk_id=%s", current_bonk_id)


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

    if result.bonk_id is not None:
        try:
            _link_bonk_player(user, result)
        except Exception:
            logger.exception("Could not persist account link")

    try:
        flash_stats = sync_flash_friends_for_user(
            user=user, friends_json={"legacyFriends": result.legacy_friends}
        )
        log_event(user, "flash_friends_synced", **flash_stats)
    except Exception:
        logger.exception("flash friends sync at login failed")

    # The profile page shows a toast that polls /api/friends-sync-status/
    # until this background sync finishes.
    if settings.SYNC_FRIENDS_ON_LOGIN:
        threading.Thread(
            target=_sync_friends_bg,
            args=(user, result.bonk_id, result.username.value, result.token),
            daemon=True,
        ).start()
        request.session["show_friend_sync_toast"] = True


@limit("login", method="POST")
def login_view(request):
    if request.method != "POST":
        return render(request, "skins/login.html", {"form": LoginForm()})

    form = LoginForm(request.POST)
    if not form.is_valid():
        return render(request, "skins/login.html", {"form": form})

    result = get_client().login(form.cleaned_data["username"], form.cleaned_data["password"])
    # Outcome only: a success holds the player's token, username, id and avatar.
    logger.info(
        "bonk login response | result=%s | error=%s | bonk_error=%s",
        "success" if result.ok else "fail",
        result.error,
        result.bonk_error,
    )
    if not result.ok:
        messages.error(request, f"Bonk.io login failed: {login_failure_message(result.error)}")
        return render(request, "skins/login.html", {"form": form})

    _sign_in(request, result)
    messages.success(request, "Logged in successfully!")

    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("my_profile")


@limit("write")
def logout_view(request):
    BonkSession(request.session).clear()
    logout(request)
    messages.success(request, "Logged out!")
    return redirect("home")
