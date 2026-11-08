"""Public API v1 endpoints. Reference: Bonkverse/developers (docs site).

Every endpoint needs an API key (auth.py) and answers with the envelope in
responses.py. Player names are bonk.io usernames, matched ignoring case.
"""

import json

from . import selectors
from .auth import api_endpoint
from .responses import fail, ok

_ERROR_STATUS = {
    selectors.NOT_FOUND: 404,
    selectors.PRIVATE: 403,
    selectors.UNAVAILABLE: 503,
}
_ERROR_CODE = {
    selectors.NOT_FOUND: "player_not_found",
    selectors.PRIVATE: "player_private",
    selectors.UNAVAILABLE: "upstream_unavailable",
}
CACHE_SECONDS = 300


def _url_builder(request):
    return request.build_absolute_uri


@api_endpoint("api")
def me(request):
    """GET /api/v1/me/ — the key you're using. Handy for checking setup."""
    key = request.api_key
    return ok(
        {
            "name": key.name,
            "prefix": f"bvk_{key.prefix}",
            "tier": key.tier,
            "created_at": key.created_at.isoformat(),
        }
    )


@api_endpoint("api")
def player(request, username):
    """GET /api/v1/players/<username>/ — level and replay totals for one player."""
    name = selectors.valid_username(username)
    if name is None:
        return fail("invalid_username", 400)
    entry = selectors.player_entries([name], _url_builder(request))[0]
    status = entry["status"]
    if status in (selectors.NOT_FOUND, selectors.UNAVAILABLE):
        return fail(_ERROR_CODE[status], _ERROR_STATUS[status])
    return ok(entry, cache_seconds=CACHE_SECONDS)


@api_endpoint("api")
def level_history(request, username):
    """GET /api/v1/players/<username>/level-history/ — every level-up seen
    in replays, and the highest level on each day played."""
    name = selectors.valid_username(username)
    if name is None:
        return fail("invalid_username", 400)
    data, error = selectors.level_history(name)
    if error:
        return fail(_ERROR_CODE[error], _ERROR_STATUS[error])
    return ok(data, cache_seconds=CACHE_SECONDS)


@api_endpoint("api_bulk", methods=("POST",))
def lookup_players(request):
    """POST /api/v1/lookup/players/ {"usernames": [...]} — up to 250 players
    at once. Every name gets an entry with a status; one missing or private
    player never fails the whole request."""
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return fail("invalid_json", 400)
    usernames = body.get("usernames") if isinstance(body, dict) else None
    if not isinstance(usernames, list) or not usernames:
        return fail("usernames_required", 400)
    if len(usernames) > selectors.MAX_LOOKUP_NAMES:
        return fail("too_many_usernames", 400, max=selectors.MAX_LOOKUP_NAMES)
    names = [selectors.valid_username(n) for n in usernames]
    if any(n is None for n in names):
        return fail("invalid_username", 400)

    entries = selectors.player_entries(names, _url_builder(request))
    counts = {}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return ok({"players": entries, "counts": counts})
