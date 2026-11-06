"""JSON endpoints for voting on and favoriting skins.

Owns: parsing the request, auth and rate limits, and the JSON the skin cards
read (pinned by tests/test_skin_actions.py).
Does not own: the vote rules and counters (skins/votes.py).
"""

import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from core.ratelimits import limit

from .events import log_event
from .models import Skin
from .votes import DIRECTIONS, cast_vote


def _get_vote_from_request(request):
    vote = request.POST.get("vote")
    if not vote:
        try:
            data = json.loads(request.body or "{}")
            vote = data.get("vote")
        except Exception:
            vote = None
    return vote


@require_POST
@limit("vote")
def vote_skin_api(request, skin_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "auth required"}, status=401)

    skin = get_object_or_404(Skin, id=skin_id)
    direction = _get_vote_from_request(request)
    if direction not in DIRECTIONS:
        return JsonResponse({"error": "invalid vote"}, status=400)

    result = cast_vote(request.user, skin, direction)

    if result.current_vote:
        log_event(request.user, "skin_voted", skin=skin, direction=result.current_vote)

    # Don't call skin.favorited_by.count() here — the vote API response
    # doesn't use it on the frontend, so it's a free wasted query.
    return JsonResponse(
        {
            "upvotes": result.upvotes,
            "downvotes": result.downvotes,
            "current_vote": result.current_vote,
            "status": "ok",
        }
    )


@require_POST
@limit("vote")
def toggle_favorite_api(request, skin_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "auth required"}, status=401)

    skin = get_object_or_404(Skin, id=skin_id)

    # .exists() → SELECT 1 LIMIT 1, not SELECT * for every favoriting user
    if skin.favorited_by.filter(pk=request.user.pk).exists():
        skin.favorited_by.remove(request.user)
        favorited = False
    else:
        # Safe under a double click: the join table is unique per (skin, user)
        # and Django inserts with ON CONFLICT DO NOTHING on Postgres.
        skin.favorited_by.add(request.user)
        favorited = True

    # Counts the join rows, so it is always right; nothing to drift.
    favorites = skin.favorited_by.count()

    log_event(request.user, "skin_favorited" if favorited else "skin_unfavorited", skin=skin)

    return JsonResponse(
        {
            "favorited": favorited,
            "favorites": favorites,
            "upvotes": skin.upvotes,
            "downvotes": skin.downvotes,
            "status": "ok",
        }
    )
