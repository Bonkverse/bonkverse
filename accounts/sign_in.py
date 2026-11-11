"""What a successful bonk.io login does on our side.

Owns: finding or creating the site account for a bonk.io name, linking it to
its BonkPlayer (with the signed token), storing the bonk.io session, syncing
Flash friends from the login reply, and queueing the regular friend sync on
the worker.
Does not own: the /login/ page (views.py) and its messages (login_messages.py), trying the
bonk.io login and the limit on wrong passwords (login_attempts.py), the
bonk.io session rules (core/bonk/session.py) or friend storage
(players/friends_sync.py, players/flash_friends_sync.py).
"""

import logging

from django.conf import settings
from django.contrib.auth import login
from django.utils import timezone

from core.bonk import BonkSession, BonkUsername
from integrations.bonk_api import BonkLoginResult

from players.services import (
    adopt_replay_names,
    queue_friend_sync as queue_players_friend_sync,
    sync_flash_friends_for_user,
)

from players.models import BonkPlayer
from skins.events import log_event
from skins.models import BonkAccountLink, BonkUser

logger = logging.getLogger(__name__)


def sign_in(request, result: BonkLoginResult) -> BonkUser:
    """Sign the visitor in after bonk.io accepted their login.

    Steps, in order: store the bonk.io session (token, name, id, active
    slot), log in the site account (created on first login), link it to the
    BonkPlayer, store Flash friends, and queue the regular friend sync. Only
    the session and the site login are required: a failure in the later
    steps is logged and the player is still signed in.

    Returns:
        The site account now logged in.
    """
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
            link = link_bonk_player(user, result)
        except Exception:
            logger.exception("Could not persist account link")

    try:
        flash_stats = sync_flash_friends_for_user(user=user, legacy_friends=result.legacy_friends)
        log_event(user, "flash_friends_synced", **flash_stats)
    except Exception:
        logger.exception("flash friends sync at login failed")

    # Regular friends come from a second bonk.io call, so they sync on the
    # worker; the task reads the token from the link, never from the queue.
    # Requests run in autocommit (no ATOMIC_REQUESTS; a test pins it), so the
    # link is committed already and the worker can't run before it exists.
    if settings.SYNC_FRIENDS_ON_LOGIN and link is not None:
        queue_friend_sync(request, link.id)
    return user


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


def link_bonk_player(user: BonkUser, result: BonkLoginResult) -> BonkAccountLink:
    """Create or refresh the BonkPlayer and its link to the site account.

    The player's stored name is corrected to bonk.io's spelling (bonk_id is
    the real identity), its XP is recorded when the reply has it, and the
    link stores the token signed (BonkAccountLink.sign_token).
    """
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


def queue_friend_sync(request, link_id: int) -> bool:
    """Hand the regular friend sync (friends.php) to the worker.

    The profile page shows a toast that polls /api/friends-sync-status/ until
    the task logs `friends_synced`; it's only shown when the sync was queued.
    Returns whether it was queued.
    """
    queued = queue_players_friend_sync(link_id)
    if queued:
        request.session["show_friend_sync_toast"] = True
    return queued
