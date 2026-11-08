"""Read-only queries for player profile pages.

A profile exists for anyone with registered replays, a Bonkverse account,
or a bonk.io account Bonkverse knows from friend lists. It is split into
tabs (Overview, Activity, Level, Maps & modes, People, Friends, Skins). A
Bonkverse account adds the Skins tab, Flash friends and the visibility
switches (ProfileVisibility): a hidden section's tab and Overview card
disappear for visitors; the owner always sees everything.
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Value, When
from django.db.models.functions import Lower
from django.utils import timezone

from integrations.replays import (
    PlayerError,
    get_player_configured,
    get_player_map_configured,
    level_distribution_configured,
    lookup_players_configured,
    search_players_configured,
)
from skins.pagination_utils import elided_page_range
from skins.selectors import (
    SKIN_SORTS,
    account_links_for,
    bonk_players_named,
    creator_stats,
    flash_friend_counts,
    decorate_skins_for_user,
    favorites_of,
    skins_created_by,
)

from skins.models import BonkAccountLink, BonkPlayer, FlashFriend, FlashFriendship, Friendship

from . import calculator, charts, search
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
    ("friends", "Friends", "friends", False),
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
    lookup_name = (profile or {}).get("username") or (account.username if account else username)
    bonk_player = bonk_players_named([lookup_name]).get(lookup_name.lower())
    if (
        profile is None
        and account is None
        and bonk_player is None
        and error == PlayerError.NOT_FOUND
    ):
        return None

    is_owner = bool(
        account and viewer.is_authenticated and viewer.username.lower() == account.username.lower()
    )
    visibility = visibility_for(account) if account else None
    saved = (
        visibility.as_dict() if visibility else {f: True for f, _, _ in ProfileVisibility.SECTIONS}
    )
    shown = {f: True for f in saved} if is_owner else saved
    name = (profile or {}).get("username") or (
        account.username if account else bonk_player.username if bonk_player else username
    )

    tabs = []
    for slug, label, section, needs_replays in TABS:
        if section and not shown[section]:
            continue
        if needs_replays and profile is None:
            continue
        if slug == "skins" and not (account and (shown["skins"] or shown["favorites"])):
            continue
        if slug == "friends" and not (bonk_player or account):
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
        "bonk_player": bonk_player,
        "account_age": calculator.account_age(bonk_player.bonk_id) if bonk_player else None,
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


def overview(base, viewer):
    profile, shown, links = base["profile"], base["shown"], base["links"]
    ctx = {}
    if shown["friends"] and any(t["slug"] == "friends" for t in base["tabs"]):
        ctx["friend_counts"] = friend_counts(base, viewer)
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
            level_card=calculator.level_card(
                profile["summary"].get("current_level"),
                xp=base["bonk_player"].xp if base["bonk_player"] else None,
            )
            if shown["level_history"]
            else None,
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


# ── Friends tab ──────────────────────────────────────────────────

FRIENDS_CAP = 5000  # per list sent to the page; bigger lists are cut


def _hidden_friend_lists(viewer):
    """BonkPlayer ids and lower usernames of members who hid their friend
    list (ProfileVisibility.friends), except the viewer: they're left out of
    other players' lists too, so their list can't be pieced back together."""
    hidden = ProfileVisibility.objects.filter(friends=False)
    if viewer.is_authenticated:
        hidden = hidden.exclude(user=viewer)
    users = list(hidden.values_list("user_id", "user__username"))
    ids = set(
        BonkAccountLink.objects.filter(user_id__in=[u for u, _ in users], active=True).values_list(
            "bonk_player_id", flat=True
        )
    )
    return ids, {name.lower() for _, name in users}


def friend_ids(player):
    """Ids of the BonkPlayers on `player`'s bonk.io friend list."""
    if player is None:
        return set()
    low = Friendship.objects.filter(player_low=player).values_list("player_high_id", flat=True)
    high = Friendship.objects.filter(player_high=player).values_list("player_low_id", flat=True)
    return set(low) | set(high)


def flash_names(user):
    """{lower name: (name, BonkPlayer or None)} of `user`'s imported Flash
    friends."""
    if user is None:
        return {}
    rows = FlashFriendship.objects.filter(user=user).select_related("flash_friend__bonk_player")
    return {
        r.flash_friend.name.lower(): (r.flash_friend.name, r.flash_friend.bonk_player) for r in rows
    }


def viewer_player(viewer):
    """The viewer's own bonk.io account, if they're signed in."""
    if not viewer.is_authenticated:
        return None
    link = (
        BonkAccountLink.objects.filter(user=viewer, active=True)
        .select_related("bonk_player")
        .order_by("-connected_at")
        .first()
    )
    if link:
        return link.bonk_player
    return bonk_players_named([viewer.username]).get(viewer.username.lower())


def _joined(bonk_id):
    age = calculator.account_age(bonk_id)
    return age["day"].strftime("%b %Y") if age else None


def friend_counts(base, viewer):
    """Small numbers for the Overview card: friends, Flash friends, mutual."""
    player, account = base["bonk_player"], base["account"]
    hidden_ids, hidden_names = _hidden_friend_lists(viewer)
    ids = friend_ids(player) - hidden_ids
    if hidden_names and ids:
        ids -= set(
            BonkPlayer.objects.annotate(lname=Lower("username"))
            .filter(id__in=ids, lname__in=hidden_names)
            .values_list("id", flat=True)
        )
    mine = viewer_player(viewer)
    is_self = mine is not None and player is not None and mine.pk == player.pk
    mutual = len(ids & friend_ids(mine)) if mine and not is_self else None
    flash = FlashFriendship.objects.filter(user=account).count() if account else 0
    return {"friends": len(ids), "flash": flash, "mutual": mutual}


def friends(base, viewer):
    """The Friends tab: bonk.io friends, Flash friends, and the ones the
    viewer has too. Names, join dates and counts go to the page as JSON for
    instant search; the first rows are also in the HTML."""
    player, account = base["bonk_player"], base["account"]
    mine = viewer_player(viewer)
    is_self = base["is_owner"] or (mine is not None and player is not None and mine.pk == player.pk)

    hidden_ids, hidden_names = _hidden_friend_lists(viewer)
    ids = friend_ids(player) - hidden_ids
    mine_ids = friend_ids(mine) if mine and not is_self else set()
    rows = (
        BonkPlayer.objects.filter(id__in=ids)
        .annotate(
            linked=Exists(BonkAccountLink.objects.filter(bonk_player=OuterRef("pk"), active=True))
        )
        .order_by(Lower("username"), "pk")
    )
    bonk_rows = []
    for p in rows[:FRIENDS_CAP]:
        if p.username.lower() in hidden_names:
            continue
        bonk_rows.append(
            {
                "n": p.username,
                "j": _joined(p.bonk_id),
                "id": p.bonk_id,
                "f": p.last_friend_count or 0,
                "m": bool(p.linked),
                "mu": p.id in mine_ids,
                "you": mine is not None and p.id == mine.id,
            }
        )

    theirs = flash_names(account)
    mine_flash = flash_names(viewer if viewer.is_authenticated else None) if not is_self else {}
    flash_rows = [
        {
            "n": name,
            "now": bp.username if bp and bp.username.lower() != name.lower() else None,
            "p": bool(bp),
            "mu": key in mine_flash,
        }
        for key, (name, bp) in sorted(theirs.items())[:FRIENDS_CAP]
    ]

    you_are_friends = mine is not None and not is_self and mine.id in ids
    return {
        "friend_data": {
            "bonk": bonk_rows,
            "flash": flash_rows,
            "viewer": mine.username if mine and not is_self else None,
        },
        "bonk_total": len(bonk_rows),
        "flash_total": len(flash_rows),
        "mutual_total": sum(r["mu"] for r in bonk_rows),
        "flash_mutual_total": sum(r["mu"] for r in flash_rows),
        "bonk_preview": [
            dict(r, url=charts.profile_path(r["n"]), shown=shown_name(r["n"]))
            for r in bonk_rows[:60]
        ],
        "flash_preview": [dict(r, shown=shown_name(r["n"])) for r in flash_rows[:60]],
        "has_flash": account is not None,
        "can_compare": mine is not None and not is_self,
        "you_are_friends": you_are_friends,
        "is_self": is_self,
        "synced": player is not None and (player.last_friend_count or bool(ids)),
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
    (replays, a Bonkverse account, or a bonk.io account from friend lists)."""
    has_profile = bool(stats) or member or bonk_player is not None
    age = calculator.account_age(bonk_player.bonk_id) if bonk_player else None
    return {
        "username": name,
        "shown_name": shown_name(name),
        "initials": name.strip()[:2].upper() or "?",
        "profile_url": charts.profile_path(name) if has_profile else None,
        "member": member,
        "level": calculator.sane_level((stats or {}).get("level")),
        "games": (stats or {}).get("games"),
        "bonk_id": bonk_player.bonk_id if bonk_player else None,
        "friends": bonk_player.last_friend_count if bonk_player else None,
        "joined": age,
        "flash_friends": flash_friends,
        "listed_by": listed_by,
    }


def shown_name(name):
    """A name as shown on a card: spaces that would otherwise vanish (at the
    ends, two in a row, or a name of only spaces) are drawn as "␣"."""
    if name != name.strip() or "  " in name or not name.strip():
        return name.replace(" ", "\u2423")
    return name


def _players_base(f):
    """BonkPlayers with `linked`, an exact name first when there is one."""
    qs = BonkPlayer.objects.annotate(
        linked=Exists(BonkAccountLink.objects.filter(bonk_player=OuterRef("pk"), active=True))
    )
    if f.text:
        exact = Q(username=f.text) if f.case else Q(username__iexact=f.text)
        qs = qs.annotate(
            exact=Case(When(exact, then=Value(0)), default=Value(1), output_field=IntegerField())
        )
        return qs.order_by("exact", "-linked", "-last_friend_count", "username")
    return qs.order_by("-linked", "-last_friend_count", "username")


def _flash_base(f):
    qs = FlashFriend.objects.select_related("bonk_player").annotate(listed_by=Count("friend_of"))
    if f.text:
        exact = Q(name=f.text) if f.case else Q(name__iexact=f.text)
        qs = qs.annotate(
            exact=Case(When(exact, then=Value(0)), default=Value(1), output_field=IntegerField())
        )
        return qs.order_by("exact", "-listed_by", "name")
    return qs.order_by("-listed_by", "name")


def _exact_replay_card(query, cards):
    """A card for the replay player named exactly `query` when no card has
    that name, so searching "." finds the player called "." first."""
    if not query or any(c["username"].lower() == query.lower() for c in cards):
        return None
    stats, _ = replay_lookup([query])
    row = (stats or {}).get(query.lower())
    if not row:
        return None
    name = row.get("username") or query
    return _card(name, stats=row, member=name.lower() in _accounts_named([name]))


def directory(get):
    """Context for players/directory.html: one search over Bonk players
    (synced from bonk.io friend lists), replay players and legacy flash
    friends, as cards that open player profiles. Advanced filters
    (players/search.py) narrow the Bonk players and flash friend views."""
    view = get.get("view")
    view = view if view in dict(DIRECTORY_VIEWS) else "all"
    page = get.get("page", 1)
    f = search.parse(get)
    query = f.text
    players = view != "flash"
    ctx = {
        "query": query,
        "view": view,
        "views": DIRECTORY_VIEWS,
        "cards": [],
        "page_obj": None,
        "replays_error": None,
        "filters": f,
        "advanced": view != "replays",
        "adv_active": f.active and view != "replays",
        "chips": f.chips(players=players) if view != "replays" else [],
        "form": _advanced_form(f, players=players),
        "base_qs": urlencode_qs(query, view, f.params() if view != "replays" else None),
        "clear_qs": urlencode_qs(query.strip(), view),
    }

    if view == "replays":
        query = query.strip()
        ctx["query"] = query
        if len(query) < 3:
            ctx["needs_query"] = True
            return ctx
        found, error = _cached(
            _cache_key("search", query), lambda: search_players_configured(query)
        )
        ctx["replays_error"] = error
        rows = found or []
        names = [r["username"] for r in rows]
        bonk = bonk_players_named(names)
        members = _accounts_named(names)
        ctx["cards"] = [
            _card(
                r["username"],
                stats=r,
                member=r["username"].lower() in members,
                bonk_player=bonk.get(r["username"].lower()),
            )
            for r in rows
        ]
        return ctx

    if view == "flash":
        qs = search.apply(_flash_base(f), f, "name", players=False)
        page_obj = Paginator(qs, DIRECTORY_PAGE_SIZE).get_page(page)
        names = [fr.bonk_player.username if fr.bonk_player else fr.name for fr in page_obj]
        stats, ctx["replays_error"] = replay_lookup(names)
        members = _accounts_named(names)
        ctx["cards"] = [
            _card(
                n,
                stats=(stats or {}).get(n.lower()),
                member=n.lower() in members,
                bonk_player=fr.bonk_player,
                listed_by=fr.listed_by,
            )
            for fr, n in zip(page_obj, names, strict=True)
        ]
        ctx.update(page_obj=page_obj, elided_range=elided_page_range(page_obj))
        return ctx

    qs = search.apply(_players_base(f), f, "username")
    page_obj = Paginator(qs, DIRECTORY_PAGE_SIZE).get_page(page)
    rows = list(page_obj)
    names = [p.username for p in rows]
    stats, ctx["replays_error"] = replay_lookup(names)
    links = account_links_for(rows)
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
        for p in rows
    ]
    if not f.active and page_obj.number == 1:
        pinned = _exact_replay_card(query, ctx["cards"])
        if pinned:
            ctx["cards"].insert(0, pinned)
            ctx["pinned"] = True
    ctx.update(page_obj=page_obj, elided_range=elided_page_range(page_obj))
    return ctx


def _advanced_form(f, *, players):
    """What the advanced-search form needs to show the current values."""
    year = timezone.now().year
    return {
        "matches": search.MATCHES,
        "kinds": [
            {"key": key, "label": label, "state": f.kinds.get(key, "")}
            for key, label, _ in search.KINDS
        ],
        "kind_states": search.KIND_STATES,
        "spaces": [{"key": k, "label": label, "on": k in f.spaces} for k, label in search.SPACES],
        "sorts": [
            (k, label) for k, label in search.SORTS if players or k not in search.PLAYER_ONLY_SORTS
        ],
        "years": list(range(year, search.FIRST_YEAR - 1, -1)),
        "players": players,
    }


def urlencode_qs(query, view, extra=None):
    params = {"view": view}
    if query:
        params["q"] = query
    params.update(extra or {})
    return urlencode(params)


# ── XP & Level calculator ────────────────────────────────────────

DISTRIBUTION_CACHE_SECONDS = 6 * 60 * 60


def level_distribution():
    """(data, error): players per highest level seen in replays."""
    key = _cache_key("levels-distribution")
    found = cache.get(key)
    if found is not None:
        return found, None
    result = level_distribution_configured()
    if result.error:
        return None, result.error
    data = {"levels": result.data["levels"], "players": result.data.get("players")}
    cache.set(key, data, DISTRIBUTION_CACHE_SECONDS)
    return data, None


def calculator_player(username, viewer):
    """(summary, error) for the calculator: level, XP when known, account
    age, level history and recent pace. Error is "not_found", "private"
    (the player hides their level) or "unavailable"."""
    username = (username or "")[:100]
    base = profile_base(username, viewer) if username else None
    if base is None or base["profile"] is None:
        error = (base or {}).get("replays_error") or PlayerError.NOT_FOUND
        return None, "unavailable" if error == PlayerError.UNAVAILABLE else "not_found"
    if not base["shown"]["level_history"]:
        return None, "private"
    player = base["bonk_player"]
    return (
        calculator.player_summary(
            base["profile"],
            bonk_id=player.bonk_id if player else None,
            xp=player.xp if player else None,
        ),
        None,
    )
