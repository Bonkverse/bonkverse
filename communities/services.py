"""Submitting a Discord server to the directory.

Owns: reading the invite code out of what was typed, the directory's rules
(permanent invites only, one entry per server, only existing tags) and the
first snapshot. Does not own: the Discord API call
(integrations/discord_api.py), what people are told (views/submit.py), or
the hourly refresh (tasks.py).
"""

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from django.db import transaction
from django.utils import timezone

from integrations.discord_api import InviteError, fetch_invite
from skins.models import DiscordServer, DiscordServerSnapshot, DiscordTag


class SubmitOutcome(StrEnum):
    CREATED = "created"
    ALREADY_LISTED = "already_listed"
    MISSING_INVITE = "missing_invite"
    INVALID_FORMAT = "invalid_format"
    LOOKUP_FAILED = "lookup_failed"
    NO_SERVER = "no_server"
    NOT_PERMANENT = "not_permanent"


@dataclass(frozen=True)
class SubmitResult:
    outcome: SubmitOutcome
    server: DiscordServer | None = None
    # Set when outcome is LOOKUP_FAILED: why Discord's lookup failed.
    lookup_error: InviteError | None = None


def extract_invite_code(invite: str) -> str:
    """The invite code from a code or a discord.gg / discord.com link."""
    invite = invite.strip()
    if "://" not in invite:
        return invite
    path = (urlparse(invite).path or "").strip("/")
    parts = path.split("/")
    return parts[-1] if parts else ""


def submit_server(invite: str, tag_names: list[str]) -> SubmitResult:
    """Add the server behind `invite` to the directory.

    Looks the invite up on Discord; refuses expiring invites and invites that
    don't name a server; returns the existing entry if the server is already
    listed. On success, saves the server with its tags (unknown tag names are
    ignored) and a first snapshot of its counts.
    """
    invite = invite.strip()
    if not invite:
        return SubmitResult(SubmitOutcome.MISSING_INVITE)

    code = extract_invite_code(invite)
    if not code:
        return SubmitResult(SubmitOutcome.INVALID_FORMAT)

    lookup = fetch_invite(code)
    if lookup.error:
        return SubmitResult(SubmitOutcome.LOOKUP_FAILED, lookup_error=lookup.error)
    data = lookup.invite

    if not data.guild_id:
        return SubmitResult(SubmitOutcome.NO_SERVER)
    if data.expires_at is not None:
        return SubmitResult(SubmitOutcome.NOT_PERMANENT)

    with transaction.atomic():
        server, created = DiscordServer.objects.get_or_create(
            guild_id=data.guild_id,
            defaults={
                "invite_code": code,
                "invite_url": f"https://discord.gg/{code}",
                "name": data.name,
                "description": (data.description or "")[:4000],
                "icon_hash": data.icon_hash,
                "splash_hash": data.splash_hash,
                "member_count": data.member_count,
                "online_count": data.online_count,
                "expires_at": None,
                "status": DiscordServer.Status.ACTIVE,
                "last_fetched_at": timezone.now(),
            },
        )
        if not created:
            return SubmitResult(SubmitOutcome.ALREADY_LISTED, server=server)

        server.tags.set(DiscordTag.objects.filter(name__in=tag_names))
        DiscordServerSnapshot.objects.create(
            server=server,
            member_count=server.member_count,
            online_count=server.online_count,
        )

    return SubmitResult(SubmitOutcome.CREATED, server=server)
