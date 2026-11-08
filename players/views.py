from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from core.ratelimits import limit

from . import selectors, services
from .models import ProfileVisibility


def _tab(request, username, slug, template, build):
    """Render one profile tab: 404 for no such player, a "private" note when
    the viewer can't see this tab, otherwise the tab with `build(base)`."""
    base = selectors.profile_base(username, request.user, active=slug)
    if base is None:
        return render(request, "players/not_found.html", {"username": username}, status=404)
    if not base["tab_allowed"]:
        return render(request, "players/tab_unavailable.html", base)
    return render(request, template, {**base, **build(base)})


@limit("browse")
def overview(request, username):
    return _tab(request, username, "", "players/overview.html", selectors.overview)


@limit("browse")
def activity(request, username):
    return _tab(request, username, "activity", "players/activity.html", selectors.activity)


@limit("browse")
def level(request, username):
    return _tab(request, username, "level", "players/level.html", selectors.level)


@limit("browse")
def maps(request, username):
    mapid = request.GET.get("map")
    return _tab(request, username, "maps", "players/maps.html", lambda b: selectors.maps(b, mapid))


@limit("browse")
def people(request, username):
    return _tab(request, username, "people", "players/people.html", selectors.people)


@limit("browse")
def skins(request, username):
    q = request.GET
    return _tab(
        request,
        username,
        "skins",
        "players/skins.html",
        lambda b: selectors.skins(b, request.user, q.get("view"), q.get("sort"), q.get("page", 1)),
    )


@limit("search")
def directory(request):
    """Find a player: Bonk players, the most active replay players and legacy
    flash friends in one search, as cards that open their profiles."""
    q = request.GET
    context = selectors.directory(q.get("q"), q.get("view"), q.get("page", 1))
    return render(request, "players/directory.html", context)


@limit("browse")
def legacy_players_page(request):
    """The old Bonk Players page lives on as the directory."""
    return _redirect_to_directory(request, "all")


@limit("browse")
def legacy_flash_friends_page(request):
    """The old Flash Friends page lives on as the directory's flash view."""
    return _redirect_to_directory(request, "flash")


def _redirect_to_directory(request, view):
    query = request.GET.get("q", "")
    return redirect(f"{reverse('players_directory')}?{selectors.urlencode_qs(query, view)}")


@login_required
@limit("write", method="POST")
def profile_settings(request):
    """Switches for which profile sections other people can see."""
    if request.method == "POST":
        services.update_visibility(request.user, {k: True for k in request.POST})
        messages.success(request, "Profile settings saved.")
        return redirect("profile_settings")

    visibility = selectors.visibility_for(request.user)
    sections = [
        {"field": field, "label": label, "help": help_text, "on": getattr(visibility, field)}
        for field, label, help_text in ProfileVisibility.SECTIONS
    ]
    return render(request, "players/settings.html", {"sections": sections})
