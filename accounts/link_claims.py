"""Proving a bonk.io account with a friend request (RFC-0003 phase 6).

Owns: starting a claim ("I own NAME"), checking the bot account's friend
requests while claims are pending, matching a request to a claim, and
finishing a proven claim in the browser that made it: signing in as the
account, or adding it to the signed-in person's accounts.
Does not own: the bot's bonk.io session (bot_account.py), signing in and
grouping (sign_in.py, groups.py).

How it works:
1. The person types NAME. A claim is stored for 10 minutes and remembered
   in this browser's session.
2. The page says: from NAME, send a friend request to the bot account.
3. Every 30 s the worker (tasks.check_link_claims) does one query; only if
   a claim is pending does it read the bot's requests (one friends.php for
   every claim).
4. A request from NAME sent after the claim started proves it: the claim
   gets bonk.io's id and spelling. The request is deleted, never accepted.
5. The browser polling the claim sees it proven and finishes it once.

The rules match BonxBot's /link (it checks the same bot account until phase
7): names compare ignoring case, not spaces; request dates are US Eastern;
each request proves at most one claim; matched requests are deleted at once
and unmatched ones once they're too old to prove anything, so fresh
requests meant for BonxBot are left alone. Two pending claims for one name
are both refused when the request arrives: there's no telling whose it was.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from integrations.bonk_api import FRIENDS_SCRIPT, BonkError, get_client, rate_limit_cooldowns

from . import bot_account
from .events import log_event
from .models import BonkAccountLink, BonkUser, LinkClaim
from .sign_in import sign_in_by_friend_request

logger = logging.getLogger(__name__)

CLAIM_MINUTES = 10
CLOCK_SLACK = timedelta(seconds=60)
# While bonk.io pauses Bonkverse's calls, nothing can read the bot's
# requests, so pending claims are kept until this long after the pause ends
# (a claim never runs out while it couldn't be checked).
PAUSE_GRACE = timedelta(minutes=5)
NAME_MAX_LENGTH = 64
# Claims for one name per hour, so nobody can keep a name busy.
CLAIMS_PER_NAME_PER_HOUR = 4
# BONK: friend request dates look like "2026-11-10 21:39:07" with no zone;
# US Eastern server time (confirmed with BonxBot, 2026-11-18).
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_ZONE = ZoneInfo("America/New_York")
# This browser's claims (ids), so only it can finish them.
SESSION_KEY = "bv_link_claims"


class ClaimProblem(Exception):
    """The claim can't be started or finished; `message` says why."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def name_key(name: str) -> str:
    """How bonk.io names are compared: case ignored, spaces kept."""
    return name.casefold()


def name_problem(name: str) -> str | None:
    """Why `name` can't be a bonk.io username, in words for the person."""
    if not name or not name.strip():
        return "Type your bonk.io username."
    if len(name) > NAME_MAX_LENGTH:
        return f"bonk.io usernames are at most {NAME_MAX_LENGTH} characters."
    if any(not ch.isprintable() for ch in name):
        return "That username has characters bonk.io doesn't allow."
    return None


# ── Starting and finishing (in the browser) ──────────────────────────


def checks_paused_for() -> int:
    """Seconds until the bot's requests can be read again: bonk.io is
    pausing Bonkverse's calls (a login pause stops every script,
    integrations/bonk_api.py). 0 when they can be read now."""
    return math.ceil(rate_limit_cooldowns.remaining(FRIENDS_SCRIPT))


def _hold_through_pause(now: datetime, paused: int) -> None:
    """Keep every pending claim until PAUSE_GRACE after the pause ends."""
    until = now + timedelta(seconds=paused) + PAUSE_GRACE
    LinkClaim.objects.filter(status=LinkClaim.PENDING, expires_at__lt=until).update(
        expires_at=until
    )


def _wait_text(seconds: int) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    return f"about {minutes} minute{'s' if minutes != 1 else ''}"


def already_on_site(*, name: str = "", bonk_id: int | None = None) -> bool:
    """Whether someone already uses this bonk.io account on Bonkverse: a site
    account with the name, or an active link to the name or the id.

    A friend request proves only that *someone* waiting on a claim for the
    name received a request from it, not that the sender started that claim
    (bonk.io's request carries no code). So it may only claim accounts no
    one has here yet; owned ones sign in with their password, or with one
    click on a browser they proved themselves on (ADR 0024, 2026-11-25).
    """
    match = Q()
    if bonk_id is not None:
        match |= Q(bonk_player__bonk_id=bonk_id)
    if name:
        match |= Q(bonk_player__username__iexact=name)
    if match and BonkAccountLink.objects.filter(match, active=True).exists():
        return True
    return bool(name) and BonkUser.objects.filter(username__iexact=name).exists()


def already_on_site_message(name: str) -> str:
    return (
        f"{name} is already on Bonkverse, so a friend request can't sign in to it. "
        "Log in with its bonk.io password, or choose it under \u201cChoose an account\u201d "
        "on a browser it used before."
    )


def start(request, name: str, *, add: bool) -> LinkClaim:
    """Start a claim for `name` from this browser. With `add`, the account
    joins the signed-in person's accounts when proven; otherwise the browser
    signs in as it.

    Raises:
        ClaimProblem: not set up, a bad name, or too many claims for it.
    """
    if not bot_account.configured():
        raise ClaimProblem("Signing in with a friend request isn't available right now.")
    name = (name or "").strip()
    problem = name_problem(name)
    if problem:
        raise ClaimProblem(problem)
    now = timezone.now()
    recent = LinkClaim.objects.filter(
        name_key=name_key(name), started_at__gte=now - timedelta(hours=1)
    ).count()
    if recent >= CLAIMS_PER_NAME_PER_HOUR:
        raise ClaimProblem("Too many tries for that name. Wait a while and try again.")
    if already_on_site(name=name):
        raise ClaimProblem(already_on_site_message(name))
    paused = checks_paused_for()
    if paused:
        # A request sent now couldn't be read until the pause ends, and
        # BonxBot (same bot account) deletes requests older than 11 minutes.
        raise ClaimProblem(
            "bonk.io is pausing Bonkverse's requests for "
            f"{_wait_text(paused)}. Try again then. It isn't anything you did."
        )
    adding = add and request.user.is_authenticated
    claim = LinkClaim.objects.create(
        name=name,
        name_key=name_key(name),
        purpose=LinkClaim.ADD if adding else LinkClaim.SIGN_IN,
        requested_by=request.user if adding else None,
        started_at=now,
        expires_at=now + timedelta(minutes=CLAIM_MINUTES),
    )
    request.session[SESSION_KEY] = _session_claims(request)[-4:] + [claim.pk]
    logger.info("link claim started | claim=%s | purpose=%s", claim.pk, claim.purpose)
    return claim


def status(request, claim_id: int) -> dict:
    """What the waiting page shows for this browser's claim, finishing it
    when proven: {"status": "pending", "seconds_left"}, {"status": "done",
    "username"}, or {"status": "expired" | "refused", "message"}.

    Raises:
        ClaimProblem: not this browser's claim.
    """
    if claim_id not in _session_claims(request):
        raise ClaimProblem("That link request isn't from this browser.")
    claim = LinkClaim.objects.filter(pk=claim_id).first()
    if claim is None:
        raise ClaimProblem("That link request isn't from this browser.")
    now = timezone.now()
    paused = checks_paused_for() if claim.status == LinkClaim.PENDING else 0
    if paused:
        _hold_through_pause(now, paused)
        claim.refresh_from_db(fields=["expires_at", "status"])
    if claim.status == LinkClaim.PENDING and claim.expires_at <= now:
        LinkClaim.objects.filter(pk=claim.pk, status=LinkClaim.PENDING).update(
            status=LinkClaim.EXPIRED
        )
        claim.status = LinkClaim.EXPIRED
    if claim.status == LinkClaim.PENDING:
        state = {"status": "pending", "seconds_left": int((claim.expires_at - now).total_seconds())}
        if paused:
            # The waiting page says checks resume in `paused` seconds.
            state["paused"] = paused
        return state
    if claim.status == LinkClaim.EXPIRED:
        return {
            "status": "expired",
            "message": f"No friend request from {claim.name} arrived in time. Try again.",
        }
    if claim.status == LinkClaim.REFUSED:
        return {"status": "refused", "message": claim.problem or "That didn't work. Try again."}
    if claim.status == LinkClaim.PROVEN and already_on_site(
        name=claim.bonk_name or claim.name, bonk_id=claim.bonk_id
    ):
        # Owned since the claim started (or under another name): the request
        # can't prove who's waiting here.
        problem = already_on_site_message(claim.bonk_name or claim.name)
        LinkClaim.objects.filter(pk=claim.pk, status=LinkClaim.PROVEN).update(
            status=LinkClaim.REFUSED, problem=problem
        )
        log_event(None, "friend_request_claim_refused", claim_id=claim.pk, reason="owned")
        return {"status": "refused", "message": problem}
    if claim.status == LinkClaim.PROVEN:
        _finish(request, claim)
    return {"status": "done", "username": claim.bonk_name or claim.name}


def _finish(request, claim: LinkClaim) -> None:
    """Sign in as (or add) the proven account, exactly once."""
    adding = claim.purpose == LinkClaim.ADD
    if adding and (not request.user.is_authenticated or request.user.pk != claim.requested_by_id):
        raise ClaimProblem("Sign in again as the account you started from, then retry.")
    with transaction.atomic():
        taken = LinkClaim.objects.filter(pk=claim.pk, status=LinkClaim.PROVEN).update(
            status=LinkClaim.DONE
        )
    if not taken:
        return  # finished by another request from this browser
    user = sign_in_by_friend_request(
        request, bonk_id=claim.bonk_id, bonk_name=claim.bonk_name, add=adding
    )
    log_event(user, "account_proven_by_friend_request", claim_id=claim.pk, added=adding)


def claimed_name(claim_id: int) -> str:
    """The name a claim is for, as typed (for the waiting page)."""
    return LinkClaim.objects.filter(pk=claim_id).values_list("name", flat=True).first() or ""


def _session_claims(request) -> list[int]:
    return [i for i in request.session.get(SESSION_KEY, []) if isinstance(i, int)]


# ── Checking the bot's requests (on the worker) ──────────────────────


@dataclass(frozen=True)
class Request:
    bonk_id: int
    name: str
    sent_at: datetime | None


def request_time(date: str | None) -> datetime | None:
    """A friend request's date as an aware UTC datetime, or None."""
    if not date:
        return None
    try:
        local = datetime.strptime(date.strip(), DATE_FORMAT)
    except ValueError:
        return None
    return local.replace(tzinfo=DATE_ZONE).astimezone(dt_timezone.utc)


def match(claims: list[LinkClaim], requests: list[Request], now: datetime):
    """(proofs, refused claim ids, request ids to delete).

    proofs: [(claim, request)]. A claim takes the first request from its
    name sent at or after it started (less CLOCK_SLACK); each request proves
    at most one name. If several claims for one name are pending when its
    request arrives, all of them are refused. Requests are deleted once used,
    or once too old to prove any claim (a claim lasts CLAIM_MINUTES).
    """
    by_name: dict[str, list[LinkClaim]] = {}
    for claim in sorted(claims, key=lambda c: c.started_at):
        by_name.setdefault(claim.name_key, []).append(claim)

    proofs, refused, used = [], [], set()
    for key, waiting in by_name.items():
        first = waiting[0]
        for request in requests:
            if request.bonk_id in used or name_key(request.name) != key:
                continue
            if request.sent_at is None or request.sent_at < first.started_at - CLOCK_SLACK:
                continue
            used.add(request.bonk_id)
            if len(waiting) > 1:
                refused.extend(claim.pk for claim in waiting)
            else:
                proofs.append((first, request))
            break

    stale_before = now - timedelta(minutes=CLAIM_MINUTES) - CLOCK_SLACK
    delete = [
        r.bonk_id
        for r in requests
        if r.bonk_id in used or (r.sent_at or stale_before) <= stale_before
    ]
    return proofs, refused, delete


def check_pending() -> dict:
    """One pass of the worker's check. Returns counts for the log."""
    now = timezone.now()
    paused = checks_paused_for()
    if paused:
        # Nothing can be read: hold the claims instead of letting them run out.
        _hold_through_pause(now, paused)
        pending = LinkClaim.objects.filter(status=LinkClaim.PENDING).count()
        return {"pending": pending, "expired": 0, "skipped": "paused"}
    expired = LinkClaim.objects.filter(status=LinkClaim.PENDING, expires_at__lte=now).update(
        status=LinkClaim.EXPIRED
    )
    claims = list(LinkClaim.objects.filter(status=LinkClaim.PENDING))
    if not claims:
        return {"pending": 0, "expired": expired}

    token = bot_account.token()
    if not token:
        return {"pending": len(claims), "expired": expired, "skipped": "no_bot_session"}
    client = get_client()
    friends = client.get_friends(token)
    if not friends.ok and friends.error == BonkError.TOKEN_REJECTED:
        bot_account.forget_token()
        token = bot_account.token()
        friends = client.get_friends(token) if token else friends
    if not friends.ok:
        if friends.error == BonkError.RATE_LIMITED:
            # bonk.io just started a pause: hold the claims through it.
            _hold_through_pause(timezone.now(), checks_paused_for())
        return {"pending": len(claims), "expired": expired, "skipped": friends.error}

    requests = [
        Request(bonk_id=r.bonk_id, name=r.name, sent_at=request_time(r.date))
        for r in friends.requests
        if r.name
    ]
    proofs, refused, delete = match(claims, requests, now)
    for claim, request in proofs:
        LinkClaim.objects.filter(pk=claim.pk, status=LinkClaim.PENDING).update(
            status=LinkClaim.PROVEN,
            bonk_id=request.bonk_id,
            bonk_name=request.name,
            proven_at=now,
        )
    if refused:
        LinkClaim.objects.filter(pk__in=refused, status=LinkClaim.PENDING).update(
            status=LinkClaim.REFUSED,
            problem="Two people tried to link that name at the same time. Try again.",
        )
    for bonk_id in delete:
        result = client.delete_friend_request(token, bonk_id)
        if not result.ok:
            logger.warning("link check: couldn't delete a request (%s)", result.error)
    counts = {
        "pending": len(claims),
        "expired": expired,
        "proven": len(proofs),
        "refused": len(refused),
        "deleted": len(delete),
    }
    logger.info("link check | %s", " | ".join(f"{k}={v}" for k, v in counts.items()))
    return counts
