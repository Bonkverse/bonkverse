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
browser (`signed_in_ids`, kept in the session). The group's other accounts
are listed with "Sign in". That is the new-device guard in its simplest
form; trusted devices (phase 5, PR 3) will let any account unlock the group
on a device the group used before.

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

from .events import log_event
from .models import AccountGroup, BonkAccountLink, BonkUser

logger = logging.getLogger(__name__)

# Site account ids signed in on this browser, oldest first. Survives the
# session flush Django does when login() changes the user.
SIGNED_IN_KEY = "bv_signed_in"


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


def is_main(user: BonkUser) -> bool:
    """Whether `user` is its group's main account (an ungrouped account is
    its own main)."""
    return user.account_group_id is None or user.account_group.main_id == user.pk


def same_group(a: BonkUser, b: BonkUser) -> bool:
    return a.pk == b.pk or (
        a.account_group_id is not None and a.account_group_id == b.account_group_id
    )


def signed_in_ids(request) -> list[int]:
    """Ids of the accounts signed in on this browser, the active one included.
    Sessions from before groups have no list: just the active account."""
    if not request.user.is_authenticated:
        return []
    ids = [i for i in request.session.get(SIGNED_IN_KEY, []) if isinstance(i, int)]
    if request.user.pk not in ids:
        ids.append(request.user.pk)
    return ids


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


def after_login(request, previous: BonkUser | None, previous_ids: list[int], *, add: bool):
    """Call right after login() put `request.user` in this browser.

    `previous` and `previous_ids` are who was signed in before (login() may
    have flushed the session). With `add` ("Add account"), the new account
    joins `previous`'s group and the browser keeps every account it had; a
    plain login keeps them only when the new account is already in the same
    group, and otherwise starts over with just the new one.
    """
    user = request.user
    if add and previous is not None and previous.pk != user.pk:
        join(previous, user)
        user.refresh_from_db()
        previous.refresh_from_db()
    keep = previous is not None and same_group(previous, user)
    ids = [i for i in previous_ids if i != user.pk] if keep else []
    request.session[SIGNED_IN_KEY] = ids + [user.pk]


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
    ids = signed_in_ids(request)
    if target.pk not in ids:
        raise NotAllowed(f"Sign in to {target.username} on this browser first.")
    _become(request, target, ids)
    log_event(target, "account_switched", from_user_id=current.pk)
    return target


def sign_out(request, *, everywhere_here: bool) -> BonkUser | None:
    """Sign out of the active account, or of every account on this browser.

    Signing out of one account switches to the most recent other account
    still signed in here. Returns the account now active, or None.
    """
    ids = signed_in_ids(request)
    current = request.user
    remaining = [i for i in ids if i != current.pk]
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
    _become(request, target, remaining)
    return target


def _become(request, target: BonkUser, ids: list[int]) -> None:
    """Log the browser in as `target` (already proven: signed in here) and
    point the bonk.io identity at its most recently used link."""
    login(request, target)
    request.session[SIGNED_IN_KEY] = [i for i in ids if i != target.pk] + [target.pk]
    bonk = bonk_session(request)
    link = (
        BonkAccountLink.objects.select_related("bonk_player")
        .filter(user=target, active=True)
        .order_by("-updated_at")
        .first()
    )
    # Nothing of the previous account's bonk.io identity may carry over.
    bonk.clear()
    if link is not None:
        bonk.store_identity(link.bonk_player.username, link.bonk_player.bonk_id)
        bonk.store_active_slot(link.active_slot)


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
    if account.pk != current.pk and group.main_id not in signed_in_ids(request):
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
        request.session[SIGNED_IN_KEY] = [current.pk]
        current.refresh_from_db()
    else:
        request.session[SIGNED_IN_KEY] = [i for i in signed_in_ids(request) if i != account.pk]
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
    if group.main_id not in signed_in_ids(request):
        raise NotAllowed("Sign in to the current main account on this browser first.")
    AccountGroup.objects.filter(pk=group.pk).update(main=account)
    log_event(current, "account_group_main_changed", account_id=account.pk, group_id=group.pk)


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
