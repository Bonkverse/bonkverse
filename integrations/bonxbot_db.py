"""BonxBot's Postgres database (Railway project "General Discord Server Bots").

Owns: the SQL for reading BonxBot's `skins` table and recording, on each row,
which Bonkverse skin it became. Only the one-time migration uses this
(management command import_bonxbot_skins); live submissions arrive over HTTP
(skins/apis/bot_skins.py) and the bot records those itself.
Does not own: Bonkverse models or anything about importing a skin.

The sync columns are the same ones BonxBot adds on start
(BonxBot features/skins/bonkverse_sync.py); whichever runs first creates them.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg2

SYNC_COLUMNS_SQL = """
ALTER TABLE skins
    ADD COLUMN IF NOT EXISTS bonkverse_skin_id INTEGER,
    ADD COLUMN IF NOT EXISTS bonkverse_sync_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS bonkverse_sync_error TEXT,
    ADD COLUMN IF NOT EXISTS bonkverse_sync_failed BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS bonkverse_next_attempt_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS bonkverse_synced_at TIMESTAMP;
"""


@dataclass(frozen=True)
class BotSkin:
    id: int
    name: str | None
    link: str | None
    creator: str | None
    submitter_id: int | None
    skin_code: str | None
    final_url: str | None = None  # where BonkLeagues redirected; may carry the code


class BonxBotDB:
    def __init__(self, database_url: str):
        self._conn = psycopg2.connect(database_url)
        self._conn.autocommit = True

    def close(self):
        self._conn.close()

    def has_sync_columns(self) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.columns"
                " WHERE table_name = 'skins' AND column_name = 'bonkverse_skin_id'"
            )
            return cur.fetchone() is not None

    def ensure_sync_columns(self):
        with self._conn.cursor() as cur:
            cur.execute(SYNC_COLUMNS_SQL)

    def unsynced_skins(self, limit: int | None = None) -> list[BotSkin]:
        """Every submission not yet on Bonkverse, oldest first (all of them before the first sync)."""
        where = (
            "WHERE bonkverse_skin_id IS NULL AND NOT bonkverse_sync_failed"
            if self.has_sync_columns()
            else ""
        )
        sql = (
            "SELECT id, skin_name, skin_url, creator, submitter_id, skin_code, final_url"
            f" FROM skins {where} ORDER BY id"
        )
        params = ()
        if limit:
            sql += " LIMIT %s"
            params = (limit,)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return [BotSkin(*row) for row in cur.fetchall()]

    def mark_synced(self, bot_skin_id: int, bonkverse_skin_id: int):
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE skins
                SET bonkverse_skin_id = %s, bonkverse_synced_at = NOW(),
                    bonkverse_sync_error = NULL, bonkverse_next_attempt_at = NULL
                WHERE id = %s
                """,
                (bonkverse_skin_id, bot_skin_id),
            )

    def mark_failed(self, bot_skin_id: int, error: str):
        """A permanent failure: the bot will not retry this row."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE skins
                SET bonkverse_sync_failed = TRUE, bonkverse_sync_error = %s,
                    bonkverse_sync_attempts = bonkverse_sync_attempts + 1
                WHERE id = %s
                """,
                (error, bot_skin_id),
            )
