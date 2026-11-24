import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.urls import reverse

from core.bonk import dbid, levels
from core.ratelimits import limit
from accounts.services import (
    account_rows,
    active_link,
    bonk_connection,
    disconnect_bonk,
    group_member_ids,
    main_signed_in_here,
    trusted_browsers,
    one_click_browsers,
    used_here_rows,
)
from skins.services import code_image

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
    return _tab(
        request,
        username,
        "",
        "players/overview.html",
        lambda b: selectors.overview(b, request.user),
    )


# Like /media/: browsers keep it an hour, Cloudflare a week. The avatar URL
# carries the skin's digest (selectors.skin_avatar_url), so a new skin is a
# new URL and nothing stale is served for it.
SKIN_AVATAR_CACHE_CONTROL = "public, max-age=3600, s-maxage=604800"


@limit("media")
def skin_avatar(request, username, kind):
    """A player's worn skin as a PNG (`kind` "png" or "thumbnail").

    404 when we know no skin for them or its image isn't ready (pages then
    show initials). The image is rendered on first request.
    """
    skin_code = selectors.worn_skin_codes([username]).get(username.lower())
    rel_path = code_image(skin_code, kind) if skin_code else None
    if rel_path is None:
        raise Http404("no skin image")
    try:
        image = open(os.path.join(settings.MEDIA_ROOT, rel_path), "rb")  # noqa: SIM115
    except FileNotFoundError:
        raise Http404("no skin image") from None
    response = FileResponse(image, content_type="image/png")
    response["Cache-Control"] = SKIN_AVATAR_CACHE_CONTROL
    return response


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
    which = request.GET.get("list")
    return _tab(
        request, username, "people", "players/people.html", lambda b: selectors.people(b, which)
    )


@limit("browse")
def friends(request, username):
    return _tab(
        request,
        username,
        "friends",
        "players/friends.html",
        lambda b: selectors.friends(b, request.user),
    )


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
    return render(request, "players/directory.html", selectors.directory(request.GET))


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
    return redirect(f"{reverse('players:players_directory')}?{selectors.urlencode_qs(query, view)}")


def _calculator_player(request):
    """Who the calculator loads first: `?player=`, else (signed in, with a
    linked bonk.io account) yourself, else nobody and the page starts from
    an example."""
    name = request.GET.get("player", "")[:100]
    if name or request.GET.get("goal"):
        return name
    mine = selectors.viewer_player(request.user)
    return mine.username if mine else ""


@limit("browse")
def xp_calculator(request):
    """The public XP & Level calculator. `?player=` and `?goal=` prefill it."""
    constants = {
        "xp_per_win": levels.XP_PER_WIN,
        "daily_cap": levels.DAILY_XP_CAP,
        "dbid_points": dbid.timeline(),
        "player_url": reverse("players:xp_calculator_player"),
        "levels_url": reverse("players:xp_calculator_levels"),
    }
    return render(
        request,
        "players/xp_calculator.html",
        {
            "constants": constants,
            "prefill_player": _calculator_player(request),
            "prefill_goal": request.GET.get("goal", "")[:6],
        },
    )


# "unavailable" (the replay site is down) is a 200 with ok: false, like
# levels.json: the calculator loads signed-in visitors' own account by
# itself, so an outage shouldn't log a server error for every such visit.
# The page says it can't load the player and starts from its example.
_PLAYER_ERROR_STATUS = {"not_found": 404, "private": 403, "unavailable": 200}


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
        # The switches save as they're flipped (players/js/profile_settings.js,
        # design review); the Save button is for browsers without scripts.
        if request.headers.get("Accept") == "application/json":
            return JsonResponse({"ok": True})
        messages.success(request, "Profile settings saved.")
        return redirect("players:profile_settings")

    visibility = selectors.visibility_for(request.user)
    sections = [
        {"field": field, "label": label, "help": help_text, "on": getattr(visibility, field)}
        for field, label, help_text in ProfileVisibility.SECTIONS
    ]
    return render(
        request,
        "players/settings.html",
        {
            "sections": sections,
            "bonk_connection": _bonk_connection(request),
            "group_accounts": account_rows(request),
            "trusted_browsers": trusted_browsers(request),
            "one_click_browsers": one_click_browsers(request),
            "used_here": used_here_rows(request),
            "group_shown_on_profiles": bool(
                request.user.account_group_id and request.user.account_group.show_on_profiles
            ),
        },
    )


@login_required
@require_POST
@limit("write")
def apply_visibility_to_all(request):
    """Settings: give every account in the group this account's profile
    switches. Needs the main signed in on this browser (RFC-0003 phase 5)."""
    if not main_signed_in_here(request):
        messages.error(request, "Sign in to your main account on this browser first.")
    else:
        changed = services.copy_visibility_to(request.user, group_member_ids(request.user))
        messages.success(request, f"Applied to your {changed} other bonk.io account(s).")
    return redirect("players:profile_settings")


def _bonk_connection(request) -> dict:
    """This browser's bonk.io connection, for the settings page (RFC-0003
    Part 2): "remembered" (stays connected, refreshed when Wear needs it),
    "connected" until a time (about a day after login), or "disconnected".
    From the account link, through the token broker (no secrets)."""
    return bonk_connection(active_link(request))


@login_required
@require_POST
@limit("write")
def disconnect_bonk_view(request):
    """Settings' "Disconnect": revoke the remember-me token on bonk.io and
    forget both tokens. The account stays linked; the next Wear asks for the
    password."""
    link = active_link(request)
    if link is not None:
        disconnect_bonk(link)
    messages.success(
        request, "Disconnected from bonk.io. Wear will ask for your password next time."
    )
    return redirect("players:profile_settings")
