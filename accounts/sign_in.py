"""What a successful bonk.io login does on our side.

Owns: finding or creating the site account for a bonk.io name, linking it to
its BonkPlayer (with the encrypted token and the skin the player is wearing),
storing the bonk.io session, syncing
Flash friends from the login reply, and queueing the regular friend sync on
the worker: from the friend list in the login answer when it has one, else
from friends.php (RFC-0003 phase 2). Also linking the account the Wear
popup logged in to (connect_from_wear). Tokens are stored through the token
broker (bonk_tokens.py).
Does not own: the /login/ page (views.py) and its messages (login_messages.py), trying the
bonk.io login and the limit on wrong passwords (login_attempts.py), the
bonk.io session rules (core/bonk/session.py) or friend storage
(players/friends_sync.py, players/flash_friends_sync.py).
"""

import logging

from django.conf import settings
from django.contrib.auth import login
from django.utils import timezone

from core.bonk import BonkUsername
from core.token_crypto import bonk_session
from integrations.bonk_api import BonkLoginResult

from players.services import (
    WornSkinSource,
    adopt_replay_names,
    forget_user_skin,
    queue_friend_sync as queue_players_friend_sync,
    queue_login_friends,
    record_worn_skin,
    sync_flash_friends_for_user,
)

from players.models import BonkPlayer
from . import bonk_tokens, groups
from .events import log_event
from .models import BonkUser
from .models import BonkAccountLink

logger = logging.getLogger(__name__)


def sign_in(
    request, result: BonkLoginResult, *, remember: bool = False, add: bool = False
) -> BonkUser:
    """Sign the visitor in after bonk.io accepted their login.

    With `add` ("Add account", RFC-0003 phase 5), the account joins the group
    of the account signed in before and both stay signed in on this browser
    (groups.after_login); without it, a login while signed in replaces the
    session unless the two are already in one group.

    Steps, in order: note which bonk.io account this browser acts as (name,
    id, active slot), log in the site account (created on first login), link
    it to the BonkPlayer with its tokens (through the token broker,
    bonk_tokens.py; the remember-me token only when `remember`), store Flash
    friends, and queue the regular friend sync. Only the session and the
    site login are required: a failure in the later steps is logged and the
    player is still signed in.

    The bonk.io tokens live on the account link only, never in the site
    session (RFC-0003 Part 2).

    Returns:
        The site account now logged in.
    """
    previous = request.user if request.user.is_authenticated else None
    previous_lists = groups.browser_lists(request)

    user = site_account_for(result.username)
    login(request, user)
    groups.after_login(request, previous, previous_lists, add=add)
    if add:
        log_event(user, "user_logged_in", added=True)
    else:
        log_event(user, "user_logged_in")

    # After login(): changing the user flushes the session.
    bonk = bonk_session(request)
    bonk.store_identity(result.username.value, result.bonk_id)
    # Remember the active slot so wear works immediately without the modal.
    bonk.store_active_slot(result.active_slot)

    link = None
    if result.bonk_id is not None:
        try:
            link = link_bonk_player(user, result, remember=remember)
        except Exception:
            logger.exception("Could not persist account link")

    try:
        flash_stats = sync_flash_friends_for_user(user=user, legacy_friends=result.legacy_friends)
        log_event(user, "flash_friends_synced", **flash_stats)
    except Exception:
        logger.exception("flash friends sync at login failed")

    # Regular friends sync on the worker. When the login answer carried the
    # friend list, the worker stores that list and bonk.io isn't called
    # again; otherwise it reads friends.php with the token from the link,
    # never from the queue. Requests run in autocommit (no ATOMIC_REQUESTS; a
    # test pins it), so the link is committed already and the worker can't
    # run before it exists.
    if settings.SYNC_FRIENDS_ON_LOGIN and link is not None:
        queue_friend_sync(request, link.id, result)
    return user


def sign_in_by_friend_request(request, *, bonk_id: int, bonk_name: str, add: bool) -> BonkUser:
    """Sign the browser in as a bonk.io account proven by a friend request
    (accounts/link_claims.py, RFC-0003 phase 6), with no password.

    Like `sign_in`, without what only a password login gives: no tokens (Wear
    asks for the password once, later), no XP (no vote until one password
    login, skins.votes), no friend lists. With `add` it joins the group of
    the account signed in before; a main signed in this way unlocks its
    group, the same as a password sign-in (groups.after_login).

    Returns:
        The site account now logged in.
    """
    previous = request.user if request.user.is_authenticated else None
    previous_lists = groups.browser_lists(request)

    username = BonkUsername(bonk_name)
    user = site_account_for(username)
    link_by_friend_request(user, bonk_id=bonk_id, bonk_name=username.value)
    login(request, user)
    groups.after_login(request, previous, previous_lists, add=add)
    log_event(user, "user_logged_in", via="friend_request", added=add)

    bonk = bonk_session(request)
    bonk.store_identity(username.value, bonk_id)
    return user


def link_by_friend_request(user: BonkUser, *, bonk_id: int, bonk_name: str) -> BonkAccountLink:
    """Link `user` to the BonkPlayer `bonk_id` after a friend request proved
    it. The link has no tokens and keeps any it had; `password_proven_at`
    isn't touched (a friend request doesn't tell us the level)."""
    adopt_replay_names({bonk_id: bonk_name})
    player, created = BonkPlayer.objects.get_or_create(
        bonk_id=bonk_id, defaults={"username": bonk_name}
    )
    if not created and player.username != bonk_name:
        player.username = bonk_name
        player.save(update_fields=["username", "updated_at"])
    link, _ = BonkAccountLink.objects.update_or_create(
        user=user, bonk_player=player, defaults={"active": True}
    )
    return link


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


def link_bonk_player(
    user: BonkUser, result: BonkLoginResult, *, remember: bool = False
) -> BonkAccountLink:
    """Create or refresh the BonkPlayer and its link to the site account.

    The player's stored name is corrected to bonk.io's spelling (bonk_id is
    the real identity), its XP and worn skin (the active slot's) are recorded
    when the reply has them, and the link stores its tokens through the
    token broker (bonk_tokens.store_login).
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
            "scopes": {"friends": True},
            "active": True,
            # A password login: the account's level (XP) is known now.
            "password_proven_at": timezone.now(),
        },
    )
    bonk_tokens.store_login(link, result, remember=remember)
    record_worn_skin(result.bonk_id, result.skin_code, WornSkinSource.LOGIN)
    forget_user_skin(user)
    return link


def connect_from_wear(
    user: BonkUser, result: BonkLoginResult, *, remember: bool
) -> BonkAccountLink | None:
    """After the Wear popup's bonk.io login: link that account to the user
    (or refresh the existing link) with its new tokens, and record the skin
    it wears. Wear reads tokens from the link (bonk_tokens.usable_token).
    Returns the link, or None when bonk.io gave no account id.
    """
    if result.bonk_id is None:
        return None
    return link_bonk_player(user, result, remember=remember)


def queue_friend_sync(request, link_id: int, result: BonkLoginResult | None = None) -> bool:
    """Hand the regular friend sync to the worker.

    With the friend list from the login answer (`result.friends`), the worker
    stores it and bonk.io isn't called; without one, it reads friends.php.
    Each login logs which, so production shows whether bonk.io's answer
    carries the list (unconfirmed: docs/bonk/api.md).

    The profile page shows a toast that polls /api/friends-sync-status/ until
    the task logs `friends_synced`; it's only shown when the sync was queued.
    Returns whether it was queued.
    """
    if result is not None and result.friends is not None:
        logger.info(
            "login answer carried friends | friends=%s | requests=%s",
            len(result.friends),
            "none" if result.requests is None else len(result.requests),
        )
        queued = queue_login_friends(link_id, result.friends, result.requests)
    else:
        logger.info("login answer carried no friend list; reading friends.php")
        queued = queue_players_friend_sync(link_id)
    if queued:
        request.session["show_friend_sync_toast"] = True
    return queued
