"""The directory's pages: the server list, one server, and the submit form."""

from django.shortcuts import get_object_or_404, render

from core.ratelimits import limit
from skins.models import DiscordServer

from .. import selectors


@limit("browse")
def server_list(request):
    query = request.GET.get("q", "").strip()
    tag_names = request.GET.getlist("tag")
    return render(
        request,
        "communities/server_list.html",
        {
            "servers": selectors.listed_servers(query, tag_names),
            "tags": selectors.all_tags(),
            "query": query,
            "active_tags": tag_names,
            "next_refresh": selectors.next_refresh_at(),
        },
    )


@limit("browse")
def server_detail(request, server_id):
    server = get_object_or_404(DiscordServer, id=server_id, status="active")
    return render(
        request,
        "communities/server_detail.html",
        {"server": server, "snapshots": selectors.recent_snapshots(server)},
    )


@limit("browse")
def submit_server_page(request):
    return render(request, "communities/submit_server.html", {"tags": selectors.all_tags()})
