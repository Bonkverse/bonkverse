# from django.contrib.auth.decorators import login_required
# from django.http import HttpResponseRedirect
# from django.urls import reverse
# from .models import Skin, SkinVote
# from django.shortcuts import get_object_or_404

# @login_required
# def vote_skin(request, skin_id):
#     skin = get_object_or_404(Skin, id=skin_id)
#     vote_value = request.POST.get("vote")

#     vote, created = SkinVote.objects.get_or_create(user=request.user, skin=skin)
#     if vote.vote != vote_value:
#         if vote.vote == 'up':
#             skin.upvotes -= 1
#         elif vote.vote == 'down':
#             skin.downvotes -= 1

#         vote.vote = vote_value
#         vote.save()

#         if vote_value == 'up':
#             skin.upvotes += 1
#         elif vote_value == 'down':
#             skin.downvotes += 1

#         skin.save()

#     return HttpResponseRedirect(reverse('skin_detail', args=[skin.id]))

# @login_required
# def toggle_favorite(request, skin_id):
#     skin = get_object_or_404(Skin, id=skin_id)
#     if request.user in skin.favorited_by.all():
#         skin.favorited_by.remove(request.user)
#     else:
#         skin.favorited_by.add(request.user)
#     return HttpResponseRedirect(reverse('skin_detail', args=[skin.id]))

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

@require_POST
def vote_skin_api(request, skin_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "auth required"}, status=401)

    skin = get_object_or_404(Skin, id=skin_id)
    vote_value = _get_vote_from_request(request)
    if vote_value not in ("up", "down"):
        return JsonResponse({"error": "invalid vote"}, status=400)

    vote, _ = SkinVote.objects.get_or_create(user=request.user, skin=skin)

    # remove previous
    if vote.vote == 'up':
        skin.upvotes = max(0, skin.upvotes - 1)
    elif vote.vote == 'down':
        skin.downvotes = max(0, skin.downvotes - 1)

    vote.vote = vote_value
    vote.save()

    if vote_value == 'up':
        skin.upvotes += 1
    else:
        skin.downvotes += 1

    skin.save(update_fields=["upvotes", "downvotes"])

    return JsonResponse({
        "upvotes": skin.upvotes,
        "downvotes": skin.downvotes,
        "favorites": skin.favorited_by.count(),
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
