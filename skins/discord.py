# skins/discord.py

from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

from django_celery_beat.models import PeriodicTask

from .models import DiscordServer, DiscordTag


def server_list(request):
    q = request.GET.get("q", "").strip()
    tag_names = request.GET.getlist("tag")

    servers = DiscordServer.objects.filter(status="active")

    if q:
        servers = servers.filter(
            Q(name__icontains=q) |
            Q(description__icontains=q)
        )

    if tag_names:
        servers = servers.filter(tags__name__in=tag_names).distinct()

    servers = servers.order_by("-member_count")

    tags = DiscordTag.objects.all().order_by("category", "name")

    # 🔄 Get next refresh time from celery beat
    task = PeriodicTask.objects.filter(
        task="skins.tasks.refresh_discord_servers"
    ).first()

    next_refresh = None
    if task and task.last_run_at:
        next_refresh = task.last_run_at + timedelta(hours=1)

    return render(request, "skins/server_list.html", {
        "servers": servers,
        "tags": tags,
        "query": q,
        "active_tags": tag_names,
        "next_refresh": next_refresh,
    })



def server_detail(request, server_id):
    server = get_object_or_404(
        DiscordServer,
        id=server_id,
        status="active"
    )

    snapshots = server.snapshots.order_by("-recorded_at")[:30]

    return render(request, "skins/server_detail.html", {
        "server": server,
        "snapshots": snapshots[::-1],  # chronological
    })


def submit_server_page(request):
    tags = DiscordTag.objects.all().order_by("category", "name")
    return render(request, "skins/submit_server.html", {
        "tags": tags
    })
