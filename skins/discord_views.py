"""Submitting a Discord server to the directory.

Owns: the submit endpoint, reading the invite from the form, the directory's
rules (permanent invites only, one entry per server), and the first snapshot.
Does not own: the Discord API call (integrations/discord_api.py) or the
hourly count refresh (skins/tasks.py).
"""

from urllib.parse import urlparse

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.ratelimits import limit
from integrations.discord_api import InviteError, fetch_invite

from .models import DiscordServer, DiscordServerSnapshot, DiscordTag

# What people see when the invite lookup fails, by InviteError code.
LOOKUP_FAILURE_MESSAGES = {
    InviteError.INVALID_CODE: "❌ Invalid Discord invite format.",
    InviteError.NOT_FOUND: "❌ Invalid or inaccessible Discord invite.",
    InviteError.RATE_LIMITED: "❌ Couldn't reach Discord right now. Try again in a minute.",
    InviteError.UNAVAILABLE: "❌ Couldn't reach Discord right now. Try again in a minute.",
}


def extract_invite_code(invite: str) -> str:
    invite = invite.strip()
    if "://" not in invite:
        return invite
    u = urlparse(invite)
    path = (u.path or "").strip("/")
    parts = path.split("/")
    return parts[-1] if parts else ""


@csrf_exempt
@require_POST
@limit("submit")
def submit_server(request):
    invite = request.POST.get("invite", "").strip()
    tags = request.POST.getlist("tags")

    # ---- Validation ----
    if not invite:
        messages.error(request, "❌ Discord invite link is required.")
        return redirect("submit_server")

    code = extract_invite_code(invite)
    if not code:
        messages.error(request, "❌ Invalid Discord invite format.")
        return redirect("submit_server")

    result = fetch_invite(code)
    if result.error:
        messages.error(request, LOOKUP_FAILURE_MESSAGES[result.error])
        return redirect("submit_server")
    data = result.invite

    if not data.guild_id:
        messages.error(request, "❌ Could not determine Discord server from invite.")
        return redirect("submit_server")

    if data.expires_at is not None:
        messages.error(request, "❌ Invite must be permanent (non-expiring).")
        return redirect("submit_server")

    # ---- Create server ----
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
            messages.warning(request, "⚠️ This Discord server has already been submitted.")
            return redirect(reverse("detail", kwargs={"server_id": server.id}))

        # Attach tags (only existing, controlled list)
        existing_tags = DiscordTag.objects.filter(name__in=tags)
        server.tags.set(existing_tags)

        # Initial snapshot
        DiscordServerSnapshot.objects.create(
            server=server,
            member_count=server.member_count,
            online_count=server.online_count,
        )

    messages.success(request, "✅ Discord server submitted successfully!")

    return redirect(reverse("detail", kwargs={"server_id": server.id}))
