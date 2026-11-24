"""Adding accounts used on this browser to your group, without proving them
again (ADR 0025).

Owns: which accounts a signed-in person may add this way, adding them, and
the one-time "add them?" offer after a sign-in.

An account qualifies when it proved itself on this browser (password or
friend request) within ONE_CLICK_SIGN_IN_DAYS, the same proof that lets it
sign in here with one click, and it is in no group. One already in a group
(someone else's, or its own) needs a fresh password or friend request to
move, so a friend who once signed in on your computer can't be pulled out
of their group. The person ticks the accounts and confirms they're theirs;
nothing is added on its own.
"""

from __future__ import annotations

from django.db import transaction

from players import selectors as player_selectors

from . import devices, groups
from .events import log_event
from .models import BonkUser

# Session flag: a sign-in just happened, so the next page may offer once.
OFFER_KEY = "bv_offer_used_here"


def addable(request) -> list[BonkUser]:
    """Accounts the signed-in person may add from this browser, most
    recently proven first."""
    user = request.user
    ids = devices.proven_here_ids(request)
    if not ids:
        return []
    mine = set(groups.member_ids(user))
    found = {
        account.pk: account
        for account in BonkUser.objects.filter(pk__in=ids, account_group__isnull=True).exclude(
            pk__in=mine
        )
    }
    return [found[pk] for pk in ids if pk in found]


def rows(request) -> list[dict]:
    """`addable` for templates: id, username, worn-skin thumbnail."""
    return [
        {
            "id": account.pk,
            "username": account.username,
            "thumbnail": player_selectors.user_skin_avatars(account).get("thumbnail"),
        }
        for account in addable(request)
    ]


def add(request, account_ids: list[int]) -> list[BonkUser]:
    """Add the chosen accounts to the signed-in person's group. They count as
    signed in on this browser, so the switcher offers them at once.

    Raises:
        groups.NotAllowed: none of them may be added from here.
    """
    allowed = {account.pk: account for account in addable(request)}
    picked = [allowed[pk] for pk in dict.fromkeys(account_ids) if pk in allowed]
    if not picked:
        raise groups.NotAllowed("None of those accounts can be added from this browser.")
    owner = request.user
    with transaction.atomic():
        for account in picked:
            groups.join(owner, account)
    owner.refresh_from_db()
    groups.add_signed_in_here(request, [account.pk for account in picked])
    log_event(owner, "accounts_added_from_browser", count=len(picked))
    return picked


def offer_after_sign_in(request) -> None:
    """A sign-in (not "Add account") just happened: the next page may offer
    the accounts used here, once."""
    request.session[OFFER_KEY] = True


def take_offer(request) -> list[dict]:
    """The one-time offer for this page, or []. Clears it either way."""
    session = getattr(request, "session", None)
    if session is None or OFFER_KEY not in session:
        return []
    del session[OFFER_KEY]
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return []
    return rows(request)
