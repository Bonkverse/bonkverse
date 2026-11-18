"""Discord accounts tied to bonk.io players, for BonxBot.

Owns: reading a Discord user's links (default first) and the one-time import
of LevelBot's verified accounts.
Does not own: verifying a Discord user's bonk.io account (BonxBot /link, plan
PR 5), the SQL against LevelBot's database (integrations/levelbot_db.py), or
player rows (players.services.player_named).

Plan: claude/plan-submissions-creator-and-discord-links (Bonkverse project).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from django.db import transaction

from core.discord import discord_id_or_none
from players.models import BonkPlayer
from players.services import player_named

from .models import DiscordLink, DiscordLinkSource

IMPORTED = "imported"
ALREADY_LINKED = "already_linked"
CLAIMED_BY_ANOTHER_DISCORD = "claimed_by_another_discord"
BAD_DISCORD_ID = "bad_discord_id"
BLANK_NAME = "blank_name"


def discord_links_for(discord_user_id: int) -> list[DiscordLink]:
    """A Discord user's bonk.io players, the default first, then oldest first."""
    return list(
        DiscordLink.objects.filter(discord_user_id=discord_user_id)
        .select_related("bonk_player")
        .order_by("-is_default", "created_at", "id")
    )


@dataclass
class LevelBotImportReport:
    counts: Counter = field(default_factory=Counter)  # one of the outcomes above per row
    new_players: int = 0  # names Bonkverse hadn't seen, added by name only


def import_levelbot_links(accounts, *, dry_run: bool = False) -> LevelBotImportReport:
    """Store LevelBot's verified accounts as DiscordLinks; safe to re-run.

    `accounts` is integrations.levelbot_db.LevelBotDB.accounts(): mains first,
    so a Discord user's LevelBot main becomes their default. A bonk.io player
    already tied to another Discord user keeps that link and the row is
    reported. A dry run does the same work and rolls it back, so its numbers
    are exact.
    """
    report = LevelBotImportReport()
    players_before = BonkPlayer.objects.count()
    with transaction.atomic():
        for account in accounts:
            report.counts[_import_one(account)] += 1
        report.new_players = BonkPlayer.objects.count() - players_before
        if dry_run:
            transaction.set_rollback(True)
    return report


def _import_one(account) -> str:
    discord_user_id = discord_id_or_none(account.discord_user_id)
    if discord_user_id is None:
        return BAD_DISCORD_ID
    if not (account.bonk_username or "").strip():
        return BLANK_NAME

    player = player_named(account.bonk_username)
    existing = DiscordLink.objects.filter(bonk_player=player).first()
    if existing:
        if existing.discord_user_id == discord_user_id:
            return ALREADY_LINKED
        return CLAIMED_BY_ANOTHER_DISCORD

    has_default = DiscordLink.objects.filter(
        discord_user_id=discord_user_id, is_default=True
    ).exists()
    DiscordLink.objects.create(
        discord_user_id=discord_user_id,
        bonk_player=player,
        source=DiscordLinkSource.LEVELBOT_IMPORT,
        is_default=not has_default,
        verified_at=account.verified_at,
    )
    return IMPORTED
