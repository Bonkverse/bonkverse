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
from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.utils import timezone

from core.background import enqueue
from core.bonk import BonkUsername, same_name
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
    links = _links_to(user, name=result.username.value, bonk_id=result.bonk_id)
    reclaimed = _reclaim(request, user, links, previous_lists, holds=PASSWORD)
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


def _links_to(user: BonkUser, *, name: str, bonk_id: int | None = None):
    """`user`'s active links to one bonk.io account, whichever player row
    holds them: by `bonk_id` when known, and by `name` (capitalization only,
    `same_name`), since a room-code link may sit on a row whose id isn't
    known yet."""
    links = BonkAccountLink.objects.filter(user=user, active=True)
    match = models.Q(bonk_player__username__iexact=name)
    if bonk_id is not None:
        match |= models.Q(bonk_player__bonk_id=bonk_id)
    rows = links.filter(match).values_list("pk", "bonk_player__bonk_id", "bonk_player__username")
    keep = [
        pk
        for pk, row_id, linked in rows
        if (bonk_id is not None and row_id == bonk_id) or same_name(linked, name)
    ]
    return links.filter(pk__in=keep)


# What a new proof can't take an account back from. A password is beaten by
# nothing older than itself: it takes the account back from a friend request
# (which can't show who started the claim) and from a room code newer than
# the last password (a code can be relayed: someone talked into typing
# another person's code). A room code takes it back only from a friend
# request.
PASSWORD = models.Q(password_proven_at__isnull=False) & (
    models.Q(room_proven_at__isnull=True)
    | models.Q(password_proven_at__gte=models.F("room_proven_at"))
)
ROOM_CODE = models.Q(password_proven_at__isnull=False) | models.Q(room_proven_at__isnull=False)


def _reclaim(request, user: BonkUser, links, previous_lists, *, holds) -> bool:
    """The owner's proof takes an account back from a weaker one (ADR 0024,
    0026): if none of its `links` match `holds` (PASSWORD or ROOM_CODE), it
    may have been claimed by someone else.

    Unless this browser is its group's own (the main signed in here, or a
    browser the group trusts): it leaves its group (even as its main: the
    claimer may have built that group around it), its one-click sign-ins
    end, and every other session holding it ends (after login, on the
    worker). Call before the new proof is recorded on `links`.

    Returns:
        Whether it was reclaimed.
    """
    if not links.exists() or links.filter(holds).exists():
        return False  # new here, or already proven at least this strongly
    if user.account_group_id:
        password_ids, _ = previous_lists
        main_id = user.account_group.main_id
        if main_id in password_ids or devices.is_trusted(request, user.account_group_id):
            return False  # its group's own browser: the owner and their alt
    groups.take_out(user)
    devices.forget_all_sign_ins(user)
    log_event(user, "account_reclaimed_by_owner")
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


def sign_in_by_room_code(
    request, *, bonk_name: str, add: bool, level: int | None = None
) -> BonkUser:
    """Sign the browser in as a bonk.io account proven by a code typed in a
    bot-hosted room (accounts/room_claims.py, ADR 0026, experimental), with
    no password.

    The code is shown only in the browser that asked, so this counts as the
    owner's proof, the same as a password (owner decision 2026-11-27): it
    works for accounts already on Bonkverse, takes back one that only a
    friend request had claimed (`_reclaim`), and with the `level` the room
    showed, lets it vote. It gives no tokens (Wear asks for the password
    once) and no friend lists.

    A room proves the name, not the account id: bonk.io's join event doesn't
    carry it. The player row is found by name (bonk.io names are unique
    ignoring case) and gets its id later, from a friend list or a password
    login.
    """
    previous = request.user if request.user.is_authenticated else None
    previous_lists = groups.browser_lists(request)

    username = BonkUsername(bonk_name)
    user = site_account_for(username)
    links = _links_to(user, name=username.value)
    player = _player_named(username.value, linked=links)
    reclaimed = _reclaim(request, user, links, previous_lists, holds=ROOM_CODE)
    link_by_room_code(user, player=player, level=level)
    login(request, user)
    groups.after_login(request, previous, previous_lists, add=add)
    if reclaimed:
        _end_other_sessions(request, user)
    log_event(user, "user_logged_in", via="room_code", added=add)
    known_accounts.remember(request, user.username, known_accounts.ROOM_CODE)
    devices.remember_sign_in(request, user)
    if not add:
        used_here.offer_after_sign_in(request)

    bonk = bonk_session(request)
    bonk.store_identity(username.value, player.bonk_id)
    return user


def _player_named(bonk_name: str, *, linked=None) -> BonkPlayer:
    """The BonkPlayer named `bonk_name` (capitalization only), made if
    Bonkverse hasn't seen the name yet. Prefers the row the account already
    links to (`linked`), so older data with two rows for one name doesn't get
    a second link; then a row whose bonk.io id is known."""
    already = linked.select_related("bonk_player").first() if linked is not None else None
    if already is not None:
        return already.bonk_player
    rows = BonkPlayer.objects.filter(username__iexact=bonk_name).order_by(
        models.F("bonk_id").asc(nulls_last=True), "pk"
    )
    player = next((row for row in rows if same_name(row.username, bonk_name)), None)
    if player is None:
        return BonkPlayer.objects.create(username=bonk_name, bonk_id=None)
    if player.username != bonk_name:
        player.username = bonk_name
        player.save(update_fields=["username", "updated_at"])
    return player


def link_by_room_code(
    user: BonkUser, *, player: BonkPlayer, level: int | None = None
) -> BonkAccountLink:
    """Link `user` to `player` after a room code proved it (`room_proven_at`,
    and the room's `level` when it showed one). The link has no tokens and
    keeps any it had, and the player's XP isn't touched: the vote rule reads
    `room_level` (groups.voting_standing)."""
    defaults = {"active": True, "room_proven_at": timezone.now()}
    if level and level > 0:
        defaults["room_level"] = level
    link, _ = BonkAccountLink.objects.update_or_create(
        user=user, bonk_player=player, defaults=defaults
    )
    return link


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


class ProtectedSiteAccount(PermissionDenied):
    """The bonk.io name matches a staff, superuser or password-holding site
    account that was never linked to that bonk.io account. Bonkverse doesn't
    sign anyone in to it by bonk.io name (a PermissionDenied, so a caller
    that doesn't catch it answers 403)."""

    message = (
        "That name belongs to a Bonkverse staff account, so it can't be signed in "
        "to with bonk.io. If it's yours, ask the Bonkverse team."
    )


def _protected(user: BonkUser, name: str) -> bool:
    """Whether `user` is a site account Bonkverse made or keeps outside
    bonk.io (staff, superuser, or one with its own password, which bonk.io
    accounts never have) and isn't linked to the bonk.io account `name`.

    A bonk.io name proves only that someone owns that name on bonk.io, and
    anyone can register a free one. Signing it in to a site account by name
    is right for accounts bonk.io made; for one made with `createsuperuser`
    (say "admin") it would hand the account to whoever registers or already
    owns that name on bonk.io."""
    # An empty password field isn't a password: rows made without
    # create_user have one, and Django calls it "usable".
    has_password = bool(user.password) and user.has_usable_password()
    if not (user.is_staff or user.is_superuser or has_password):
        return False
    linked = BonkAccountLink.objects.filter(
        user=user, bonk_player__username__iexact=name
    ).values_list("bonk_player__username", flat=True)
    return not any(same_name(linked_name, name) for linked_name in linked)


def refuses_bonk_sign_in(name: str) -> bool:
    """Whether a bonk.io sign-in as `name` would be refused
    (`ProtectedSiteAccount`): checked before a room opens for it."""
    candidates = BonkUser.objects.filter(username__iexact=name)
    return any(same_name(user.username, name) and _protected(user, name) for user in candidates)


def site_account_for(username: BonkUsername) -> BonkUser:
    """The site account for a bonk.io name, created on first login.

    Matched case-insensitively because bonk.io names are unique that way
    (docs/bonk/accounts.md), so "the saucy tulip" and "The Saucy Tulip" are
    one account. An exact-spelling match wins if older data holds more than
    one. An existing account keeps its stored spelling: skins and other rows
    refer to it by that name.

    Only capitalization is ignored (core.bonk.usernames.fold). `__iexact`
    alone compares with Postgres's UPPER(), which also turns "ı" into "I"
    and "ſ" into "S": a bonk.io account named "admın" would be signed in to
    the site account "admin". `__iexact` narrows the search; `same_name`
    decides.

    Raises:
        ProtectedSiteAccount: the name matches a staff, superuser or
            password-holding site account not linked to that bonk.io account
            (`_protected`). Nothing has changed when it's raised.
    """
    candidates = list(BonkUser.objects.filter(username__iexact=username.value).order_by("pk"))
    matches = [user for user in candidates if same_name(user.username, username.value)]
    if len(matches) != len(candidates):
        # A bonk.io name that the database's case rule matches to an account
        # it isn't: either someone trying a look-alike name, or (if bonk.io
        # itself treats the two as one) a real player split in two here.
        # Either way someone should look. Ids only, never names.
        logger.warning(
            "login name matched site accounts %s only by a look-alike letter; not signed in to them",
            [user.pk for user in candidates if user not in matches],
        )
    if len(matches) > 1:
        # No names in the log line; the count and ids are enough to find them.
        logger.warning(
            "site accounts %s match one bonk.io name case-insensitively",
            [user.pk for user in matches],
        )
    exact = [user for user in matches if user.username == username.value]
    user = (exact or matches or [None])[0]
    if user is None:
        return BonkUser.objects.create_user(username=username.value)
    if _protected(user, username.value):
        # Ids only, never names.
        logger.warning("bonk.io sign-in refused for unlinked staff site account %s", user.pk)
        raise ProtectedSiteAccount(ProtectedSiteAccount.message)
    return user


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
