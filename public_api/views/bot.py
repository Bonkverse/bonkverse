"""Read endpoints for BonxBot, the Bonkverse Discord bot (/api/bot/).

Owns: GET skins/search/, skins/random/, skins/latest/, skins/<id>/, players/<username>/,
POST maps/decode/ and POST collection/ — what each returns to the bot. Same shared secret as skin
submissions (core/bot_auth.py), the public API's envelope (responses.py), and
one "bot" rate-limit tier for the bot's IP.
Does not own: search rules (skins/querysets.py), player data (selectors.py)
or decoding (integrations/map_decoder.py).

    {"ok": true, "data": {...}}  /  {"ok": false, "error": "skin_not_found"}

Errors: unauthorized 401, missing_query 400, invalid_username 400,
skin_not_found 404, player_not_found 404, search_timeout 503, invalid_after 400,
missing_code 400, map_rejected 422 (+ "detail"), upstream_unavailable 503;
collection/: missing_skin 400, invalid_username 400, skin_not_found 404, plus
the import codes (invalid_link 422, fetch_failed 502, render_failed 502, …).
"""

import functools
import json

from django.conf import settings
from django.db import OperationalError
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from accounts.services import ProtectedSiteAccount, log_event, site_account_for
from core.bonk import BonkUsername, InvalidUsername
from core.bot_auth import bot_authorized
from core.ratelimits import limit
from integrations.map_decoder import DecodeError, decode_map_configured
from skins.models import Skin
from skins.selectors import best_matches, random_skin
from skins.services import collect as collect_skin
from skins.services import discord_id_or_none

from .. import selectors
from ..responses import fail, ok

MAX_RESULTS = 10
MAX_QUERY = 100
MAX_MAP_CODE = 200_000
CACHE_SECONDS = 60


def bot_endpoint(*methods):
    """Token check, rate limit and allowed methods for a bot endpoint."""

    def decorator(view):
        @csrf_exempt  # token-authenticated, no cookies involved
        @limit("bot")
        @functools.wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                return fail("method_not_allowed", 405)
            if not bot_authorized(request):
                return fail("unauthorized", 401)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def skin_data(request, skin) -> dict:
    """What the bot shows for a skin. `skin` needs `fav_count` annotated."""
    png = f"{settings.MEDIA_URL}skins/{skin.id}.png"
    return {
        "id": skin.id,
        "name": skin.name,
        "creator": skin.creator,
        "url": request.build_absolute_uri(skin.get_absolute_url()),
        "image_url": request.build_absolute_uri(png),
        "upvotes": skin.upvotes,
        "downvotes": skin.downvotes,
        "favorites": getattr(skin, "fav_count", 0),
        "created_at": skin.created_at.isoformat(),
    }


@bot_endpoint("GET")
def search_skins(request):
    """GET skins/search/?q=tulip&limit=5 — the most relevant skins, best first."""
    query = request.GET.get("q", "").strip()[:MAX_QUERY]
    if not query:
        return fail("missing_query", 400)
    try:
        size = min(MAX_RESULTS, max(1, int(request.GET.get("limit", 5))))
    except ValueError:
        size = 5
    try:
        skins = best_matches(query, size)
    except OperationalError:
        return fail("search_timeout", 503)
    return ok(
        {"query": query, "skins": [skin_data(request, s) for s in skins]},
        cache_seconds=CACHE_SECONDS,
    )


LATEST_MAX = 25


@bot_endpoint("GET")
def latest(request):
    """GET skins/latest/?after=<id>&limit=10 — skins added after skin `after`,
    oldest first, for the bot's #skin-feed. Without `after`: just the newest
    skin's id, so a new feed starts from now instead of posting the backlog."""
    newest = Skin.objects.order_by("-id").values_list("id", flat=True).first() or 0
    after = request.GET.get("after")
    if after is None:
        return ok({"newest_id": newest, "skins": []})
    try:
        after = int(after)
        size = min(LATEST_MAX, max(1, int(request.GET.get("limit", 10))))
    except ValueError:
        return fail("invalid_after", 400)
    skins = Skin.objects.with_favorite_count().filter(id__gt=after).order_by("id")[:size]
    return ok(
        {
            "newest_id": newest,
            "skins": [skin_data(request, s) | {"source": s.submission_source} for s in skins],
        }
    )


@bot_endpoint("GET")
def random(request):
    """GET skins/random/ — any one skin."""
    skin = random_skin()
    if skin is None:
        return fail("skin_not_found", 404)
    return ok({"skin": skin_data(request, skin)})


@bot_endpoint("GET")
def skin(request, skin_id):
    """GET skins/<id>/ — one skin by its Bonkverse id."""
    found = Skin.objects.with_favorite_count().filter(id=skin_id).first()
    if found is None:
        return fail("skin_not_found", 404)
    return ok({"skin": skin_data(request, found)}, cache_seconds=CACHE_SECONDS)


@bot_endpoint("GET")
def player(request, username):
    """GET players/<username>/ — the public API's player entry, plus how many
    Bonkverse skins they're credited with."""
    name = selectors.valid_username(username)
    if name is None:
        return fail("invalid_username", 400)
    entry = selectors.player_entries([name], request.build_absolute_uri)[0]
    if entry["status"] == selectors.UNAVAILABLE:
        return fail("upstream_unavailable", 503)
    entry["skins"] = Skin.objects.made_by(entry["username"]).count()
    if entry["status"] == selectors.NOT_FOUND and not entry["skins"]:
        return fail("player_not_found", 404)
    return ok(entry, cache_seconds=CACHE_SECONDS)


def map_summary(decoded) -> dict:
    """The parts of a decoded map worth showing in Discord."""
    data = decoded if isinstance(decoded, dict) else {}
    meta = data.get("m") if isinstance(data.get("m"), dict) else {}
    physics = data.get("physics") if isinstance(data.get("physics"), dict) else {}

    def count(container, key):
        value = container.get(key)
        return len(value) if isinstance(value, list) else 0

    return {
        "name": meta.get("n") or None,
        "author": meta.get("a") or None,
        "mode": meta.get("mo") or None,
        "date": meta.get("date") or None,
        "map_id": meta.get("dbid"),
        "upvotes": meta.get("vu"),
        "downvotes": meta.get("vd"),
        "shapes": count(physics, "shapes"),
        "bodies": count(physics, "bodies"),
        "joints": count(physics, "joints"),
        "spawns": count(data, "spawns"),
        "cap_zones": count(data, "capZones"),
    }


@bot_endpoint("POST")
def decode_map(request):
    """POST maps/decode/ {"code": "<bonk.io map string>"} — a summary of the map."""
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return fail("invalid_json", 400)
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(code, str) or not code.strip() or len(code) > MAX_MAP_CODE:
        return fail("missing_code", 400)
    result = decode_map_configured(code.strip())
    if result.error == DecodeError.REJECTED:
        return fail("map_rejected", 422, detail=result.detail)
    if result.error:
        return fail("upstream_unavailable", 503)
    return ok({"map": map_summary(result.data)})


# How an import failure is reported to the bot (permanent ones are 422).
IMPORT_STATUS = {
    "invalid_link": 422,
    "link_too_long": 422,
    "unsafe_svg": 422,
    "svg_too_large": 422,
    "invalid_skin_code": 422,
    "render_failed": 502,
    "fetch_failed": 502,
    "storage_failed": 503,
}


@bot_endpoint("POST")
def collect(request):
    """POST collection/ {"bonk_username", "link" | "skin_id", "discord_user_id"}
    — add a skin to that player's collection (their favorites), uploading it
    from BonkLeagues first if needed. The player is BonxBot-verified; a site
    account is made for them if they've never signed in, as sign-in would."""
    try:
        body = json.loads(request.body or b"{}")
        player = BonkUsername(body.get("bonk_username") or "")
    except (ValueError, UnicodeDecodeError, AttributeError, InvalidUsername):
        return fail("invalid_username", 400)

    try:
        user = site_account_for(player)
    except ProtectedSiteAccount:
        # A staff or admin site account by that name: never credited by name.
        return fail("account_protected", 403)
    result = collect_skin(
        user,
        link=body.get("link"),
        skin_id=body.get("skin_id"),
        discord_user_id=discord_id_or_none(body.get("discord_user_id")),
    )
    if result.error:
        status = 404 if result.error == "skin_not_found" else IMPORT_STATUS.get(result.error, 400)
        return fail(result.error, status)

    skin = result.skin
    if not result.already:
        log_event(user, "skin_favorited", skin=skin, source="discord")
    if result.uploaded:
        log_event(None, "skin_uploaded", skin=skin, source="discord_collection")
    found = Skin.objects.with_favorite_count().get(id=skin.id)
    return ok(
        {
            "skin": skin_data(request, found),
            "uploaded": result.uploaded,
            "already_collected": result.already,
            "collection_size": user.favorite_skins.count(),
            "collection_url": request.build_absolute_uri(
                reverse("players:player_skins", args=[user.username]) + "?view=favorites"
            ),
        }
    )
