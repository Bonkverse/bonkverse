from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import Skin, SkinVote

def _get_vote_from_request(request):
    # Accept form or JSON
    vote = request.POST.get("vote")
    if not vote:
        import json
        try:
            data = json.loads(request.body or "{}")
            vote = data.get("vote")
        except Exception:
            vote = None
    return vote

# @require_POST
# def vote_skin_api(request, skin_id):
#     if not request.user.is_authenticated:
#         return JsonResponse({"error": "auth required"}, status=401)

#     skin = get_object_or_404(Skin, id=skin_id)
#     vote_value = _get_vote_from_request(request)
#     if vote_value not in ("up", "down"):
#         return JsonResponse({"error": "invalid vote"}, status=400)

#     vote, _ = SkinVote.objects.get_or_create(user=request.user, skin=skin)

#     # remove previous
#     if vote.vote == 'up':
#         skin.upvotes = max(0, skin.upvotes - 1)
#     elif vote.vote == 'down':
#         skin.downvotes = max(0, skin.downvotes - 1)

#     vote.vote = vote_value
#     vote.save()

#     if vote_value == 'up':
#         skin.upvotes += 1
#     else:
#         skin.downvotes += 1

#     skin.save(update_fields=["upvotes", "downvotes"])

#     return JsonResponse({
#         "upvotes": skin.upvotes,
#         "downvotes": skin.downvotes,
#         "favorites": skin.favorited_by.count(),
#         "status": "ok",
#     })

@require_POST
def vote_skin_api(request, skin_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "auth required"}, status=401)

    skin = get_object_or_404(Skin, id=skin_id)
    vote_value = _get_vote_from_request(request)
    if vote_value not in ("up", "down"):
        return JsonResponse({"error": "invalid vote"}, status=400)

    vote, created = SkinVote.objects.get_or_create(user=request.user, skin=skin)

    current_vote = None

    # If clicking the same vote again → remove it
    if not created and vote.vote == vote_value:
        if vote_value == "up":
            skin.upvotes = max(0, skin.upvotes - 1)
        else:
            skin.downvotes = max(0, skin.downvotes - 1)
        vote.delete()
    else:
        # remove previous vote first
        if vote.vote == "up":
            skin.upvotes = max(0, skin.upvotes - 1)
        elif vote.vote == "down":
            skin.downvotes = max(0, skin.downvotes - 1)

        # apply new vote
        vote.vote = vote_value
        vote.save()
        current_vote = vote.vote

        if vote_value == "up":
            skin.upvotes += 1
        else:
            skin.downvotes += 1

    skin.save(update_fields=["upvotes", "downvotes"])

    # If deleted, current_vote should stay None
    return JsonResponse({
        "upvotes": skin.upvotes,
        "downvotes": skin.downvotes,
        "favorites": skin.favorited_by.count(),
        "current_vote": current_vote,
        "status": "ok",
    })



@require_POST
def toggle_favorite_api(request, skin_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "auth required"}, status=401)

    skin = get_object_or_404(Skin, id=skin_id)
    if request.user in skin.favorited_by.all():
        skin.favorited_by.remove(request.user)
        favorited = False
    else:
        skin.favorited_by.add(request.user)
        favorited = True

    return JsonResponse({
        "favorited": favorited,
        "favorites": skin.favorited_by.count(),
        "upvotes": skin.upvotes,
        "downvotes": skin.downvotes,
        "status": "ok",
    })
