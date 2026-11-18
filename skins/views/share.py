from django.shortcuts import get_object_or_404, redirect

from core.ratelimits import limit
from skins.models import Skin


@limit("browse")
def share_skin(request, skin_id, uuid):
    """Old share links (/skins/share/<id>/<uuid>/) go to the skin's page.

    The share page was a second, older skin page that still showed the
    generated description; links to it are all over Discord, so the address
    stays and points at the one skin page (design review 2026-11-09).
    """
    skin = get_object_or_404(Skin, id=skin_id, uuid=uuid)
    return redirect(skin, permanent=True)
