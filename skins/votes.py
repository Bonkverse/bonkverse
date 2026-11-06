"""Up/down votes on skins, kept in step with the counters on the Skin row.

Owns: casting, switching and removing a vote, and the rule that a skin's
`upvotes`/`downvotes` always equal its SkinVote rows.
Does not own: the HTTP endpoint (skin_votes.py), favorites, or repairing
counters that drifted before this module existed (the audit_vote_counts
command).

Why the lock: the old view read `skin.upvotes`, changed it in Python and saved
it back. Two votes at the same moment both read the same number, so one was
lost. Now every vote on a skin takes that skin's row lock for the length of a
short transaction, and the counters change in SQL with F() expressions, so
concurrent votes are applied one after another.
"""

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count, F, Q
from django.db.models.functions import Greatest

from .models import Skin, SkinVote

UP = "up"
DOWN = "down"
DIRECTIONS = (UP, DOWN)

# Which Skin counter each vote direction counts toward.
_COUNTER_FOR = {UP: "upvotes", DOWN: "downvotes"}


@dataclass(frozen=True)
class VoteResult:
    """A skin's counters after a vote, and the voter's vote now (None if removed)."""

    upvotes: int
    downvotes: int
    current_vote: str | None


def cast_vote(user, skin: Skin, direction: str) -> VoteResult:
    """Apply a click on the up or down button for `user` on `skin`.

    Clicking the direction the user already voted removes the vote; clicking
    the other direction switches it; otherwise it adds one. The matching
    counters change in the same transaction.

    Args:
        user: a signed-in site account.
        skin: the skin being voted on (only its id is used).
        direction: "up" or "down".

    Returns:
        The skin's counters as stored after this vote, and the user's vote now.

    Raises:
        ValueError: `direction` is not "up" or "down".
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"invalid vote direction: {direction!r}")

    with transaction.atomic():
        # Serializes every vote on this skin until the transaction ends.
        Skin.objects.select_for_update().filter(id=skin.id).values_list("id", flat=True).get()

        existing = SkinVote.objects.filter(user=user, skin_id=skin.id).first()
        previous = existing.vote if existing else None
        current = None if previous == direction else direction

        if current is None:
            existing.delete()
        elif existing:
            existing.vote = current
            existing.save(update_fields=["vote"])
        else:
            SkinVote.objects.create(user=user, skin_id=skin.id, vote=current)

        changes = {}
        if previous:
            field = _COUNTER_FOR[previous]
            # Never below zero, even on a counter that drifted before this fix.
            changes[field] = Greatest(F(field) - 1, 0)
        if current:
            field = _COUNTER_FOR[current]
            changes[field] = F(field) + 1
        Skin.objects.filter(id=skin.id).update(**changes)

        upvotes, downvotes = (
            Skin.objects.filter(id=skin.id).values_list("upvotes", "downvotes").get()
        )

    return VoteResult(upvotes=upvotes, downvotes=downvotes, current_vote=current)


def recount_votes(skin_ids=None) -> list[tuple[int, int, int, int, int]]:
    """Find skins whose counters differ from their SkinVote rows.

    Args:
        skin_ids: limit the check to these skins; None checks every skin.

    Returns:
        (skin_id, stored_up, stored_down, real_up, real_down) for each skin
        whose stored counters are wrong, ordered by skin id.
    """
    skins = Skin.objects.all()
    if skin_ids is not None:
        skins = skins.filter(id__in=skin_ids)
    rows = (
        skins.annotate(
            real_up=Count("skinvote", filter=Q(skinvote__vote=UP)),
            real_down=Count("skinvote", filter=Q(skinvote__vote=DOWN)),
        )
        .exclude(upvotes=F("real_up"), downvotes=F("real_down"))
        .order_by("id")
        .values_list("id", "upvotes", "downvotes", "real_up", "real_down")
    )
    return list(rows)


def fix_vote_counts(drifted) -> int:
    """Set each skin's counters to the real counts from `recount_votes`.

    Each skin is re-counted under its row lock, so a vote arriving during the
    repair is not overwritten with an older number.

    Returns:
        How many skins were changed.
    """
    changed = 0
    for skin_id, *_ in drifted:
        with transaction.atomic():
            locked = Skin.objects.select_for_update().filter(id=skin_id).values_list("id")
            if not list(locked):  # evaluating it takes the lock
                continue  # deleted since it was counted
            real = SkinVote.objects.filter(skin_id=skin_id).aggregate(
                up=Count("id", filter=Q(vote=UP)),
                down=Count("id", filter=Q(vote=DOWN)),
            )
            changed += Skin.objects.filter(id=skin_id).update(
                upvotes=real["up"], downvotes=real["down"]
            )
    return changed
