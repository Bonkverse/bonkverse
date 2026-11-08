"""Read-only queries for player profile pages.

A profile exists for anyone with registered replays, Bonkverse account or
not. A Bonkverse account adds skins and the visibility switches
(ProfileVisibility); the owner always sees everything on their own page.
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from integrations.replays import PlayerError, get_player_configured
from skins.selectors import favorites_of, skins_created_by

from . import charts
from .models import ProfileVisibility

SKINS_SHOWN = 12


def _cache_key(username):
    digest = hashlib.sha1(username.lower().encode("utf-8")).hexdigest()
    return f"players:profile:v1:{digest}"


def replay_profile(username):
    """(profile dict or None, error code or None), cached for a few minutes.

    "No such player" is cached too, so a missing name can't be used to make
    every request reach the replay service. Outages are not cached.
    """
    key = _cache_key(username)
    cached = cache.get(key)
    if cached is not None:
        return cached

    result = get_player_configured(username)
    value = (result.data, result.error)
    if result.error != PlayerError.UNAVAILABLE and result.error != PlayerError.NOT_CONFIGURED:
        cache.set(key, value, settings.PLAYER_PROFILE_CACHE_SECONDS)
    return value


def site_account(username):
    """The Bonkverse account for a bonk.io username, if there is one.
    Site accounts are named after their bonk.io username."""
    return get_user_model().objects.filter(username__iexact=username).order_by("id").first()


def visibility_for(user):
    """The user's switches, or the all-public defaults if they never saved any."""
    found = ProfileVisibility.objects.filter(user=user).first()
    return found or ProfileVisibility(user=user)


def _sections(visibility, is_owner):
    if visibility is None:
        return {field: True for field, _, _ in ProfileVisibility.SECTIONS}
    shown = visibility.as_dict()
    return {field: True for field in shown} if is_owner else shown


def profile_page(username, viewer):
    """Context for players/profile.html, or None when there's nothing to show
    (no replays and no Bonkverse account by that name)."""
    profile, error = replay_profile(username)
    account = site_account(username)
    if profile is None and account is None and error == PlayerError.NOT_FOUND:
        return None

    is_owner = bool(
        account and viewer.is_authenticated and viewer.username.lower() == account.username.lower()
    )
    visibility = visibility_for(account) if account else None
    shown = _sections(visibility, is_owner)

    context = {
        "username": (profile or {}).get("username") or (account.username if account else username),
        "account": account,
        "is_owner": is_owner,
        "shown": shown,
        "hidden_labels": [
            label
            for field, label, _ in ProfileVisibility.SECTIONS
            if visibility is not None and not getattr(visibility, field)
        ],
        "replays": charts.build(profile, settings.BONKVERSE_REPLAYS_URL) if profile else None,
        "replays_error": error,
        "replays_url": settings.BONKVERSE_REPLAYS_URL,
    }

    if account and shown["skins"]:
        context["skins"], context["skins_total"] = skins_created_by(account.username, SKINS_SHOWN)
    if account and shown["favorites"]:
        context["favorites"], context["favorites_total"] = favorites_of(account, SKINS_SHOWN)
    return context


def own_replay_stats(user):
    """Context for the Replays tab on My Profile: every section, no skins
    (the other tabs already show those)."""
    profile, error = replay_profile(user.username)
    visibility = visibility_for(user)
    return {
        "username": user.username,
        "is_owner": True,
        "shown": _sections(visibility, is_owner=True),
        "hidden_labels": [
            label
            for field, label, _ in ProfileVisibility.SECTIONS
            if not getattr(visibility, field)
        ],
        "replays": charts.build(profile, settings.BONKVERSE_REPLAYS_URL) if profile else None,
        "replays_error": error,
        "replays_url": settings.BONKVERSE_REPLAYS_URL,
    }
