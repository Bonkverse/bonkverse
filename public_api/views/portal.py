"""The developer portal (/developers/): read about the API, agree to its
terms, and create or revoke your own API keys.

Thin views: rules live in services.py, reads in selectors.py. A new key is
shown once, in the reply to the POST that made it (never redirected, never
stored); that reply is `no-store` so the browser doesn't keep it either.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from core.ratelimits import limit

from .. import selectors, services
from ..models import ApiKey

_ERRORS = {
    "terms_not_accepted": "Tick the box to agree to the API terms first.",
    "name_required": "Give the key a name, like the site or bot it's for.",
    "name_too_long": "Key names can be at most 100 characters.",
    "too_many_keys": (
        "You already have {max} active keys. Revoke one you don't use to make a new one."
    ),
    "key_not_found": "That key doesn't exist or is already revoked.",
}


def _error(code):
    return _ERRORS[code].format(max=settings.PUBLIC_API_MAX_KEYS_PER_USER)


def _keys_page(request, *, new_key=None, new_raw=None, status=200):
    keys = list(selectors.keys_for(request.user))
    active = sum(1 for k in keys if k.is_active)
    context = {
        "keys": keys,
        "active_count": active,
        "max_keys": settings.PUBLIC_API_MAX_KEYS_PER_USER,
        "at_limit": active >= settings.PUBLIC_API_MAX_KEYS_PER_USER,
        "terms_accepted": services.has_accepted_terms(request.user),
        "new_key": new_key,
        "new_raw": new_raw,
        "partner_tier": ApiKey.TIER_PARTNER,
    }
    return render(request, "developers/keys.html", context, status=status)


@limit("browse")
def index(request):
    """GET /developers/: what the API is, with links to the docs and keys."""
    return render(request, "developers/index.html")


@limit("browse")
def terms(request):
    """GET /developers/terms/: the API terms."""
    return render(request, "developers/terms.html", {"terms_version": services.TERMS_VERSION})


@never_cache
@login_required
@limit("write", method="POST")
def keys(request):
    """GET: your keys and the form for a new one. POST: create a key and
    show it once."""
    if request.method != "POST":
        return _keys_page(request)

    try:
        api_key, raw = services.create_own_key(
            request.user,
            name=request.POST.get("name", ""),
            agree_to_terms=request.POST.get("agree") == "on",
        )
    except services.PortalError as err:
        messages.error(request, _error(err.code))
        return redirect("developer_keys")
    return _keys_page(request, new_key=api_key, new_raw=raw)


@require_POST
@login_required
@limit("write", method="POST")
def revoke_key(request, prefix):
    """POST /developers/keys/<prefix>/revoke/: revoke one of your keys."""
    try:
        api_key = services.revoke_own_key(request.user, prefix)
    except services.PortalError as err:
        messages.error(request, _error(err.code))
    else:
        messages.success(request, f"Revoked “{api_key.name}”. Requests with it now get 401.")
    return redirect("developer_keys")
