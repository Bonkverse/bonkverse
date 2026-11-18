"""LevelBot's Postgres database (Railway project "General Discord Server Bots").

Owns: the SQL for reading LevelBot's verified Discord ↔ bonk.io accounts
(`discord_bonk_accounts`). Read only: Bonkverse never writes here. Only the
one-time import uses this (management command import_levelbot_links).
Does not own: Bonkverse models or deciding which links to keep
(accounts/discord_links.py).

LevelBot (repo Misterurias/levelbot, db.js) stores one row per verified
account: the first one a Discord user verified is `is_main`, later ones are
alts. `created_at` is rewritten each time an account is re-verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg2


@dataclass(frozen=True)
class LevelBotAccount:
    discord_user_id: str  # LevelBot keeps Discord ids as text; checked by the importer
    bonk_username: str
    is_main: bool
    verified_at: datetime | None


class LevelBotDB:
    def __init__(self, database_url: str):
        self._conn = psycopg2.connect(database_url)
        self._conn.set_session(readonly=True, autocommit=True)

    def close(self):
        self._conn.close()

    def accounts(self) -> list[LevelBotAccount]:
        """Every verified account, mains first, then oldest first."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT discord_user_id, bonk_username, is_main, created_at"
                " FROM discord_bonk_accounts"
                " ORDER BY discord_user_id, is_main DESC, created_at, bonk_username"
            )
            return [
                LevelBotAccount(str(discord_id), name, bool(main), created)
                for discord_id, name, main, created in cur.fetchall()
            ]
