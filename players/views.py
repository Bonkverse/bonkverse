from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from core.ratelimits import limit

from . import selectors, services
from .models import ProfileVisibility


@limit("browse")
def player_profile(request, username):
    """A player's public page: replay stats for anyone with registered
    replays, plus skins for Bonkverse users, minus what they chose to hide."""
    context = selectors.profile_page(username, request.user)
    if context is None:
        return render(request, "players/not_found.html", {"username": username}, status=404)
    return render(request, "players/profile.html", context)


@login_required
@limit("browse")
def my_replay_stats_partial(request):
    """The Replays tab on My Profile, loaded when the tab is first opened so
    the replay service never slows down the rest of the page."""
    return render(
        request, "players/partials/_replay_stats.html", selectors.own_replay_stats(request.user)
    )


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
