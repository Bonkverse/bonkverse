"""Retiring friend-request sign-in (2026-11-27, ADR 0024 "Removed").

Owns: `retire()`, which undoes what a friend request may have given someone
who wasn't the owner:

- friend-request claims still waiting (or proven but not finished) end as
  refused, with the message old waiting pages show;
- accounts proven only by friend request (no password or room-code proof on
  any link; every link from before friend requests was marked
  password-proven by migration 0010, and only password and room-code
  sign-ins make links now) leave any group they're in, lose their one-click
  sign-ins, and every session holding them ends (one pass over the live
  sessions).

The accounts themselves stay; the next sign-in needs a room code or the
password. Run by migration 0014, and again with `manage.py
retire_friend_requests` once the deploy has settled (old processes still ran
friend requests for that minute). Safe to repeat.
"""

from __future__ import annotations

import logging

from django.contrib.sessions.models import Session
from django.db.models import Q
from django.utils import timezone

from . import groups
from .link_claims import FRIEND_REQUESTS_GONE
from .models import BonkAccountLink, BonkUser, LinkClaim, RememberedSignIn

logger = logging.getLogger(__name__)


def friend_only_ids() -> list[int]:
    """Accounts with an active link and no owner's proof on any link."""
    linked = set(BonkAccountLink.objects.filter(active=True).values_list("user_id", flat=True))
    proven = set(
        BonkAccountLink.objects.filter(
            Q(password_proven_at__isnull=False) | Q(room_proven_at__isnull=False)
        ).values_list("user_id", flat=True)
    )
    return sorted(linked - proven)


def retire() -> dict:
    """See the module docstring. Returns counts (no names)."""
    claims = LinkClaim.objects.filter(
        method=LinkClaim.FRIEND_REQUEST, status__in=[LinkClaim.PENDING, LinkClaim.PROVEN]
    ).update(status=LinkClaim.REFUSED, problem=FRIEND_REQUESTS_GONE)

    ids = friend_only_ids()
    grouped = 0
    for account in BonkUser.objects.filter(pk__in=ids, account_group__isnull=False):
        groups.take_out(account)  # even as a main: the claimer may have built the group
        grouped += 1
    one_click = RememberedSignIn.objects.filter(user_id__in=ids).delete()[0]
    sessions = _end_sessions(set(ids))

    counts = {
        "claims_refused": claims,
        "accounts": len(ids),
        "taken_out_of_groups": grouped,
        "one_click_ended": one_click,
        "sessions_ended": sessions,
    }
    logger.info("retire friend requests | %s", counts)
    return counts


def _end_sessions(ids: set[int]) -> int:
    """End every live session holding one of `ids` (as the account in use,
    or signed in or unlocked on that browser: groups.SIGNED_IN_KEY,
    UNLOCKED_KEY), in one pass."""
    if not ids:
        return 0
    ended = 0
    keys = {str(i) for i in ids}
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        try:
            data = session.get_decoded()
        except Exception:  # an unreadable session can't hold the account
            continue
        held = {*(data.get(groups.SIGNED_IN_KEY) or []), *(data.get(groups.UNLOCKED_KEY) or [])}
        if str(data.get("_auth_user_id")) in keys or held & ids:
            session.delete()
            ended += 1
    return ended
