"""Keeping Bonkverse and the replay archive in step.

Bonkverse knows bonk.io account IDs (DBIDs) from friend lists and logins;
the replay archive knows every registered name that has played. Each run:

1. pull_replay_names: reads registered names from replays added since the
   last run (a batch of replays at a time, after a saved cursor) and adds
   the ones Bonkverse has never seen as BonkPlayers with no DBID, so the
   Players page finds them too. When a friend list or login later shows
   the DBID, that row gets it (players.friends_sync.adopt_replay_names).
2. push_player_ids: sends every BonkPlayer with a DBID that changed since
   the last run (name, DBID, estimated join day) to the replay site, for
   "A player's DBID" and "A player joined" replay searches.

Runs: hourly on the worker (players.tasks.sync_replays, every
REPLAY_SYNC_INTERVAL_SECONDS), and by hand with `python manage.py
sync_replays` (first run: the whole archive, in batches). Off unless
BONKVERSE_SYNC_TOKEN is set. HTTP lives in integrations/replay_sync.py.
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from core.bonk import dbid
from integrations.replay_sync import (
    MAX_PLAYERS_PER_POST,
    fetch_replay_names_configured,
    push_player_ids_configured,
)
from .models import BonkPlayer

from .models import SyncCursor

logger = logging.getLogger(__name__)

NAMES_CURSOR = "replay-names"
IDS_CURSOR = "player-ids"
LOCK_KEY = "players:replay-sync:lock"
LOCK_SECONDS = 30 * 60
NAMES_BATCH = 5000  # replays per request
MAX_NAME_LENGTH = 100


def _cursor(name):
    row = SyncCursor.objects.filter(name=name).first()
    return row.value if row else ""


def _save_cursor(name, value):
    SyncCursor.objects.update_or_create(name=name, defaults={"value": value})


def enabled():
    return bool(settings.BONKVERSE_SYNC_TOKEN and settings.BONKVERSE_REPLAYS_URL)


# ── Replay names in ──────────────────────────────────────────────────


def add_names(names):
    """Add BonkPlayers (no DBID) for names Bonkverse doesn't have yet,
    matching case-insensitively. Returns how many were added."""
    fresh = {}
    for name in names:
        if isinstance(name, str) and name and len(name) <= MAX_NAME_LENGTH:
            fresh.setdefault(name.lower(), name)
    if not fresh:
        return 0
    known = set(
        BonkPlayer.objects.annotate(lname=Lower("username"))
        .filter(lname__in=list(fresh))
        .values_list("lname", flat=True)
    )
    new = [
        BonkPlayer(bonk_id=None, username=name) for key, name in fresh.items() if key not in known
    ]
    BonkPlayer.objects.bulk_create(new, batch_size=1000)
    return len(new)


def pull_replay_names(max_batches=20):
    """Up to `max_batches` batches of replays after the saved cursor.
    Returns {"added", "batches", "done", "error"}."""
    added, batches, done, error = 0, 0, False, None
    after = _cursor(NAMES_CURSOR)
    while batches < max_batches:
        result = fetch_replay_names_configured(after, NAMES_BATCH)
        if result.error:
            error = result.error
            break
        data = result.data
        added += add_names(n.get("username") for n in data["names"] if isinstance(n, dict))
        after = data["next"]
        _save_cursor(NAMES_CURSOR, after)
        batches += 1
        if data.get("done"):
            done = True
            break
    return {"added": added, "batches": batches, "done": done, "error": error}


# ── DBIDs out ────────────────────────────────────────────────────────


def _row(player):
    est = dbid.estimate(player.bonk_id)
    return {
        "username": player.username,
        "dbid": player.bonk_id,
        "joined": est.day.isoformat() if est else None,
    }


def _parse_ids_cursor(raw):
    """("2026-11-08T21:00:00+00:00", 123) from "iso|pk"; (None, 0) for none."""
    try:
        when, pk = raw.split("|")
        return datetime.fromisoformat(when), int(pk)
    except (ValueError, AttributeError):
        return None, 0


def push_player_ids(max_batches=50):
    """Send BonkPlayers with a DBID that changed since the last run, oldest
    change first, MAX_PLAYERS_PER_POST at a time. The cursor is the last
    (updated_at, pk) sent, so rows sharing a timestamp aren't skipped.
    Returns {"sent", "batches", "done", "error"}."""
    sent, batches, error = 0, 0, None
    since, last_pk = _parse_ids_cursor(_cursor(IDS_CURSOR))
    while batches < max_batches:
        qs = BonkPlayer.objects.filter(bonk_id__gt=0)
        if since is not None:
            qs = qs.filter(Q(updated_at__gt=since) | Q(updated_at=since, pk__gt=last_pk))
        rows = list(qs.order_by("updated_at", "pk")[:MAX_PLAYERS_PER_POST])
        if not rows:
            return {"sent": sent, "batches": batches, "done": True, "error": None}
        result = push_player_ids_configured([_row(p) for p in rows])
        if result.error:
            error = result.error
            break
        sent += len(rows)
        batches += 1
        since, last_pk = rows[-1].updated_at, rows[-1].pk
        _save_cursor(IDS_CURSOR, f"{since.isoformat()}|{last_pk}")
        if len(rows) < MAX_PLAYERS_PER_POST:
            return {"sent": sent, "batches": batches, "done": True, "error": None}
    return {"sent": sent, "batches": batches, "done": False, "error": error}


# ── Running ──────────────────────────────────────────────────────────


def run(*, names=True, ids=True, max_batches=20):
    """One sync, unless another is already running. Returns what it did,
    or {"skipped": reason}."""
    if not enabled():
        return {"skipped": "BONKVERSE_SYNC_TOKEN or BONKVERSE_REPLAYS_URL isn't set"}
    if not cache.add(LOCK_KEY, timezone.now().isoformat(), LOCK_SECONDS):
        return {"skipped": "another sync is running"}
    try:
        out = {}
        if names:
            out["names"] = pull_replay_names(max_batches)
        if ids:
            out["ids"] = push_player_ids(max_batches * 2)
        logger.info("replay sync: %s", out)
        return out
    finally:
        cache.delete(LOCK_KEY)
