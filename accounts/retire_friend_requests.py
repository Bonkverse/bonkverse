"""Retiring friend-request sign-in (2026-11-27, ADR 0024 "Removed").

Owns: `retire()`, which undoes what a friend request may have given someone
who wasn't the owner:

- friend-request claims still waiting (or proven but not finished) end as
  refused, with the message old waiting pages show;
- accounts that came in by friend request and were never proven by their
  owner (a finished friend-request claim for one of their bonk.io ids, and no
  password or room-code proof on any link) leave any group they're in, lose
  their one-click sign-ins, and every session holding them ends (one pass
  over the live sessions).

The accounts themselves stay; the next sign-in needs a room code or the
password. Ending a session also signs that browser out of the other
accounts it held; that's the price of making sure the claimer is out.

Run with `manage.py retire_friend_requests` once the deploy has settled (old
processes still ran friend requests for that minute; migration 0014 only
refuses waiting claims). `--dry-run` first shows the counts. Safe to repeat:
the group and one-click changes are one transaction, and sessions are ended
after it.
"""

from __future__ import annotations

import logging

from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import groups
from .link_claims import FRIEND_REQUESTS_GONE
from .models import BonkAccountLink, BonkUser, LinkClaim, RememberedSignIn

logger = logging.getLogger(__name__)


def friend_only_ids() -> list[int]:
    """Accounts that came in by friend request and were never proven by
    their owner: a friend-request claim finished for a bonk.io id one of its
    active links holds, and no password or room-code proof on any of its
    links. One proof on any link clears the account: the owner proved it."""
    claimed_ids = set(
        LinkClaim.objects.filter(
            method=LinkClaim.FRIEND_REQUEST, status=LinkClaim.DONE, bonk_id__isnull=False
        ).values_list("bonk_id", flat=True)
    )
    linked = set(
        BonkAccountLink.objects.filter(
            active=True, bonk_player__bonk_id__in=claimed_ids
        ).values_list("user_id", flat=True)
    )
    proven = set(
        BonkAccountLink.objects.filter(
            Q(password_proven_at__isnull=False) | Q(room_proven_at__isnull=False)
        ).values_list("user_id", flat=True)
    )
    return sorted(linked - proven)


def retire(*, dry_run: bool = False) -> dict:
    """See the module docstring. Returns counts (no names). With `dry_run`,
    only counts what it would do."""
    ids = friend_only_ids()
    waiting = LinkClaim.objects.filter(
        method=LinkClaim.FRIEND_REQUEST, status__in=[LinkClaim.PENDING, LinkClaim.PROVEN]
    )
    grouped = BonkUser.objects.filter(pk__in=ids, account_group__isnull=False)
    if dry_run:
        return {
            "claims_to_refuse": waiting.count(),
            "accounts": len(ids),
            "in_groups": grouped.count(),
            "one_click": RememberedSignIn.objects.filter(user_id__in=ids).count(),
            "sessions": _end_sessions(set(ids), dry_run=True),
        }

    with transaction.atomic():
        claims = waiting.update(status=LinkClaim.REFUSED, problem=FRIEND_REQUESTS_GONE)
        taken_out = 0
        for account in grouped:
            groups.take_out(account)  # even as a main: the claimer may have built the group
            taken_out += 1
        one_click = RememberedSignIn.objects.filter(user_id__in=ids).delete()[0]
    # Outside the transaction: a long scan mustn't hold it, and what's done
    # above stays done even if this is interrupted (run it again).
    sessions = _end_sessions(set(ids))

    counts = {
        "claims_refused": claims,
        "accounts": len(ids),
        "taken_out_of_groups": taken_out,
        "one_click_ended": one_click,
        "sessions_ended": sessions,
    }
    logger.info("retire friend requests | %s", counts)
    return counts


def _end_sessions(ids: set[int], *, dry_run: bool = False) -> int:
    """End every live session holding one of `ids` (as the account in use,
    or signed in or unlocked on that browser: groups.SIGNED_IN_KEY,
    UNLOCKED_KEY), in one pass; each delete is its own write. The site uses
    Django's database sessions, so deleting the row ends the session."""
    if not ids:
        return 0
    ended = 0
    keys = {str(i) for i in ids}  # compared as text: however a list stored them
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        try:
            data = session.get_decoded()
        except Exception:  # an unreadable session can't hold the account
            continue
        held = {
            str(i)
            for key in (groups.SIGNED_IN_KEY, groups.UNLOCKED_KEY)
            for i in (data.get(key) or [])
        }
        if str(data.get("_auth_user_id")) in keys or held & keys:
            if not dry_run:
                session.delete()
            ended += 1
    return ended
