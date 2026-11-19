"""Your own skins: the owner's actions on their profile's Skins tab.

The tab itself is players/ (players/templates/players/skins.html); its owner
script (skins/static/js/skin_owner.js) calls these JSON endpoints. Each one
checks Skin.is_owned_by. /my-profile/ is kept as a redirect for old links
and the account menu.
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from core.auth_guards import api_login_required
from core.ratelimits import limit
from skins import editing
from skins.models import Skin

MAX_BULK_DELETE = 100


def _not_yours():
    return JsonResponse({"ok": False, "error": "not_owner"}, status=403)


@login_required
@limit("browse")
def my_profile(request):
    """The old My profile page: your profile's Skins tab now."""
    return redirect("players:player_skins", request.user.username)


@require_POST
@api_login_required
@limit("write")
def edit_skin(request, skin_id):
    """Rename a skin and set its tags (POST name, tags as a JSON list)."""
    skin = get_object_or_404(Skin, id=skin_id)
    if not skin.is_owned_by(request.user):
        return _not_yours()
    try:
        tags = json.loads(request.POST.get("tags") or "[]")
        edited = editing.edit(skin.id, name=request.POST.get("name"), tags=tags)
    except json.JSONDecodeError:
        return JsonResponse(
            {"ok": False, "error": "bad_tags", "message": "Tags must be a list."}, status=400
        )
    except editing.EditError as error:
        return JsonResponse(
            {"ok": False, "error": "invalid_edit", "message": str(error)}, status=400
        )
    return JsonResponse({"ok": True, "data": {"name": edited.name, "tags": edited.tags}})


@require_POST
@api_login_required
@limit("write")
def delete_skin(request, skin_id):
    """Delete one skin you own. POST only: a visit to the URL never deletes."""
    skin = get_object_or_404(Skin, id=skin_id)
    if not skin.is_owned_by(request.user):
        return _not_yours()
    skin.delete()
    return JsonResponse({"ok": True, "data": {"deleted_ids": [skin_id]}})


@require_POST
@api_login_required
@limit("write")
def bulk_delete_skins(request):
    """Delete the selected skins (POST skin_ids, repeated). Only skins the
    requester owns are deleted, so a doctored list can't touch anyone else's."""
    try:
        ids = [int(i) for i in request.POST.getlist("skin_ids")]
    except ValueError:
        return JsonResponse({"ok": False, "error": "bad_ids"}, status=400)
    if not ids:
        return JsonResponse({"ok": False, "error": "nothing_selected"}, status=400)
    if len(ids) > MAX_BULK_DELETE:
        return JsonResponse({"ok": False, "error": "too_many"}, status=400)

    owned = Skin.objects.made_by(request.user.username).filter(id__in=ids)
    deleted_ids = list(owned.values_list("id", flat=True))
    owned.delete()
    return JsonResponse({"ok": True, "data": {"deleted_ids": deleted_ids}})
