from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django_ratelimit.decorators import ratelimit
from .models import Skin, SkinVote
import json


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
@ratelimit(key="ip", rate="500/h", block=True)
def vote_skin_api(request, skin_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "auth required"}, status=401)

    skin = get_object_or_404(Skin, id=skin_id)
    vote_value = _get_vote_from_request(request)
    if vote_value not in ("up", "down"):
        return JsonResponse({"error": "invalid vote"}, status=400)

    vote, created = SkinVote.objects.get_or_create(user=request.user, skin=skin)
    current_vote = None

    if not created and vote.vote == vote_value:
        # Clicking the same vote again — remove it
        if vote_value == "up":
            skin.upvotes = max(0, skin.upvotes - 1)
        else:
            skin.downvotes = max(0, skin.downvotes - 1)
        vote.delete()
    else:
        # Undo previous vote first
        if vote.vote == "up":
            skin.upvotes = max(0, skin.upvotes - 1)
        elif vote.vote == "down":
            skin.downvotes = max(0, skin.downvotes - 1)

        vote.vote = vote_value
        vote.save()
        current_vote = vote_value

        if vote_value == "up":
            skin.upvotes += 1
        else:
            skin.downvotes += 1

    skin.save(update_fields=["upvotes", "downvotes"])

    # Don't call skin.favorited_by.count() here — the vote API response
    # doesn't use it on the frontend, so it's a free wasted query.
    return JsonResponse({
        "upvotes":      skin.upvotes,
        "downvotes":    skin.downvotes,
        "current_vote": current_vote,
        "status":       "ok",
    })


@require_POST
@ratelimit(key="ip", rate="500/h", block=True)
def toggle_favorite_api(request, skin_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "auth required"}, status=401)

    skin = get_object_or_404(Skin, id=skin_id)

    # .exists() → SELECT 1 LIMIT 1, not SELECT * for every favoriting user
    if skin.favorited_by.filter(pk=request.user.pk).exists():
        skin.favorited_by.remove(request.user)
        favorited = False
    else:
        skin.favorited_by.add(request.user)
        favorited = True

    # One COUNT(*) here is fine — the favorite count IS used in the response
    favorites = skin.favorited_by.count()

    return JsonResponse({
        "favorited":  favorited,
        "favorites":  favorites,
        "upvotes":    skin.upvotes,
        "downvotes":  skin.downvotes,
        "status":     "ok",
    })