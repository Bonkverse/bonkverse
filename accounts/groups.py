"""A person's bonk.io accounts: grouping them and switching between them.

Owns: AccountGroup membership (adding an account, removing one, the main
account), which accounts are signed in on this browser, switching the browser
to another of them, and signing out of one or all.
Does not own: the bonk.io login itself (login_attempts.py, sign_in.py), the
tokens of each account (bonk_tokens.py), or what each account owns (its
favorites, votes, uploads and privacy stay on its own site account).

RFC-0003 phase 5, ADR 0023. Each bonk.io account is its own site account
(BonkUser); a group ties several together. The browser is signed in as one
of them at a time (`request.user`, the "active account"), and that account
decides Wear, upload credit, votes, favorites and the header everywhere.

Switching needs no password, but only between accounts signed in on this
browser (`signed_in_ids`). An account is signed in here when:
- someone typed its password on this browser (SIGNED_IN_KEY), or
- the group's main signed in on this browser, which unlocks every account in
  the group (UNLOCKED_KEY) while the browser stays trusted (devices.py: 90
  days from last use, and removable from Settings).
Signing in to any other account opens only that account: only the main
unlocks the group, every time (RFC-0003 phase 5 decisions, PR 3; ADR 0023).
The group's other accounts are listed with "Sign in".

A plain login while signed in replaces the session, as before: only "Add
account" groups accounts, so logging in to a friend's account on your
browser never joins it to your group.
"""

from __future__ import annotations

import logging

from django.contrib.auth import login, logout
from django.db import transaction
from django.utils import timezone

from core.token_crypto import bonk_session

from core.bonk.levels import level_for_xp

from . import devices, known_accounts
from .events import log_event
from .models import AccountGroup, BonkAccountLink, BonkUser
from .signals import account_joined_group

logger = logging.getLogger(__name__)

# Site account ids signed in on this browser with their own password, oldest
# first. Survives the session flush Django does when login() changes the user.
SIGNED_IN_KEY = "bv_signed_in"
# Site account ids the group's main unlocked on this browser (only usable
# while devices.is_trusted says the browser is still trusted).
UNLOCKED_KEY = "bv_unlocked"
# Accounts signed in here only by a room code although they've used their
# password (ADR 0026): a code can be relayed, so they don't count as "the
# main signed in here" and can't take new accounts into their group.
CODE_ONLY_KEY = "bv_code_only"


class NotAllowed(Exception):
    """The action isn't allowed for this browser; `message` says why."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ── Reading ──────────────────────────────────────────────────────────


def members(user: BonkUser) -> list[BonkUser]:
    """Every account in `user`'s group (main first, then by when they joined),
    or just `user` when it has no group."""
    if user.account_group_id is None:
        return [user]
    group = user.account_group
    accounts = list(
        BonkUser.objects.filter(account_group_id=group.pk).order_by("joined_group_at", "pk")
    )
    accounts.sort(key=lambda account: account.pk != group.main_id)
    return accounts


def member_ids(user: BonkUser) -> list[int]:
    """Ids of every account in `user`'s group, or just `user`'s."""
    if user.account_group_id is None:
        return [user.pk]
    return list(
        BonkUser.objects.filter(account_group_id=user.account_group_id).values_list("pk", flat=True)
    )


def bonk_level(user: BonkUser) -> int | None:
    """The account's bonk.io level from the XP stored at its last sign-in
    (the highest of its linked bonk.io accounts), or None if never stored."""
    xp = (
        BonkAccountLink.objects.filter(user=user, active=True, bonk_player__xp__isnull=False)
        .order_by("-bonk_player__xp")
        .values_list("bonk_player__xp", flat=True)
        .first()
    )
    return None if xp is None else level_for_xp(xp)


def voting_standing(user: BonkUser) -> tuple[int | None, bool]:
    """(bonk.io level or None, never proven with its password) for the vote
    rule, in one query.

    The level is the highest known across its links: from the XP stored at a
    password sign-in, or the level a room showed at a room-code sign-in.
    "Never proven with its password": it has links and none has a password
    proof. Accounts from before friend-request linking all came in by
    password, so a missing level only blocks voting when there's no
    password proof either (skins.votes.why_cant_vote)."""
    rows = list(
        BonkAccountLink.objects.filter(user=user, active=True).values_list(
            "bonk_player__xp", "room_level", "password_proven_at"
        )
    )
    levels = [level_for_xp(xp) for xp, _, _ in rows if xp is not None]
    levels += [level for _, level, _ in rows if level]
    level = max(levels) if levels else None
    return level, bool(rows) and all(proven is None for _, _, proven in rows)


def main_signed_in_here(request) -> bool:
    """Whether the group's main is signed in on this browser (true for an
    account with no group). Actions that change the other accounts need it."""
    group = request.user.account_group if request.user.account_group_id else None
    return group is None or _main_here(request, group)


def _main_here(request, group) -> bool:
    """The group's main is signed in on this browser by its own proof, not
    only by a room code (CODE_ONLY_KEY)."""
    return group.main_id in signed_in_ids(request) and group.main_id not in code_only_ids(request)


def code_only_ids(request) -> list[int]:
    return [i for i in request.session.get(CODE_ONLY_KEY, []) if isinstance(i, int)]


def is_main(user: BonkUser) -> bool:
    """Whether `user` is its group's main account (an ungrouped account is
    its own main)."""
    return user.account_group_id is None or user.account_group.main_id == user.pk


def same_group(a: BonkUser, b: BonkUser) -> bool:
    return a.pk == b.pk or (
        a.account_group_id is not None and a.account_group_id == b.account_group_id
    )


def _password_ids(request) -> list[int]:
    return [i for i in request.session.get(SIGNED_IN_KEY, []) if isinstance(i, int)]


def _unlocked_ids(request) -> list[int]:
    """The accounts the main unlocked here, while this browser is trusted for
    the active account's group; else []."""
    ids = [i for i in request.session.get(UNLOCKED_KEY, []) if isinstance(i, int)]
    if not ids or request.user.account_group_id is None:
        return []
    if not devices.is_trusted(request, request.user.account_group_id):
        return []
    return ids


def signed_in_ids(request) -> list[int]:
    """Ids of the accounts signed in on this browser, the active one included:
    those signed in with their own password, then those the main unlocked
    (while the browser is trusted). Sessions from before groups have no
    list: just the active account. Worked out once per request."""
    if not request.user.is_authenticated:
        return []
    cached = getattr(request, "_bv_signed_in", None)
    if cached is not None:
        return list(cached)
    ids = _password_ids(request)
    ids += [i for i in _unlocked_ids(request) if i not in ids]
    if request.user.pk not in ids:
        ids.append(request.user.pk)
    request._bv_signed_in = ids
    return list(ids)


def _forget_cache(request) -> None:
    if hasattr(request, "_bv_signed_in"):
        del request._bv_signed_in


class BrowserLists(tuple):
    """(password ids, unlocked ids), with `.code_only` (CODE_ONLY_KEY)
    carried alongside so it survives login()'s session flush too."""

    code_only: list[int]


def _lists(password, unlocked, code_only=()) -> BrowserLists:
    lists = BrowserLists((password, unlocked))
    lists.code_only = list(code_only)
    return lists


def browser_lists(request) -> BrowserLists:
    """(password ids, unlocked ids) as stored for this browser, to carry
    across login()'s session flush, plus `.code_only`. The unlocked list
    stays separate so a removed or expired trust still ends it. A session
    from before groups counts its active account as signed in with its
    password."""
    if not request.user.is_authenticated:
        return _lists([], [])
    password = _password_ids(request)
    unlocked = [i for i in request.session.get(UNLOCKED_KEY, []) if isinstance(i, int)]
    if request.user.pk not in password and request.user.pk not in unlocked:
        password.append(request.user.pk)
    return _lists(password, unlocked, code_only_ids(request))


def _store(request, password: list[int], unlocked: list[int]) -> None:
    request.session[SIGNED_IN_KEY] = password
    request.session[UNLOCKED_KEY] = [i for i in unlocked if i not in password]
    _forget_cache(request)


def accounts_for(request) -> list[dict]:
    """The account menu and settings list for this browser: every account in
    the active account's group, with whether it's the active one, the main,
    signed in here, and connected for Wear. No secrets."""
    if not request.user.is_authenticated:
        return []
    here = set(signed_in_ids(request))
    group = request.user.account_group if request.user.account_group_id else None
    rows = []
    for account in members(request.user):
        rows.append(
            {
                "id": account.pk,
                "username": account.username,
                "active": account.pk == request.user.pk,
                "main": group is None or group.main_id == account.pk,
                "signed_in": account.pk in here,
                "connected": _connected_for_wear(account),
            }
        )
    return rows


def _connected_for_wear(account: BonkUser) -> bool:
    """Whether Wear can act as `account` without its password: a remember-me
    token, or a session token that hasn't expired."""
    for link in BonkAccountLink.objects.filter(user=account, active=True):
        if link.remember_status == BonkAccountLink.REMEMBER_ACTIVE or link.bonk_token():
            return True
    return False


# ── Signing in, switching, signing out ───────────────────────────────


def after_login(
    request,
    previous: BonkUser | None,
    previous_lists: BrowserLists,
    *,
    add: bool,
    unlock: bool = True,
):
    """Call right after login() put `request.user` in this browser (signed in
    with its password).

    `previous` and `previous_lists` (from `browser_lists`, taken before
    login() may have flushed the session) are who was signed in before. With
    `add` ("Add account"), the new account joins `previous`'s group and the
    browser keeps every account it had; a plain login keeps them only when
    the new account is already in the same group, and otherwise starts over.
    If the new account is its group's main, this browser becomes trusted and
    every account in the group is unlocked here, unless `unlock` is False (a
    room code for an account that has used its password, ADR 0026): then it
    opens only itself and is marked code-only here (CODE_ONLY_KEY), so it
    doesn't count as the main signed in here and adds nothing to its group.
    """
    user = request.user
    was_code_only = list(getattr(previous_lists, "code_only", []))
    # An account in only by a room code can't take new ones into its group.
    if add and previous is not None and previous.pk != user.pk and previous.pk not in was_code_only:
        join(previous, user)
        user.refresh_from_db()
        previous.refresh_from_db()
    keep = previous is not None and same_group(previous, user)
    password, unlocked = previous_lists if keep else ([], [])
    password = [i for i in password if i != user.pk] + [user.pk]
    code_only = [i for i in (was_code_only if keep else []) if i != user.pk]
    if not unlock:
        code_only.append(user.pk)
    elif user.account_group_id is not None and is_main(user):
        # Only the main unlocks the group, and only on this browser.
        devices.trust(request, user.account_group)
        unlocked = member_ids(user)
    _store(request, password, unlocked)
    request.session[CODE_ONLY_KEY] = code_only


def add_signed_in_here(request, account_ids: list[int]) -> None:
    """Count `account_ids` (just proven or added from this browser) as signed
    in here, behind the account in use."""
    password, unlocked = browser_lists(request)
    current = request.user.pk
    added = [pk for pk in account_ids if pk not in password and pk != current]
    password = [pk for pk in password if pk != current] + added + [current]
    _store(request, password, unlocked)
    _forget_cache(request)


def switch(request, target_id: int) -> BonkUser:
    """Make another account signed in on this browser the active one.

    Raises:
        NotAllowed: not in this account's group, or not signed in here.
    """
    current = request.user
    target = BonkUser.objects.filter(pk=target_id).select_related("account_group").first()
    if target is None or not same_group(current, target):
        raise NotAllowed("That account isn't one of yours.")
    if target.pk == current.pk:
        return current
    if target.pk not in signed_in_ids(request):
        raise NotAllowed(f"Sign in to {target.username} on this browser first.")
    _become(request, target, browser_lists(request))
    log_event(target, "account_switched", from_user_id=current.pk)
    return target


def sign_out(request, *, everywhere_here: bool, forget_device: bool = False) -> BonkUser | None:
    """Sign out of the active account, or of every account on this browser.

    Signing out of one account switches to the most recent other account
    still signed in here. `forget_device` (with everywhere_here: "Also forget
    this device") stops trusting this browser for the group, ends one-click
    sign-in here and empties "Choose an account". Returns the
    account now active, or None.
    """
    current = request.user
    if forget_device and everywhere_here:
        # A shared computer: no trust, and no names left on the login page.
        known_accounts.forget_all(request)
        devices.forget_sign_ins_here(request)
        if current.account_group_id is not None:
            devices.forget_this(request, current.account_group_id)
    available = signed_in_ids(request)
    password, unlocked = browser_lists(request)
    password = [i for i in password if i != current.pk]
    unlocked = [i for i in unlocked if i != current.pk]
    remaining = [i for i in available if i != current.pk]
    candidates = []
    if not everywhere_here and remaining and current.account_group_id is not None:
        candidates = list(
            BonkUser.objects.filter(pk__in=remaining, account_group_id=current.account_group_id)
        )
    if not candidates:
        bonk_session(request).clear()
        logout(request)
        return None
    # The most recently signed-in of the others still here.
    order = {pk: n for n, pk in enumerate(remaining)}
    target = max(candidates, key=lambda account: order[account.pk])
    _become(request, target, (password, unlocked))
    return target


def _become(request, target: BonkUser, lists: tuple[list[int], list[int]]) -> None:
    """Log the browser in as `target` (already proven: signed in here), keep
    which accounts are signed in here and how, and point the bonk.io
    identity at its most recently used link."""
    login(request, target)
    password, unlocked = lists
    # Most recently used last, in whichever list it's in: signing out of one
    # account goes back to the one used before it.
    if target.pk in password:
        password = [i for i in password if i != target.pk] + [target.pk]
    elif target.pk in unlocked:
        unlocked = [i for i in unlocked if i != target.pk] + [target.pk]
    _store(request, password, unlocked)
    point_bonk_identity(request, target)


def point_bonk_identity(request, user: BonkUser) -> None:
    """Point this browser's bonk.io identity (for Wear) at `user`'s most
    recently used link. Nothing of the previous account's identity carries
    over."""
    bonk = bonk_session(request)
    link = (
        BonkAccountLink.objects.select_related("bonk_player")
        .filter(user=user, active=True)
        .order_by("-updated_at")
        .first()
    )
    bonk.clear()
    if link is not None:
        bonk.store_identity(link.bonk_player.username, link.bonk_player.bonk_id)
        bonk.store_active_slot(link.active_slot)


class UnlockedAccountMiddleware:
    """If the browser is using an account the main unlocked, and this browser
    is no longer trusted for the group (removed in Settings, or unused for
    90 days), sign out of that account here (switching to another still
    signed in, if any)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            password, unlocked = browser_lists(request)
            unlocked_only = user.pk in unlocked and user.pk not in password
            if unlocked_only and not (
                user.account_group_id is not None
                and devices.is_trusted(request, user.account_group_id)
            ):
                sign_out(request, everywhere_here=False)
        return self.get_response(request)


# ── Membership ───────────────────────────────────────────────────────


@transaction.atomic
def join(owner: BonkUser, account: BonkUser) -> AccountGroup:
    """Put `account` in `owner`'s group (creating it with `owner` as main).

    Proven by a password login of `account` on the owner's browser. If
    `account` was in another group it leaves that one first (an account
    shared, sold or given away is moved by whoever can log in to it now). It
    takes the group's appearance.
    """
    owner = BonkUser.objects.select_for_update().get(pk=owner.pk)
    account = BonkUser.objects.select_for_update().get(pk=account.pk)
    if owner.account_group_id is not None and owner.account_group_id == account.account_group_id:
        return owner.account_group
    if account.account_group_id is not None:
        _leave(account)
    group = owner.account_group
    others = member_ids(owner)
    now = timezone.now()
    if group is None:
        group = AccountGroup.objects.create(main=owner)
        owner.account_group = group
        owner.joined_group_at = now
        owner.save(update_fields=["account_group", "joined_group_at"])
    account.account_group = group
    account.joined_group_at = now
    account.theme, account.seasonal, account.appearance_at = (
        owner.theme,
        owner.seasonal,
        owner.appearance_at,
    )
    account.save(
        update_fields=["account_group", "joined_group_at", "theme", "seasonal", "appearance_at"]
    )
    account_joined_group.send(sender=BonkUser, account=account, group=group, others=others)
    log_event(owner, "account_group_joined", account_id=account.pk, group_id=group.pk)
    logger.info("account joined a group | group=%s | account=%s", group.pk, account.pk)
    return group


def remove(request, account_id: int) -> None:
    """Take an account out of the active account's group.

    Allowed for the account itself, or for the main when it's signed in on
    this browser. Its favorites, votes and uploads go with it (they were
    always its own). If it's signed in here it's signed out here too.

    Raises:
        NotAllowed
    """
    current = request.user
    account = BonkUser.objects.filter(pk=account_id).first()
    if account is None or not same_group(current, account) or account.account_group_id is None:
        raise NotAllowed("That account isn't in your group.")
    group = current.account_group
    if account.pk != current.pk and not _main_here(request, group):
        main_name = BonkUser.objects.filter(pk=group.main_id).values_list("username", flat=True)
        raise NotAllowed(
            f"Only {main_name.first() or 'the main account'} can remove other accounts. "
            "Sign in to it on this browser first."
        )
    with transaction.atomic():
        _leave(BonkUser.objects.select_for_update().get(pk=account.pk))
    log_event(current, "account_group_left", account_id=account.pk, group_id=group.pk)
    if account.pk == current.pk:
        # Leaving the group: this browser stays signed in as it, alone.
        _store(request, [current.pk], [])
    else:
        password, unlocked = browser_lists(request)
        _store(
            request,
            [i for i in password if i != account.pk],
            [i for i in unlocked if i != account.pk],
        )
    current.refresh_from_db()


def make_main(request, account_id: int) -> None:
    """Make another account in the group its main. Allowed when the current
    main is signed in on this browser.

    Raises:
        NotAllowed
    """
    current = request.user
    account = BonkUser.objects.filter(pk=account_id).first()
    if account is None or not same_group(current, account) or account.account_group_id is None:
        raise NotAllowed("That account isn't in your group.")
    group = current.account_group
    if not _main_here(request, group):
        raise NotAllowed("Sign in to the current main account on this browser first.")
    AccountGroup.objects.filter(pk=group.pk).update(main=account)
    log_event(current, "account_group_main_changed", account_id=account.pk, group_id=group.pk)


def take_out(account: BonkUser) -> None:
    """Take `account` out of its group, whatever browser asks: when a
    password reclaims it from someone who claimed it by friend request
    (sign_in._reclaim). No-op for an account with no group."""
    with transaction.atomic():
        locked = BonkUser.objects.select_for_update().get(pk=account.pk)
        if locked.account_group_id is None:
            return
        group_id = locked.account_group_id
        _leave(locked)
    log_event(
        account, "account_group_left", account_id=account.pk, group_id=group_id, reclaimed=True
    )
    account.refresh_from_db()


def _leave(account: BonkUser) -> None:
    """Take a (locked) account out of its group: a new main if it was the
    main, and the group deleted when one member would be left."""
    group = AccountGroup.objects.select_for_update().get(pk=account.account_group_id)
    account.account_group = None
    account.joined_group_at = None
    account.save(update_fields=["account_group", "joined_group_at"])
    rest = list(BonkUser.objects.filter(account_group=group).order_by("joined_group_at", "pk"))
    if len(rest) <= 1:
        BonkUser.objects.filter(account_group=group).update(
            account_group=None, joined_group_at=None
        )
        group.delete()
        return
    if group.main_id == account.pk:
        group.main = rest[0]
        group.save(update_fields=["main"])


def show_on_profiles(request, show: bool) -> None:
    """Turn "Also plays as…" on or off for the active account's group.
    Allowed when the main is signed in on this browser.

    Raises:
        NotAllowed
    """
    group = request.user.account_group if request.user.account_group_id else None
    if group is None:
        raise NotAllowed("You have only one bonk.io account here.")
    if not main_signed_in_here(request):
        raise NotAllowed("Sign in to your main account on this browser first.")
    AccountGroup.objects.filter(pk=group.pk).update(show_on_profiles=show)
    log_event(request.user, "account_group_profiles", group_id=group.pk, shown=show)


def shown_alongside(user: BonkUser) -> list[str]:
    """For `user`'s public profile: the usernames of the other accounts in
    its group when the group shows them ("Also plays as…"), else []."""
    if user.account_group_id is None or not user.account_group.show_on_profiles:
        return []
    return [account.username for account in members(user) if account.pk != user.pk]


def trusted_browsers(request) -> list[dict]:
    """Settings: the group's trusted browsers (where its main signed in in
    the last 90 days), or [] for an account with no group."""
    if request.user.account_group_id is None:
        return []
    return devices.listed(request, request.user.account_group_id)


def remove_browser(request, device_id: int) -> None:
    """Settings: stop trusting one of the group's browsers. The accounts the
    main unlocked there are signed out there on its next visit. Needs the
    main signed in on this browser.

    Raises:
        NotAllowed
    """
    if request.user.account_group_id is None or not main_signed_in_here(request):
        raise NotAllowed("Sign in to your main account on this browser first.")
    if not devices.remove(request.user.account_group_id, device_id):
        raise NotAllowed("That browser isn't on the list.")
    _forget_cache(request)
    log_event(request.user, "trusted_device_removed", group_id=request.user.account_group_id)


def one_click_browsers(request) -> list[dict]:
    """Settings: where the account in use signs in with one click
    (devices.remembered_browsers, ADR 0025)."""
    return devices.remembered_browsers(request, request.user)
