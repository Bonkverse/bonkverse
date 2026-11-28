"""Proving a bonk.io account with a code typed in a bot-hosted room
(ADR 0026, experimental).

Owns: starting a room-code claim (a code for this browser and a room from the
room service), checking what was typed in the room, and finishing a proven
claim: signing in, or adding the account. Works for any account, on
Bonkverse already or not: a room code is the owner's proof, like a password
(owner decision 2026-11-27; sign_in.sign_in_by_room_code).
Does not own: hosting the room (roombot/, via integrations/roombot.py),
signing in and grouping (sign_in.py, groups.py), friend-request claims
(link_claims.py holds what claims share: the per-name limit, name checks).

How it works:
1. The person types NAME. A claim is stored for CLAIM_MINUTES with a hash of
   a random code; the code itself is kept in this browser's session, the
   only place it's shown.
2. The room service opens a hidden bonk.io room and returns its link.
3. The person joins the room signed in as NAME and types the code.
4. While the waiting page polls, the claim is proven by a message whose code
   matches, typed by a player bonk.io's server reports as NAME and not a
   guest (a guest can use any name). The code ties the proof to this claim:
   unlike a friend request, a message typed for any other reason proves
   nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from integrations import roombot

from .events import log_event
from .link_claims import CLAIM_MINUTES, CLAIMS_PER_NAME_PER_HOUR, ClaimProblem, name_problem
from .models import LinkClaim
from .sign_in import (
    NeedsPassword,
    ProtectedSiteAccount,
    refuses_bonk_sign_in,
    sign_in_by_room_code,
    used_its_password,
)

logger = logging.getLogger(__name__)

SESSION_KEY = "bv_room_claims"  # {claim id: code}, this browser's claims
CODE_LENGTH = 6
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
MAX_WRONG_CODES = 3
EXPERIMENTAL_NOTE = "Signing in with a room code is experimental."


def configured() -> bool:
    return roombot.configured()


def name_key(name: str) -> str:
    """bonk.io names compared ignoring ASCII case only: equal keys mean the
    database's lower() agrees (casefold() would match lookalikes like "ſ")."""
    return "".join(ch.lower() if "A" <= ch <= "Z" else ch for ch in name)


def _normalize_code(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalnum())


def _code_hash(code: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), f"room-code:{_normalize_code(code)}".encode(), hashlib.sha256
    ).hexdigest()


def _session_codes(request) -> dict[int, str]:
    stored = request.session.get(SESSION_KEY, {})
    return {int(k): v for k, v in stored.items() if str(k).isdigit() and isinstance(v, str)}


def code_for(request, claim_id: int) -> str:
    """This browser's code for its claim, or "" if it isn't this browser's."""
    return _session_codes(request).get(claim_id, "")


def start(request, name: str, *, add: bool) -> LinkClaim:
    """Start a room-code claim for `name` from this browser.

    Raises:
        ClaimProblem: not set up, a bad name, too many claims for it, or no
            room available right now.
    """
    if not configured():
        raise ClaimProblem("Signing in with a room code isn't available right now.")
    name = (name or "").strip()
    problem = name_problem(name)
    if problem:
        raise ClaimProblem(problem)
    if not name.isascii():
        raise ClaimProblem("bonk.io usernames only use letters, numbers, spaces and underscores.")
    now = timezone.now()
    recent = LinkClaim.objects.filter(
        name_key=name.casefold(), started_at__gte=now - timedelta(hours=1)
    ).count()
    if recent >= CLAIMS_PER_NAME_PER_HOUR:
        raise ClaimProblem("Too many tries for that name. Wait a while and try again.")
    if refuses_bonk_sign_in(name):
        raise ClaimProblem(ProtectedSiteAccount.message)
    if add and used_its_password(name):
        raise ClaimProblem(NeedsPassword.message)

    opened = roombot.open_room_for(name)
    if opened.error == "busy":
        raise ClaimProblem(
            "All sign-in rooms are busy right now. "
            f"Try again in {max(1, -(-opened.retry_after // 60))} minute(s), "
            "or log in with a friend request or your password."
        )
    if opened.error or opened.room is None:
        raise ClaimProblem("Couldn't open a bonk.io room right now. Try again in a minute.")

    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    adding = add and request.user.is_authenticated
    claim = LinkClaim.objects.create(
        name=name,
        name_key=name.casefold(),  # the shared per-name limit counts by this
        purpose=LinkClaim.ADD if adding else LinkClaim.SIGN_IN,
        requested_by=request.user if adding else None,
        started_at=now,
        expires_at=now + timedelta(minutes=CLAIM_MINUTES),
        method=LinkClaim.ROOM_CODE,
        code_hash=_code_hash(code),
        room_id=opened.room.id,
        room_link=opened.room.link,
    )
    codes = _session_codes(request)
    codes = dict(list(codes.items())[-4:])
    codes[claim.pk] = code
    request.session[SESSION_KEY] = {str(k): v for k, v in codes.items()}
    logger.info("room claim started | claim=%s | purpose=%s", claim.pk, claim.purpose)
    return claim


def status(request, claim_id: int) -> dict:
    """What the waiting page shows, checking the room and finishing the
    claim when proven: {"status": "pending", "seconds_left"}, {"status":
    "done", "username"}, or {"status": "expired" | "refused", "message"}.

    Raises:
        ClaimProblem: not this browser's claim.
    """
    if not code_for(request, claim_id):
        raise ClaimProblem("That sign-in isn't from this browser.")
    claim = LinkClaim.objects.filter(pk=claim_id, method=LinkClaim.ROOM_CODE).first()
    if claim is None:
        raise ClaimProblem("That sign-in isn't from this browser.")
    now = timezone.now()

    if claim.status == LinkClaim.PENDING and claim.expires_at <= now:
        _end(claim, LinkClaim.EXPIRED, "", "Time's up. Start again on Bonkverse.")
    if claim.status == LinkClaim.PENDING:
        _check_room(claim)

    if claim.status == LinkClaim.PENDING:
        state = {"status": "pending", "seconds_left": int((claim.expires_at - now).total_seconds())}
        note = _wrong_code_note(claim.wrong_codes)
        if note:
            state["note"] = note
        return state
    if claim.status == LinkClaim.EXPIRED:
        return {
            "status": "expired",
            "message": claim.problem or f"{claim.name} didn't type the code in time. Try again.",
        }
    if claim.status == LinkClaim.REFUSED:
        return {"status": "refused", "message": claim.problem or "That didn't work. Try again."}
    if claim.status == LinkClaim.PROVEN:
        _finish(request, claim)
    return {"status": "done", "username": claim.bonk_name or claim.name}


def _check_room(claim: LinkClaim) -> None:
    """Read the room; prove, refuse or expire the claim from what was typed."""
    result = roombot.read(claim.room_id)
    if result.error == "unavailable":
        return  # try again on the next poll
    if result.error or result.room is None or not result.room.open:
        _end(claim, LinkClaim.EXPIRED, "", "The bonk.io room closed. Start again on Bonkverse.")
        return

    key = name_key(claim.name)
    wrong = 0
    for message in result.room.messages:
        # Only the claimed account, as bonk.io's server reports it, and never
        # a guest: a guest can call themselves anything.
        if message.guest or name_key(message.username) != key:
            continue
        if wrong >= MAX_WRONG_CODES:
            break  # tries used up: a later right code doesn't count
        if hmac.compare_digest(_code_hash(message.text), claim.code_hash):
            level = _level_of(result.room.players, key)
            proven = LinkClaim.objects.filter(pk=claim.pk, status=LinkClaim.PENDING).update(
                status=LinkClaim.PROVEN,
                bonk_name=message.username,
                bonk_level=level,
                proven_at=timezone.now(),
            )
            if proven:
                claim.status, claim.bonk_name = LinkClaim.PROVEN, message.username
                claim.bonk_level = level
                roombot.close(claim.room_id, "Code accepted! You're signed in on Bonkverse.")
                log_event(None, "room_code_claim_proven", claim_id=claim.pk)
            return
        wrong += 1

    if wrong > claim.wrong_codes:
        # The database decides who answers: of overlapping polls (two tabs,
        # a reload), only the one that moves the count says anything.
        moved = LinkClaim.objects.filter(pk=claim.pk, wrong_codes__lt=wrong).update(
            wrong_codes=wrong
        )
        claim.wrong_codes = wrong
        if moved and wrong < MAX_WRONG_CODES:
            # Answer in the room at once, where the person is typing. Best
            # effort: if roombot misses it, the waiting page still says it.
            roombot.say(claim.room_id, f"That's not the code. {_tries_left(wrong)}")
    if wrong >= MAX_WRONG_CODES:
        _end(
            claim,
            LinkClaim.REFUSED,
            "Too many wrong codes. Closing this room.",
            "Too many wrong codes were typed. Start again to get a new code.",
        )


def _level_of(players, key: str) -> int | None:
    """The level bonk.io's server shows for the (non-guest) player named
    `key`, or None if they've left the room or it isn't known."""
    for player in players:
        if not player.guest and name_key(player.username) == key and player.level > 0:
            return player.level
    return None


def _tries_left(wrong: int) -> str:
    left = MAX_WRONG_CODES - wrong
    return f"{left} {'try' if left == 1 else 'tries'} left."


def _wrong_code_note(wrong: int) -> str:
    """The waiting page's line after a wrong code, or ""."""
    if not wrong:
        return ""
    times = "once" if wrong == 1 else f"{wrong} times"
    return f"A wrong code was typed {times}. {_tries_left(wrong)} Check the code above."


def _end(claim: LinkClaim, status: str, room_message: str, problem: str) -> None:
    updated = LinkClaim.objects.filter(pk=claim.pk, status=LinkClaim.PENDING).update(
        status=status, problem=problem
    )
    if updated:
        claim.status, claim.problem = status, problem
        if claim.room_id:
            roombot.close(claim.room_id, room_message)


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
    try:
        user = sign_in_by_room_code(
            request, bonk_name=claim.bonk_name, add=adding, level=claim.bonk_level
        )
    except PermissionDenied as refused:  # ProtectedSiteAccount, NeedsPassword
        message = getattr(refused, "message", "") or "That didn't work. Try again."
        LinkClaim.objects.filter(pk=claim.pk).update(status=LinkClaim.REFUSED, problem=message)
        raise ClaimProblem(message) from refused
    log_event(user, "account_proven_by_room_code", claim_id=claim.pk, added=adding)
