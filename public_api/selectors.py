"""Read-only player data for the public API.

Owns: turning replay-site answers into the public v1 shapes, applying each
player's ProfileVisibility (a hidden Level section means no level in the
API either), and caching per player so a partner's sync of a few hundred
names doesn't reach the replay service each time.
Does not own: the replay numbers (the replay service computes them from
its own database), who may call the API (auth.py), or the profile pages
(players/), whose cached profile this reuses for level history.

Only replay data is published here. XP from a player's own bonk.io login
(BonkPlayer.xp) is what they gave Bonkverse, not other sites, so it stays
out of the public API.
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models.functions import Lower

from players.models import BonkPlayer

from integrations.replays import LOOKUP_MAX, PlayerError, lookup_players_configured
from players.calculator import account_age
from players.charts import profile_path
from players.models import ProfileVisibility
from players.selectors import replay_profile

from .models import ApiKey

MAX_USERNAME_LENGTH = 100
MAX_LOOKUP_NAMES = 250

FOUND = "found"
NOT_FOUND = "not_found"
PRIVATE = "private"
UNAVAILABLE = "unavailable"

_MISSING = {"missing": True}  # cached marker: the replay site has no such player


def _cache_key(username):
    digest = hashlib.sha256(username.lower().encode("utf-8")).hexdigest()
    return f"public_api:v1:lookup:{digest}"


def valid_username(raw) -> str | None:
    """bonk.io names aren't trimmed (leading/trailing spaces can be real)."""
    if not isinstance(raw, str) or not raw or len(raw) > MAX_USERNAME_LENGTH:
        return None
    return raw


def accounts_named(names) -> dict:
    """{lower name: BonkUser} for the Bonkverse accounts named like these."""
    lowered = {n.lower() for n in names}
    if not lowered:
        return {}
    users = (
        get_user_model()
        .objects.annotate(lname=Lower("username"))
        .filter(lname__in=lowered)
        .order_by("id")
    )
    found = {}
    for user in users:
        found.setdefault(user.lname, user)
    return found


def hidden_level_names(accounts: dict) -> set[str]:
    """Lowercased names whose owner hid their Level section."""
    hidden_user_ids = set(
        ProfileVisibility.objects.filter(
            user__in=list(accounts.values()), level_history=False
        ).values_list("user_id", flat=True)
    )
    return {name for name, user in accounts.items() if user.id in hidden_user_ids}


def bonk_accounts_named(names) -> dict:
    """{lower name: BonkPlayer} for bonk.io accounts Bonkverse knows (from
    friend lists and logins). The newest record wins if two share a name."""
    lowered = {n.lower() for n in names}
    if not lowered:
        return {}
    players = (
        BonkPlayer.objects.annotate(lname=Lower("username"))
        .filter(lname__in=lowered)
        .order_by("last_seen")
    )
    return {p.lname: p for p in players}


def _account(bonk_player) -> dict | None:
    """The bonk.io account: its ID (DBID, shown on public player cards too)
    and the day it was made, estimated from the ID."""
    if bonk_player is None:
        return None
    age = account_age(bonk_player.bonk_id)
    return {
        "dbid": bonk_player.bonk_id,
        "joined": age["day"].isoformat() if age else None,
        "joined_estimated": True,
    }


def _replay_rows(names) -> dict:
    """{lower name: replay lookup row | _MISSING | None (unavailable)}, from
    cache where possible; misses are fetched in chunks the replay site takes."""
    rows, misses = {}, []
    for name in names:
        cached = cache.get(_cache_key(name))
        if cached is None:
            misses.append(name)
        else:
            rows[name.lower()] = cached

    for start in range(0, len(misses), LOOKUP_MAX):
        chunk = misses[start : start + LOOKUP_MAX]
        result = lookup_players_configured(chunk)
        if result.error:
            for name in chunk:
                rows.setdefault(name.lower(), None)
            continue
        for name in chunk:
            value = result.data.get(name.lower(), _MISSING)
            cache.set(_cache_key(name), value, settings.PLAYER_PROFILE_CACHE_SECONDS)
            rows[name.lower()] = value
    return rows


def _level(row) -> dict:
    return {
        "value": row.get("level"),
        "peak": row.get("peak_level"),
        "seen_at": row.get("seen_at"),
        "seen_day": row.get("seen_day"),
        "estimated": bool(row.get("seen_estimated")),
        "source": "replays",
        "replay": row.get("last"),
    }


def player_entries(names, build_url) -> list[dict]:
    """One public entry per requested name, in the order asked, duplicates
    (ignoring case) dropped. `build_url(path)` makes absolute URLs."""
    seen, unique = set(), []
    for name in names:
        if name.lower() not in seen:
            seen.add(name.lower())
            unique.append(name)
    accounts = accounts_named(unique)
    hidden = hidden_level_names(accounts)
    bonk_players = bonk_accounts_named(unique)
    rows = _replay_rows(unique)

    entries = []
    for requested in unique:
        key = requested.lower()
        row = rows.get(key)
        account = accounts.get(key)
        entry = {
            "requested": requested,
            "username": requested,
            "status": FOUND,
            "level": None,
            "games": None,
            "account": _account(bonk_players.get(key)),
            "bonkverse_account": account is not None,
            "profile_url": None,
        }
        if row is None:
            entry["status"] = UNAVAILABLE
        elif row is _MISSING or row.get("missing"):
            entry["status"] = NOT_FOUND
            known = account or bonk_players.get(key)
            if known is not None:
                entry["username"] = known.username
                entry["profile_url"] = build_url(profile_path(known.username))
        else:
            entry["username"] = row.get("username") or requested
            entry["games"] = row.get("games")
            entry["profile_url"] = build_url(profile_path(entry["username"]))
            if key in hidden:
                entry["status"] = PRIVATE
            else:
                entry["level"] = _level(row)
        entries.append(entry)
    return entries


def level_history(username):
    """(data, error) for one player's level history. Error is NOT_FOUND,
    PRIVATE or UNAVAILABLE."""
    accounts = accounts_named([username])
    if username.lower() in hidden_level_names(accounts):
        return None, PRIVATE

    profile, error = replay_profile(username)
    if profile is None:
        return None, UNAVAILABLE if error == PlayerError.UNAVAILABLE else NOT_FOUND

    summary = profile.get("summary") or {}
    return {
        "username": profile.get("username") or username,
        "current_level": summary.get("current_level"),
        "peak_level": summary.get("peak_level"),
        # Each new highest level, when it was first seen in a replay. `at` is
        # exact only for live-collected replays; `day` is always set.
        "level_ups": [
            {
                "level": up.get("level"),
                "day": up.get("day"),
                "at": up.get("at"),
                "replay": {"cycle": up.get("cycle"), "id": up.get("id")},
            }
            for up in profile.get("level_ups") or []
        ],
        # Highest level seen on each day the player was in a replay.
        "days": [{"day": d.get("day"), "level": d.get("level")} for d in profile.get("days") or []],
    }, None


def keys_for(user):
    """The account's API keys for its developer portal list: active first,
    newest first."""
    return ApiKey.objects.filter(owner=user).order_by("-is_active", "-created_at")
