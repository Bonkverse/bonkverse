from urllib.parse import urlparse
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django_ratelimit.decorators import ratelimit

from .models import DiscordServer, DiscordTag, DiscordServerSnapshot
from .discord_invite import fetch_invite, parse_invite_payload


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
@ratelimit(key="ip", rate="7/hr", block=True)
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

    try:
        payload = fetch_invite(code)
    except Exception:
        messages.error(request, "❌ Invalid or inaccessible Discord invite.")
        return redirect("submit_server")

    data = parse_invite_payload(payload)

    if not data.get("guild_id"):
        messages.error(request, "❌ Could not determine Discord server from invite.")
        return redirect("submit_server")

    if data.get("expires_at") is not None:
        messages.error(request, "❌ Invite must be permanent (non-expiring).")
        return redirect("submit_server")

    # ---- Create server ----
    with transaction.atomic():
        server, created = DiscordServer.objects.get_or_create(
            guild_id=data["guild_id"],
            defaults={
                "invite_code": code,
                "invite_url": f"https://discord.gg/{code}",
                "name": data["name"],
                "description": (data["description"] or "")[:4000],
                "icon_hash": data["icon_hash"],
                "splash_hash": data["splash_hash"],
                "member_count": data["member_count"],
                "online_count": data["online_count"],
                "expires_at": None,
                "status": DiscordServer.Status.ACTIVE,
                "last_fetched_at": timezone.now(),
            },
        )

        if not created:
            messages.warning(
                request,
                "⚠️ This Discord server has already been submitted."
            )
            return redirect(
                reverse("detail", kwargs={"server_id": server.id})
            )

        # Attach tags (only existing, controlled list)
        existing_tags = DiscordTag.objects.filter(name__in=tags)
        server.tags.set(existing_tags)

        # Initial snapshot
        DiscordServerSnapshot.objects.create(
            server=server,
            member_count=server.member_count,
            online_count=server.online_count,
        )

    messages.success(
        request,
        "✅ Discord server submitted successfully!"
    )

    return redirect(
        reverse("detail", kwargs={"server_id": server.id})
    )
