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
from django.db import models, transaction
from django.utils import timezone

from core.background import enqueue
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
from . import bonk_tokens, devices, groups, known_accounts, used_here
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
    reclaimed = _reclaim(request, user, result.bonk_id, previous_lists)
    login(request, user)
    groups.after_login(request, previous, previous_lists, add=add)
    if reclaimed:
        _end_other_sessions(request, user)
    if add:
        log_event(user, "user_logged_in", added=True)
    else:
        log_event(user, "user_logged_in")
    # The login page's account chooser offers it next time, by password, and
    # signs it back in with one click for a while (ADR 0025).
    known_accounts.remember(request, user.username, known_accounts.PASSWORD)
    devices.remember_sign_in(request, user)
    if not add:
        used_here.offer_after_sign_in(request)

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


def _reclaim(request, user: BonkUser, bonk_id: int | None, previous_lists) -> bool:
    """The password beats an earlier friend-request claim (ADR 0024).

    A friend request can't show who started the claim it proves, so an
    account only ever proven that way may have been claimed by someone else.
    When its password signs in on a browser where its group's main isn't
    signed in and that the group doesn't trust, it leaves its group and every other browser's hold on it ends: one-click
    sign-ins here and the other sessions (after login, on the worker).

    Returns:
        Whether it was reclaimed.
    """
    if bonk_id is None:
        return False
    links = BonkAccountLink.objects.filter(user=user, bonk_player__bonk_id=bonk_id, active=True)
    if not links.exists() or links.filter(password_proven_at__isnull=False).exists():
        return False  # new here, or its password signed in before
    if user.account_group_id:
        password_ids, _ = previous_lists
        main_id = user.account_group.main_id
        if main_id in password_ids or devices.is_trusted(request, user.account_group_id):
            return False  # its group's own browser: the owner and their alt
    groups.take_out(user)
    devices.forget_all_sign_ins(user)
    log_event(user, "account_reclaimed_by_password")
    return True


def _end_other_sessions(request, user: BonkUser) -> None:
    """After the reclaim commits, end the other sessions on the worker; if
    the work can't be queued, here and now (it's what stops the claimer)."""
    from . import sessions, tasks  # tasks imports link_claims, which imports this module

    request.session.save()
    keep = request.session.session_key

    def run():
        if not enqueue(tasks.end_other_sessions, user.pk, keep):
            sessions.end_other_sessions(user.pk, keep)

    transaction.on_commit(run)


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
    # The login page's account chooser offers it next time, by friend request,
    # and signs it back in with one click for a while (ADR 0025).
    known_accounts.remember(request, user.username, known_accounts.FRIEND_REQUEST)
    devices.remember_sign_in(request, user)
    if not add:
        used_here.offer_after_sign_in(request)

    bonk = bonk_session(request)
    bonk.store_identity(username.value, bonk_id)
    return user


def sign_in_by_room_code(request, *, bonk_name: str, add: bool) -> BonkUser:
    """Sign the browser in as a bonk.io account proven by a code typed in a
    bot-hosted room (accounts/room_claims.py, ADR 0026, experimental), with
    no password.

    Like `sign_in_by_friend_request`, except that a room proves the name, not
    the account id: bonk.io's join event doesn't carry it. The player row is
    found by name (bonk.io names are unique ignoring case) and gets its id
    later, from a friend list or a password login.
    """
    previous = request.user if request.user.is_authenticated else None
    previous_lists = groups.browser_lists(request)

    username = BonkUsername(bonk_name)
    user = site_account_for(username)
    player = link_by_room_code(user, bonk_name=username.value)
    login(request, user)
    groups.after_login(request, previous, previous_lists, add=add)
    log_event(user, "user_logged_in", via="room_code", added=add)
    known_accounts.remember(request, user.username, known_accounts.ROOM_CODE)
    devices.remember_sign_in(request, user)
    if not add:
        used_here.offer_after_sign_in(request)

    bonk = bonk_session(request)
    bonk.store_identity(username.value, player.bonk_id)
    return user


def link_by_room_code(user: BonkUser, *, bonk_name: str) -> BonkPlayer:
    """Link `user` to the BonkPlayer named `bonk_name` (case ignored), made
    if Bonkverse hasn't seen the name yet. The link has no tokens and keeps
    any it had. Prefers a row whose bonk.io id is known."""
    player = (
        BonkPlayer.objects.filter(username__iexact=bonk_name)
        .order_by(models.F("bonk_id").asc(nulls_last=True), "pk")
        .first()
    )
    if player is None:
        player = BonkPlayer.objects.create(username=bonk_name, bonk_id=None)
    elif player.username != bonk_name:
        player.username = bonk_name
        player.save(update_fields=["username", "updated_at"])
    BonkAccountLink.objects.update_or_create(
        user=user, bonk_player=player, defaults={"active": True}
    )
    return player


def sign_in_with_one_click(request, user: BonkUser) -> None:
    """Sign the browser back in as `user` from "Choose an account", with no
    password and no bonk.io call (ADR 0025). The caller has checked
    `devices.one_click_ids`.

    Same as the other sign-ins otherwise: a main unlocks its group here
    (groups.after_login). It doesn't restart the one-click window: after
    ONE_CLICK_SIGN_IN_DAYS the account proves itself again.
    """
    previous = request.user if request.user.is_authenticated else None
    previous_lists = groups.browser_lists(request)
    login(request, user)
    groups.after_login(request, previous, previous_lists, add=False)
    log_event(user, "user_logged_in", via="one_click")
    way = known_accounts.way_in(request, user.username) or known_accounts.PASSWORD
    known_accounts.remember(request, user.username, way)
    used_here.offer_after_sign_in(request)
    groups.point_bonk_identity(request, user)


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
