"""/api/: the old placeholder page for the Bonkverse API.

The public API and its keys are on the Developers page now, so /api/ sends
people there. (Everything else under /api/ is the API itself.)
"""

from django.shortcuts import redirect

from core.ratelimits import limit


@limit("browse")
def index(request):
    return redirect("developers:developers")
