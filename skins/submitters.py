"""Who sent a skin in, kept apart from who made it.

Owns: the `Submission` record every skin-creating path hands over (upload form,
editor, BonxBot, the BonxBot migration), turning it into Skin fields, the rule
for crediting the BonkLeagues author or the submitter (`resolve_creator`), and
the backfill that fills those fields for skins added before they existed, from the
`skin_uploaded` events in the event log.
Does not own: asking the submitter (the upload page and BonxBot do), the event log itself (accounts), or storing skins
(skin_import.py, views/publish.py).

`creator` is the person credited with making the skin; the submitter is whoever
sent it to Bonkverse. They differ when someone uploads another player's skin.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from django.db import transaction

from accounts.models import UserEvent
from core.discord import discord_id_or_none
from skins.models import CreatorSource, Skin, SubmissionSource

BACKFILL_BATCH_SIZE = 500

# skin_uploaded events say where the upload came from in metadata["source"].
_EVENT_SOURCES = {
    "bonkleagues": SubmissionSource.WEBSITE,
    "editor": SubmissionSource.EDITOR,
    "discord": SubmissionSource.DISCORD,
}


@dataclass(frozen=True)
class Submission:
    """Who submitted a skin, from where, and where its creator name came from."""

    source: str  # a SubmissionSource value
    creator_source: str  # a CreatorSource value
    user: object | None = None  # the site account (website and editor)
    discord_user_id: int | None = None  # the Discord account (BonxBot)

    def skin_fields(self) -> dict:
        """Keyword arguments for Skin.objects.create()."""
        return {
            "submitted_by": self.user,
            "submitted_by_discord_id": self.discord_user_id,
            "submission_source": self.source,
            "creator_source": self.creator_source,
        }


@dataclass(frozen=True)
class CreatorChoice:
    """Who to credit as a skin's creator, and why."""

    creator: str
    source: str  # a CreatorSource value


def resolve_creator(submitter: str, bonkleagues_author: str | None, made_it: bool | None):
    """Who made a skin the submitter is sending in: a CreatorChoice, or None to ask them.

    No BonkLeagues author, or the submitter's own name (ignoring case but not
    spaces, like bonk.io), credits the submitter without asking. Another name needs an
    answer: made_it True credits the submitter, False the BonkLeagues author.
    """
    author = bonkleagues_author or ""
    if not author.strip() or author.casefold() == submitter.casefold() or made_it is True:
        return CreatorChoice(submitter, CreatorSource.SUBMITTER)
    if made_it is False:
        return CreatorChoice(author, CreatorSource.BONKLEAGUES)
    return None


@dataclass
class BackfillReport:
    counts: Counter = field(default_factory=Counter)  # by submission source, plus skips
    updated: int = 0  # skins changed (or, in a dry run, that would be)


def backfill_submitters(*, dry_run: bool = False) -> BackfillReport:
    """Fill submitter fields on legacy skins from their first skin_uploaded event.

    Touches only skins still marked `legacy`, so it is safe to re-run. Skins
    with no upload event (bulk imports, very old uploads) stay `legacy`.
    """
    report = BackfillReport()
    legacy_before = Skin.objects.filter(submission_source=SubmissionSource.LEGACY).count()
    pending = []
    for event in _first_upload_events():
        changes = _changes_from_event(event)
        if changes is None:
            report.counts["unknown_source"] += 1
            continue
        report.counts[changes["submission_source"]] += 1
        for name, value in changes.items():
            setattr(event.skin, name, value)
        pending.append(event.skin)
        if len(pending) >= BACKFILL_BATCH_SIZE:
            report.updated += _save_batch(pending, dry_run)
            pending = []
    report.updated += _save_batch(pending, dry_run)
    report.counts["still_legacy"] = legacy_before - report.updated
    return report


def _first_upload_events():
    """The earliest skin_uploaded event of each still-legacy skin."""
    events = (
        UserEvent.objects.filter(
            event_type="skin_uploaded",
            skin__submission_source=SubmissionSource.LEGACY,
        )
        .select_related("user", "skin")
        .order_by("skin_id", "created_at", "id")
    )
    seen = set()
    for event in events.iterator(chunk_size=BACKFILL_BATCH_SIZE):
        if event.skin_id in seen:
            continue
        seen.add(event.skin_id)
        yield event


def _changes_from_event(event) -> dict | None:
    """The submitter fields this upload event implies, or None if its source is unknown."""
    metadata = event.metadata or {}
    source = _EVENT_SOURCES.get(metadata.get("source"))
    if source is None:
        return None

    if source == SubmissionSource.DISCORD:
        return {
            "submission_source": source,
            "submitted_by_discord_id": discord_id_or_none(metadata.get("discord_user_id")),
            "creator_source": CreatorSource.AS_ENTERED,
        }

    user = event.user
    made_by_uploader = bool(user) and (event.skin.creator or "").lower() == user.username.lower()
    return {
        "submission_source": source,
        "submitted_by": user,
        "creator_source": CreatorSource.SUBMITTER if made_by_uploader else CreatorSource.AS_ENTERED,
    }


def _save_batch(skins, dry_run) -> int:
    if dry_run or not skins:
        return len(skins)
    with transaction.atomic():
        Skin.objects.bulk_update(
            skins,
            ["submission_source", "submitted_by", "submitted_by_discord_id", "creator_source"],
        )
    return len(skins)
