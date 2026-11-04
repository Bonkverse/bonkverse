"""One-time migration of BonxBot's Discord skin submissions onto Bonkverse.

Owns: walking every BonxBot submission not yet on Bonkverse, importing it
through skins/skin_import.py (the editor renders from the stored skin code, so
BonkLeagues is only contacted for rows without one), and recording each outcome
back on the bot's row so the bot never re-sends it.
Used by: management command import_bonxbot_skins.
Does not own: BonxBot's SQL (integrations/bonxbot_db.py) or the import itself.

Safe to run again: rows already marked synced are skipped, and a link already
on Bonkverse comes back as the existing skin without rendering anything.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from integrations.bonxbot_db import BonxBotDB, BotSkin
from skins.events import log_event
from skins.skin_import import (
    ImportFailure,
    existing_skin,
    import_bonkleagues_skin,
    link_problem,
)

# Pause between rows that must be read from BonkLeagues (no stored code).
BONKLEAGUES_PAUSE_SECONDS = 2.0


@dataclass
class MigrationReport:
    counts: Counter = field(default_factory=Counter)
    retry_later: list[tuple[int, str]] = field(default_factory=list)  # (bot id, error)
    failed: list[tuple[int, str]] = field(default_factory=list)  # permanent

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def plan_row(row: BotSkin) -> str:
    """What a real run would do with this row, without rendering or writing anything."""
    link = (row.link or "").strip()
    problem = link_problem(link)
    if problem:
        return problem
    if existing_skin(link):
        return "duplicate"
    return "create_from_code" if (row.skin_code or "").strip() else "create_from_bonkleagues"


def migrate(
    db: BonxBotDB,
    *,
    dry_run: bool,
    limit: int | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
    sleep: Callable[[float], None] = time.sleep,
    importer=import_bonkleagues_skin,
) -> MigrationReport:
    report = MigrationReport()
    if not dry_run:
        db.ensure_sync_columns()
    rows = db.unsynced_skins(limit=limit)
    progress(f"{len(rows)} BonxBot submission(s) not on Bonkverse yet")

    for i, row in enumerate(rows, 1):
        if dry_run:
            report.counts[plan_row(row)] += 1
        else:
            _migrate_row(db, row, report, importer, sleep)
        if i % 25 == 0:
            progress(f"  {i}/{len(rows)}")
    return report


def _migrate_row(db, row, report, importer, sleep):
    has_code = bool((row.skin_code or "").strip())
    result = importer(row.link or "", row.name, row.creator, skin_code=row.skin_code)

    if result.error in ImportFailure.PERMANENT:
        db.mark_failed(row.id, result.error)
        report.counts[result.error] += 1
        report.failed.append((row.id, result.error))
    elif result.error:
        # Render/fetch/storage trouble: leave the row unsynced so the bot retries it.
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
            report.counts["created_from_code" if has_code else "created_from_bonkleagues"] += 1
        else:
            report.counts["duplicate"] += 1

    # Without a code the import read the link from BonkLeagues; space those calls out.
    was_duplicate = result.skin is not None and not result.created
    rejected_link = result.error in (ImportFailure.INVALID_LINK, ImportFailure.LINK_TOO_LONG)
    if not has_code and not was_duplicate and not rejected_link:
        sleep(BONKLEAGUES_PAUSE_SECONDS)
