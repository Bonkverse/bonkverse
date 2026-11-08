from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from core.bonk import dbid, levels
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


@limit("browse")
def xp_calculator(request):
    """The public XP & Level calculator. `?player=` and `?goal=` prefill it."""
    constants = {
        "xp_per_win": levels.XP_PER_WIN,
        "daily_cap": levels.DAILY_XP_CAP,
        "dbid_points": dbid.timeline(),
        "player_url": reverse("xp_calculator_player"),
        "levels_url": reverse("xp_calculator_levels"),
    }
    return render(
        request,
        "players/xp_calculator.html",
        {
            "constants": constants,
            "prefill_player": request.GET.get("player", "")[:100],
            "prefill_goal": request.GET.get("goal", "")[:6],
        },
    )


_PLAYER_ERROR_STATUS = {"not_found": 404, "private": 403, "unavailable": 502}


@limit("search")
def xp_calculator_player(request):
    """JSON for one player in the calculator: level, XP when known, account
    age, level history and recent pace."""
    data, error = selectors.calculator_player(request.GET.get("name", ""), request.user)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=_PLAYER_ERROR_STATUS[error])
    return JsonResponse({"ok": True, "data": data})


@limit("browse")
def xp_calculator_levels(request):
    """JSON: how many replay players have each level (for "higher than N%")."""
    data, error = selectors.level_distribution()
    if error:
        # 200, not 5xx: the spread is an optional extra on the page, which
        # says it can't load it and keeps working.
        return JsonResponse({"ok": False, "error": "unavailable"})
    response = JsonResponse({"ok": True, "data": data})
    response["Cache-Control"] = "public, max-age=3600"
    return response


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
