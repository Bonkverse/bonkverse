"""Up/down votes on skins, kept in step with the counters on the Skin row.

Owns: casting, switching and removing a vote, the rule that a skin's
`upvotes`/`downvotes` always equal its SkinVote rows, and who may vote:
one vote per person (RFC-0003 phase 5: all the bonk.io accounts in a group
share one vote, and the latest wins) and bonk.io level 5 for a new vote.
Does not own: the HTTP endpoints (views/votes.py), favorites, or repairing
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
from django.utils import timezone

from accounts.services import bonk_level, group_member_ids

from .models import Skin, SkinVote

UP = "up"
DOWN = "down"
DIRECTIONS = (UP, DOWN)

# A new vote needs this bonk.io level on the account casting it, so freshly
# made accounts can't pile votes on a skin. Votes from before the rule stay.
MIN_VOTE_LEVEL = 5


class VoteNotAllowed(Exception):
    """This account may not cast a new vote; `message` says why."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def why_cant_vote(user) -> str | None:
    """Why `user` may not cast a new vote, or None if they may.

    An account whose level was never stored (signed in before Bonkverse kept
    XP) isn't blocked: every sign-in now stores it.
    """
    level = bonk_level(user)
    if level is not None and level < MIN_VOTE_LEVEL:
        return f"Reach level {MIN_VOTE_LEVEL} on bonk.io to vote. You're level {level}."
    return None


def group_vote(user, skin_ids) -> dict[int, str]:
    """{skin_id: "up" | "down"}: the vote of `user`'s group (theirs or another
    of their accounts') on each of `skin_ids`; the latest when there are
    several."""
    rows = (
        SkinVote.objects.filter(user_id__in=group_member_ids(user), skin_id__in=skin_ids)
        .order_by(F("voted_at").asc(nulls_first=True), "id")
        .values_list("skin_id", "vote")
    )
    return dict(rows)  # later rows overwrite earlier ones: the latest wins


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

    The vote belongs to the person: every account in `user`'s group shares
    it (RFC-0003 phase 5). Clicking the direction the group already voted
    removes the vote; clicking the other direction switches it; otherwise it
    adds one. Either way the vote ends up on `user`, and any other account
    in the group loses its vote on this skin, so the latest vote wins. The
    matching counters change in the same transaction.

    Args:
        user: a signed-in site account.
        skin: the skin being voted on (only its id is used).
        direction: "up" or "down".

    Returns:
        The skin's counters as stored after this vote, and the vote now.

    Raises:
        ValueError: `direction` is not "up" or "down".
        VoteNotAllowed: a new vote from an account below MIN_VOTE_LEVEL.
            Taking a vote back is always allowed.
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"invalid vote direction: {direction!r}")

    with transaction.atomic():
        # Serializes every vote on this skin until the transaction ends.
        Skin.objects.select_for_update().filter(id=skin.id).values_list("id", flat=True).get()

        rows = list(
            SkinVote.objects.filter(user_id__in=group_member_ids(user), skin_id=skin.id).order_by(
                F("voted_at").asc(nulls_first=True), "id"
            )
        )
        previous = rows[-1].vote if rows else None
        current = None if previous == direction else direction
        if current is not None:
            reason = why_cant_vote(user)
            if reason:
                raise VoteNotAllowed(reason)

        # Take every vote of the group off the counters, then add the one
        # that stays (if any), cast by `user` now.
        removed = {UP: 0, DOWN: 0}
        for row in rows:
            removed[row.vote] += 1
        SkinVote.objects.filter(pk__in=[row.pk for row in rows]).delete()
        if current:
            SkinVote.objects.create(
                user=user, skin_id=skin.id, vote=current, voted_at=timezone.now()
            )

        changes = {}
        for vote, field in _COUNTER_FOR.items():
            delta = (1 if current == vote else 0) - removed[vote]
            if delta < 0:
                # Never below zero, even on a counter that drifted before.
                changes[field] = Greatest(F(field) + delta, 0)
            elif delta > 0:
                changes[field] = F(field) + delta
        if changes:
            Skin.objects.filter(id=skin.id).update(**changes)

        upvotes, downvotes = (
            Skin.objects.filter(id=skin.id).values_list("upvotes", "downvotes").get()
        )

    return VoteResult(upvotes=upvotes, downvotes=downvotes, current_vote=current)


def merge_votes_into_group(account_id: int, others: list[int]) -> int:
    """After an account joined a group: where it and the group both voted on
    a skin, the group's vote stays and the joining account's goes (its old
    votes have no time to compare). Counters follow.

    Returns:
        How many of the joining account's votes were dropped.
    """
    if not others:
        return 0
    overlapping = SkinVote.objects.filter(
        user_id=account_id,
        skin_id__in=SkinVote.objects.filter(user_id__in=others).values("skin_id"),
    )
    dropped = 0
    for vote in overlapping.order_by("skin_id"):
        with transaction.atomic():
            Skin.objects.select_for_update().filter(id=vote.skin_id).values_list("id").get()
            if SkinVote.objects.filter(pk=vote.pk).delete()[0]:
                field = _COUNTER_FOR[vote.vote]
                Skin.objects.filter(id=vote.skin_id).update(**{field: Greatest(F(field) - 1, 0)})
                dropped += 1
    return dropped


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
