"""Read endpoints for BonxBot, the Bonkverse Discord bot (/api/bot/).

Owns: GET skins/search/, skins/random/, skins/<id>/, players/<username>/ and
POST maps/decode/ — what each returns to the bot. Same shared secret as skin
submissions (core/bot_auth.py), the public API's envelope (responses.py), and
one "bot" rate-limit tier for the bot's IP.
Does not own: search rules (skins/querysets.py), player data (selectors.py)
or decoding (integrations/map_decoder.py).

    {"ok": true, "data": {...}}  /  {"ok": false, "error": "skin_not_found"}

Errors: unauthorized 401, missing_query 400, invalid_username 400,
skin_not_found 404, player_not_found 404, search_timeout 503,
missing_code 400, map_rejected 422 (+ "detail"), upstream_unavailable 503.
"""

import functools
import json

from django.conf import settings
from django.db import OperationalError
from django.views.decorators.csrf import csrf_exempt

from core.bot_auth import bot_authorized
from core.ratelimits import limit
from integrations.map_decoder import DecodeError, decode_map_configured
from skins.models import Skin
from skins.selectors import best_matches, random_skin

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
