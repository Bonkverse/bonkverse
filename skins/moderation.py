"""Staff decisions about reported skins (the /moderation/ page).

Owns: the report queue (skins with open reports, their reports grouped on
each skin), the three decisions staff can make, and the record of each one
(ModerationDecision). Every decision closes all of the skin's open reports
in the same transaction, so nothing needs a second step afterwards.
Does not own: making a report (views/report.py), hiding reported skins from
featured places (Skin.objects.without_open_reports), or telling reporters
and creators what happened (not built yet; the decisions keep what it will
need: the reporters' ids, the old and new creator).
"""

from collections import Counter
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q

from core.validators import validate_bonk_username

from .models import CreatorSource, ModerationDecision, Skin, SkinReport

Action = ModerationDecision.Action

_OPEN = Q(reports__resolved=False)


def report_queue():
    """Skins with open reports, most reported first, then most recently reported.

    Each skin gets `open_report_count`, `last_reported_at`, `open_reports`
    (newest first, reporter loaded) and `reason_counts` ([(label, n)], most
    common first). Three queries however long the queue is.
    """
    open_reports = SkinReport.objects.filter(resolved=False).select_related("reporter")
    skins = list(
        Skin.objects.filter(id__in=open_reports.values("skin_id"))
        .annotate(
            open_report_count=Count("reports", filter=_OPEN),
            last_reported_at=Max("reports__created_at", filter=_OPEN),
        )
        .select_related("submitted_by")
        .prefetch_related(
            Prefetch(
                "reports",
                queryset=open_reports.order_by("-created_at"),
                to_attr="open_reports",
            )
        )
        .order_by("-open_report_count", "-last_reported_at")
    )
    labels = dict(SkinReport.REASON_CHOICES)
    for skin in skins:
        counts = Counter(report.reason for report in skin.open_reports)
        skin.reason_counts = [(labels.get(r, r), n) for r, n in counts.most_common()]
    return skins


def recent_decisions(limit=20):
    """The latest decisions, newest first, with who made them."""
    return ModerationDecision.objects.select_related("decided_by", "skin")[:limit]


def open_report_total() -> int:
    return SkinReport.objects.filter(resolved=False).count()


@dataclass(frozen=True)
class Outcome:
    decision: ModerationDecision
    message: str  # for the staff member, shown as a toast


def _close_reports(skin, by, action, note, **fields) -> ModerationDecision:
    """Record the decision and close every open report on `skin` under it.
    Call inside a transaction with the skin locked."""
    reports = list(SkinReport.objects.filter(skin=skin, resolved=False).order_by("id"))
    decision = ModerationDecision.objects.create(
        skin=skin,
        skin_name=skin.name,
        action=action,
        note=note.strip(),
        report_count=len(reports),
        reasons=[r.reason for r in reports],
        reporter_ids=sorted({r.reporter_id for r in reports if r.reporter_id}),
        decided_by=by,
        **fields,
    )
    SkinReport.objects.filter(id__in=[r.id for r in reports]).update(
        resolved=True, decision=decision
    )
    return decision


def _locked(skin_id) -> Skin:
    return Skin.objects.select_for_update().get(id=skin_id)


def dismiss(skin_id: int, *, by, note: str = "") -> Outcome:
    """Keep the skin as it is and close its reports."""
    with transaction.atomic():
        skin = _locked(skin_id)
        decision = _close_reports(skin, by, Action.DISMISSED, note)
    return Outcome(decision, f"Kept “{skin.name}” and closed {_reports(decision)}.")


def change_creator(skin_id: int, new_creator: str, *, by, note: str = "") -> Outcome:
    """Credit the skin to `new_creator` (a bonk.io name) and close its reports.

    The new creator also becomes the skin's owner (Skin.is_owned_by).
    Raises ValidationError for a name bonk.io wouldn't allow, or the same one.
    """
    new_creator = new_creator.strip()
    validate_bonk_username(new_creator)
    with transaction.atomic():
        skin = _locked(skin_id)
        old_creator = skin.creator or ""
        if old_creator.lower() == new_creator.lower():
            raise ValidationError(f"“{skin.name}” is already credited to {old_creator}.")
        decision = _close_reports(
            skin,
            by,
            Action.CREATOR_CHANGED,
            note,
            old_creator=old_creator,
            new_creator=new_creator,
        )
        skin.creator = new_creator
        skin.creator_source = CreatorSource.STAFF
        skin.save(update_fields=["creator", "creator_source"])
    return Outcome(
        decision,
        f"“{skin.name}” is now credited to {new_creator}; closed {_reports(decision)}.",
    )


def delete(skin_id: int, *, by, note: str = "") -> Outcome:
    """Delete the skin. Its reports go with it; the decision keeps the record."""
    with transaction.atomic():
        skin = _locked(skin_id)
        decision = _close_reports(skin, by, Action.DELETED, note, old_creator=skin.creator or "")
        skin.delete()
    return Outcome(decision, f"Deleted “{decision.skin_name}” ({_reports(decision)}).")


def _reports(decision) -> str:
    n = decision.report_count
    return f"{n} report" if n == 1 else f"{n} reports"


DECISIONS = {
    "dismiss": lambda skin_id, by, note, creator: dismiss(skin_id, by=by, note=note),
    "change_creator": lambda skin_id, by, note, creator: change_creator(
        skin_id, creator, by=by, note=note
    ),
    "delete": lambda skin_id, by, note, creator: delete(skin_id, by=by, note=note),
}
