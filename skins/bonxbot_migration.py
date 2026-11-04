"""One-time migration of BonxBot's Discord skin submissions onto Bonkverse.

Owns: walking every BonxBot submission not yet on Bonkverse, finding its skin
code (the bot's `skin_code`, else the one in the `final_url` BonkLeagues
redirected to), importing it through skins/skin_import.py so the editor renders
it, and recording each outcome back on the bot's row so the bot never re-sends it.
Only rows with no code anywhere are read from BonkLeagues, paced, and
`skip_bonkleagues` leaves those for later instead.
Used by: management command import_bonxbot_skins.
Does not own: BonxBot's SQL (integrations/bonxbot_db.py) or the import itself.

Safe to run again: rows already marked synced are skipped, and a link already
on Bonkverse comes back as the existing skin without rendering anything.
"""

from __future__ import annotations

import functools
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from core.bonk import SkinCode
from integrations.bonxbot_db import BonxBotDB, BotSkin
from skins.events import log_event
from skins.skin_import import (
    ImportFailure,
    existing_skin,
    import_bonkleagues_skin,
    link_problem,
)

# Pause between rows that must be read from BonkLeagues (no code anywhere).
BONKLEAGUES_PAUSE_SECONDS = 2.0
# This many BonkLeagues fetch failures back to back means we're blocked or it's
# down, so the run stops rather than marching through every remaining row.
MAX_FETCH_FAILURES_IN_A_ROW = 5

# Where a row's skin code came from; also the suffix of its report outcome.
FROM_CODE = "code"
FROM_FINAL_URL = "final_url"
FROM_BONKLEAGUES = "bonkleagues"
SKIPPED_NEEDS_BONKLEAGUES = "skipped_needs_bonkleagues"


@dataclass
class MigrationReport:
    counts: Counter = field(default_factory=Counter)
    retry_later: list[tuple[int, str]] = field(default_factory=list)  # (bot id, error)
    failed: list[tuple[int, str]] = field(default_factory=list)  # permanent
    stopped_early: bool = False

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def code_for(row: BotSkin) -> tuple[str | None, str]:
    """(skin code, where it came from). No code means only BonkLeagues has it."""
    stored = (row.skin_code or "").strip()
    if stored:
        return stored, FROM_CODE
    from_url = SkinCode.from_bonkleagues_url(row.final_url)
    if from_url:
        return from_url.raw, FROM_FINAL_URL
    return None, FROM_BONKLEAGUES


def plan_row(row: BotSkin, *, skip_bonkleagues: bool = False) -> str:
    """What a real run would do with this row, without rendering or writing anything."""
    problem = link_problem(row.link)
    if problem:
        return problem
    if existing_skin(row.link):
        return "duplicate"
    _code, source = code_for(row)
    if source == FROM_BONKLEAGUES and skip_bonkleagues:
        return SKIPPED_NEEDS_BONKLEAGUES
    return f"create_from_{source}"


def migrate(
    db: BonxBotDB,
    *,
    dry_run: bool,
    limit: int | None = None,
    skip_bonkleagues: bool = False,
    pace_seconds: float = BONKLEAGUES_PAUSE_SECONDS,
    progress: Callable[[str], None] = lambda _msg: None,
    sleep: Callable[[float], None] = time.sleep,
    importer=import_bonkleagues_skin,
) -> MigrationReport:
    report = MigrationReport()
    pause = functools.partial(sleep, pace_seconds)
    if not dry_run:
        db.ensure_sync_columns()
    rows = db.unsynced_skins(limit=limit)
    progress(f"{len(rows)} BonxBot submission(s) not on Bonkverse yet")

    fetch_failures_in_a_row = 0
    for i, row in enumerate(rows, 1):
        if dry_run:
            report.counts[plan_row(row, skip_bonkleagues=skip_bonkleagues)] += 1
        else:
            error = _migrate_row(db, row, report, importer, pause, skip_bonkleagues)
            fetch_failures_in_a_row = (
                fetch_failures_in_a_row + 1 if error == ImportFailure.FETCH_FAILED else 0
            )
            if fetch_failures_in_a_row >= MAX_FETCH_FAILURES_IN_A_ROW:
                report.stopped_early = True
                progress(
                    f"Stopped: {fetch_failures_in_a_row} BonkLeagues fetches failed in a row"
                    " (likely blocked or down). Re-run later; finished rows are kept."
                )
                break
        if i % 25 == 0:
            progress(f"  {i}/{len(rows)}")
    return report


def _migrate_row(db, row, report, importer, pause, skip_bonkleagues) -> str | None:
    """Import one row and record the outcome; returns the import error, if any."""
    code, source = code_for(row)
    if source == FROM_BONKLEAGUES and skip_bonkleagues and not existing_skin(row.link):
        # Left unsynced on the bot: a later run without the flag picks it up.
        report.counts[SKIPPED_NEEDS_BONKLEAGUES] += 1
        return None

    result = importer(row.link or "", row.name, row.creator, skin_code=code)

    if result.error in ImportFailure.PERMANENT:
        db.mark_failed(row.id, result.error)
        report.counts[result.error] += 1
        report.failed.append((row.id, result.error))
    elif result.error:
        # Render/fetch/storage trouble: leave the row unsynced so it can be retried.
        report.counts["retry_later"] += 1
        report.retry_later.append((row.id, f"{result.error} {result.detail}".strip()))
    else:
        db.mark_synced(row.id, result.skin.id)
        if result.created:
            log_event(
                None,
                "skin_uploaded",
                skin=result.skin,
                source="discord",
                migrated=True,
                discord_user_id=row.submitter_id,
                bonx_skin_id=row.id,
            )
            report.counts[f"created_from_{source}"] += 1
        else:
            report.counts["duplicate"] += 1

    # Only a real BonkLeagues read is paced; duplicates and bad links never reach it.
    was_duplicate = result.skin is not None and not result.created
    rejected_link = result.error in (ImportFailure.INVALID_LINK, ImportFailure.LINK_TOO_LONG)
    if source == FROM_BONKLEAGUES and not was_duplicate and not rejected_link:
        pause()
    return result.error
