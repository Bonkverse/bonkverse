"""The report queue: /moderation/ (skins/moderation.py does the work).

Open to anyone with skins.moderate_skins: the Moderator group
(manage.py grant_moderator) and superusers.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.auth_guards import permission_required
from core.ratelimits import limit
from skins import moderation
from skins.models import Skin


@permission_required("skins.moderate_skins")
@limit("browse")
def queue(request):
    return render(
        request,
        "skins/moderation.html",
        {
            "skins": moderation.report_queue(),
            "decisions": moderation.recent_decisions(),
        },
    )


@require_POST
@permission_required("skins.moderate_skins")
@limit("write")
def decide(request, skin_id):
    decide_with = moderation.DECISIONS.get(request.POST.get("action", ""))
    if decide_with is None:
        raise Http404
    try:
        outcome = decide_with(
            skin_id,
            request.user,
            request.POST.get("note", ""),
            request.POST.get("creator", ""),
        )
    except Skin.DoesNotExist:
        messages.error(request, "That skin is already gone; someone else may have decided.")
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, outcome.message)
    return redirect("skins:moderation")
