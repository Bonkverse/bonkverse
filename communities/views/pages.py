"""The directory's pages: the server list, one server, and the submit form."""

from django.shortcuts import get_object_or_404, render

from core.ratelimits import limit

from .. import selectors
from ..models import DiscordServer


@limit("browse")
def server_list(request):
    query = request.GET.get("q", "").strip()
    tag_names = request.GET.getlist("tag")
    servers = list(selectors.listed_servers(query, tag_names))
    return render(
        request,
        "communities/server_list.html",
        {
            "servers": servers,
            "tag_filters": selectors.tag_filters(selectors.all_tags(), tag_names, query),
            "query": query,
            "active_tags": tag_names,
            "minutes_to_refresh": selectors.minutes_to_refresh(),
        },
    )


@limit("browse")
def server_detail(request, server_id):
    server = get_object_or_404(DiscordServer, id=server_id, status="active")
    snapshots = selectors.recent_snapshots(server)
    return render(
        request,
        "communities/server_detail.html",
        {"server": server, "growth": selectors.growth_chart(snapshots)},
    )


@limit("browse")
def submit_server_page(request):
    return render(request, "communities/submit_server.html", {"tags": selectors.all_tags()})
