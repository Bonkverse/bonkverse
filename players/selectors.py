"""Read-only queries for player profile pages.

A profile exists for anyone with registered replays, Bonkverse account or
not. It is split into tabs (Overview, Activity, Level, Maps & modes, People,
Skins). A Bonkverse account adds the Skins tab and the visibility switches
(ProfileVisibility): a hidden section's tab and Overview card disappear for
visitors; the owner always sees everything.
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models.functions import Lower
from django.utils import timezone

from integrations.replays import (
    PlayerError,
    get_player_configured,
    get_player_map_configured,
    lookup_players_configured,
    search_players_configured,
)
from skins.pagination_utils import elided_page_range
from skins.selectors import (
    SKIN_SORTS,
    account_links_for,
    bonk_players_matching,
    bonk_players_named,
    creator_stats,
    flash_friend_counts,
    flash_friends_matching,
    decorate_skins_for_user,
    favorites_of,
    skins_created_by,
)

from . import charts
from .models import ProfileVisibility

FEATURED_SKINS = 4
SKINS_PER_PAGE = 24

# (slug, label, the ProfileVisibility section that hides it, needs replays)
TABS = [
    ("", "Overview", None, False),
    ("activity", "Activity", "activity", True),
    ("level", "Level", "level_history", True),
    ("maps", "Maps & modes", "maps_and_modes", True),
    ("people", "People", "play_partners", True),
    ("skins", "Skins", None, False),
]


def _cache_key(*parts):
    # Hashed only to keep any username (spaces, symbols) a safe cache key.
    raw = "\x1f".join(str(p).lower() for p in parts)
    return "players:v2:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cached(key, fetch):
    """(data, error) from cache or `fetch()`. "Not found" is cached too, so a
    missing name can't make every request reach the replay service; outages
    are not."""
    found = cache.get(key)
    if found is not None:
        return found
    result = fetch()
    value = (result.data, result.error)
    if result.error not in (PlayerError.UNAVAILABLE, PlayerError.NOT_CONFIGURED):
        cache.set(key, value, settings.PLAYER_PROFILE_CACHE_SECONDS)
    return value


def replay_profile(username):
    return _cached(_cache_key("profile", username), lambda: get_player_configured(username))


def replay_map(username, mapid):
    return _cached(
        _cache_key("map", username, mapid), lambda: get_player_map_configured(username, mapid)
    )


def site_account(username):
    """The Bonkverse account for a bonk.io username, if there is one.
    Site accounts are named after their bonk.io username."""
    return get_user_model().objects.filter(username__iexact=username).order_by("id").first()


def visibility_for(user):
    """The user's switches, or the all-public defaults if they never saved any."""
    return ProfileVisibility.objects.filter(user=user).first() or ProfileVisibility(user=user)


def profile_base(username, viewer, active=""):
    """What every tab shares: who this is, what the viewer may see, the
    replay profile and the tab bar. None when there's no such player."""
    profile, error = replay_profile(username)
    account = site_account(username)
    if profile is None and account is None and error == PlayerError.NOT_FOUND:
        return None

    is_owner = bool(
        account and viewer.is_authenticated and viewer.username.lower() == account.username.lower()
    )
    visibility = visibility_for(account) if account else None
    saved = (
        visibility.as_dict() if visibility else {f: True for f, _, _ in ProfileVisibility.SECTIONS}
    )
    shown = {f: True for f in saved} if is_owner else saved
    name = (profile or {}).get("username") or (account.username if account else username)

    tabs = []
    for slug, label, section, needs_replays in TABS:
        if section and not shown[section]:
            continue
        if needs_replays and profile is None:
            continue
        if slug == "skins" and not (account and (shown["skins"] or shown["favorites"])):
            continue
        tabs.append(
            {
                "slug": slug,
                "label": label,
                "url": charts.profile_path(name, slug),
                "active": slug == active,
                "private": bool(section and not saved[section]),
            }
        )

    links = charts.ReplayLinks(settings.BONKVERSE_REPLAYS_URL)
    return {
        "username": name,
        "account": account,
        "is_owner": is_owner,
        "shown": shown,
        "hidden_labels": [label for f, label, _ in ProfileVisibility.SECTIONS if not saved[f]],
        "profile": profile,
        "replays_error": error,
        "summary": charts.summary(profile) if profile else None,
        "links": links,
        "all_replays_url": links.player_replays(name),
        "tabs": tabs,
        "active_tab": active,
        "tab_allowed": any(t["slug"] == active for t in tabs),
    }


def overview(base):
    profile, shown, links = base["profile"], base["shown"], base["links"]
    ctx = {}
    if profile:
        today = timezone.now().date()
        maps = profile.get("maps") or []
        ctx.update(
            sparkline=charts.sparkline(profile.get("days", [])) if shown["level_history"] else None,
            main_mode=charts.main_mode(profile.get("modes", []))
            if shown["maps_and_modes"]
            else None,
            home_map=(charts.map_rows(maps[:1], links) or [None])[0]
            if shown["maps_and_modes"]
            else None,
            heatmap=charts.heatmap(profile.get("days", []), today) if shown["activity"] else None,
            streaks=charts.streaks(profile.get("days", []), today) if shown["activity"] else None,
            partners=charts.people_rows(
                (profile.get("played_with") or [])[:4], links, base["username"]
            )
            if shown["play_partners"]
            else None,
            milestones=charts.milestones(
                profile,
                links,
                show_level=shown["level_history"],
                show_activity=shown["activity"],
            )[:5],
        )
    account = base["account"]
    if account and shown["skins"]:
        ctx["featured"] = list(skins_created_by(account.username, "top")[:FEATURED_SKINS])
        ctx["skins_total"] = skins_created_by(account.username).count()
    return ctx


def activity(base):
    profile = base["profile"]
    today = timezone.now().date()
    sessions = profile.get("sessions") or {}
    return {
        "heatmap": charts.heatmap(profile.get("days", []), today),
        "streaks": charts.streaks(profile.get("days", []), today),
        "sessions": {
            "count": sessions.get("count") or 0,
            "typical": charts.minutes_label(sessions.get("median_minutes")),
            "longest": charts.minutes_label(sessions.get("longest_minutes")),
        },
        "script_data": charts.activity_script_data(profile),
    }


def level(base):
    profile = base["profile"]
    return {
        "sparkline": charts.sparkline(profile.get("days", []), width=1000, height=280),
        "level_ups": charts.level_ups(profile, base["links"], limit=10),
        "script_data": charts.level_script_data(profile),
    }


def maps(base, mapid=None):
    profile, links = base["profile"], base["links"]
    rows = charts.map_rows(profile.get("maps") or [], links)
    selected = next((m for m in rows if m["mapid"] == mapid), rows[0] if rows else None)
    detail, detail_error = None, None
    if selected:
        data, detail_error = replay_map(base["username"], selected["mapid"])
        if data:
            detail = charts.map_detail(
                data, links, base["username"], int(profile["summary"]["games"])
            )
    return {
        "ring": charts.mode_ring(profile.get("modes") or []),
        "rooms": charts.room_split(profile.get("rooms")),
        "maps": rows,
        "selected": selected,
        "detail": detail,
        "detail_error": detail_error,
    }


def people(base):
    profile, links, name = base["profile"], base["links"], base["username"]
    return {
        "lists": [
            {
                "key": "with",
                "title": "Plays with",
                "unit": "replays",
                "rows": charts.people_rows(profile.get("played_with") or [], links, name),
                "empty": "No registered players seen together yet.",
            },
            {
                "key": "team",
                "title": "Teams with",
                "unit": "team games",
                "rows": charts.people_rows(profile.get("teammates") or [], links, name),
                "empty": "No team games with registered players yet.",
            },
            {
                "key": "rivals",
                "title": "Plays against",
                "unit": "games against",
                "rows": charts.people_rows(profile.get("rivals") or [], links, name),
                "empty": "No team games or 1v1s against registered players yet.",
            },
        ]
    }


def skins(base, viewer, view, sort, page):
    account, shown = base["account"], base["shown"]
    views = [v for v, ok in (("created", shown["skins"]), ("favorites", shown["favorites"])) if ok]
    view = view if view in views else views[0]
    sort = sort if sort in SKIN_SORTS else ("top" if view == "created" else "new")
    qs = (
        skins_created_by(account.username, sort)
        if view == "created"
        else favorites_of(account, sort)
    )
    page_obj = Paginator(qs, SKINS_PER_PAGE).get_page(page)
    decorate_skins_for_user(page_obj, viewer)
    return {
        "creator": creator_stats(account.username),
        "favorites_total": account.favorite_skins.count() if shown["favorites"] else None,
        "views": views,
        "view": view,
        "sort": sort,
        "sorts": [("top", "Most upvoted"), ("new", "Newest"), ("az", "A–Z")],
        "page_obj": page_obj,
        "elided_range": elided_page_range(page_obj),
        "base_qs": f"view={view}&sort={sort}",
    }


# ── Player directory (the "Players" page) ────────────────────────

DIRECTORY_PAGE_SIZE = 24
DIRECTORY_VIEWS = [
    ("all", "All players"),
    ("replays", "Most active"),
    ("flash", "Flash friends"),
]


def replay_lookup(names):
    """{lower name: {username, games, level}} for names with replays, cached
    per name set; {} (and error) when the replay site can't be reached."""
    names = sorted({n for n in names if n}, key=str.lower)
    return _cached(_cache_key("lookup", *names), lambda: lookup_players_configured(names))


def _accounts_named(names):
    lowered = {n.lower() for n in names}
    if not lowered:
        return set()
    return set(
        get_user_model()
        .objects.annotate(lname=Lower("username"))
        .filter(lname__in=lowered)
        .values_list("lname", flat=True)
    )


def _card(name, *, stats, member, bonk_player=None, flash_friends=None, listed_by=None):
    """One player card. It links to the profile only when there is one
    (replays or a Bonkverse account)."""
    has_profile = bool(stats) or member
    return {
        "username": name,
        "initials": name.strip()[:2].upper() or "?",
        "profile_url": charts.profile_path(name) if has_profile else None,
        "member": member,
        "level": (stats or {}).get("level") or None,
        "games": (stats or {}).get("games"),
        "bonk_id": bonk_player.bonk_id if bonk_player else None,
        "friends": bonk_player.last_friend_count if bonk_player else None,
        "flash_friends": flash_friends,
        "listed_by": listed_by,
    }


def directory(query, view, page):
    """Context for players/directory.html: one search over Bonk players
    (synced from bonk.io friend lists), replay players and legacy flash
    friends, as cards that open player profiles."""
    query = (query or "").strip()[:100]
    view = view if view in dict(DIRECTORY_VIEWS) else "all"
    ctx = {
        "query": query,
        "view": view,
        "views": DIRECTORY_VIEWS,
        "cards": [],
        "page_obj": None,
        "replays_error": None,
        "base_qs": urlencode_qs(query, view),
    }

    if view == "replays":
        if len(query) < 3:
            ctx["needs_query"] = True
            return ctx
        found, error = _cached(
            _cache_key("search", query), lambda: search_players_configured(query)
        )
        ctx["replays_error"] = error
        rows = found or []
        names = [r["username"] for r in rows]
        players = bonk_players_named(names)
        members = _accounts_named(names)
        ctx["cards"] = [
            _card(
                r["username"],
                stats=r,
                member=r["username"].lower() in members,
                bonk_player=players.get(r["username"].lower()),
            )
            for r in rows
        ]
        return ctx

    if view == "flash":
        page_obj = Paginator(flash_friends_matching(query), DIRECTORY_PAGE_SIZE).get_page(page)
        names = [f.bonk_player.username if f.bonk_player else f.name for f in page_obj]
        stats, ctx["replays_error"] = replay_lookup(names)
        members = _accounts_named(names)
        ctx["cards"] = [
            _card(
                n,
                stats=(stats or {}).get(n.lower()),
                member=n.lower() in members,
                bonk_player=f.bonk_player,
                listed_by=f.listed_by,
            )
            for f, n in zip(page_obj, names, strict=True)
        ]
        ctx.update(page_obj=page_obj, elided_range=elided_page_range(page_obj))
        return ctx

    page_obj = Paginator(bonk_players_matching(query), DIRECTORY_PAGE_SIZE).get_page(page)
    players = list(page_obj)
    names = [p.username for p in players]
    stats, ctx["replays_error"] = replay_lookup(names)
    links = account_links_for(players)
    flash = flash_friend_counts(links.values())
    members = _accounts_named(names)
    ctx["cards"] = [
        _card(
            p.username,
            stats=(stats or {}).get(p.username.lower()),
            member=p.linked or p.username.lower() in members,
            bonk_player=p,
            flash_friends=flash.get(links.get(p.id)),
        )
        for p in players
    ]
    ctx.update(page_obj=page_obj, elided_range=elided_page_range(page_obj))
    return ctx


def urlencode_qs(query, view):
    params = {"view": view}
    if query:
        params["q"] = query
    return urlencode(params)
