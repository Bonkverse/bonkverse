"""Wearing skins on bonk.io from Bonkverse.

Owns: the wear endpoints (gallery skin by id, unsaved editor skin by code) and
the in-page bonk.io login used when the player's bonk.io token is missing.
Does not own: the bonk.io session rules (core/bonk/session.py) or the HTTP
calls to bonk.io (integrations/bonk_api.py).

JSON contract the frontend relies on (tests/test_wear.py):
- 401 with auth="bonkverse" -> sign in to the site
- 401 with auth="bonk"      -> show the bonk.io login modal
- 401 without auth          -> the bonk.io credentials were wrong
- any other failure         -> no modal; show `message` (a sentence):
    422 avatar_too_big   the skin is over bonk.io's size limit
    503 rate_limited     bonk.io is limiting requests from Bonkverse
    502 network_error    bonk.io couldn't be reached
    502 rejected         a refusal code we don't recognise (logged)

Only bonk.io's "token" refusal opens the login modal. Treating every refusal
as an expired token made the modal reappear forever for a too-big skin, and
every time bonk.io was rate-limiting the server (docs/bonk/api.md).
"""

import logging

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from core.bonk import AvatarSlot, BonkSession
from core.ratelimits import limit
from integrations.bonk_api import BonkAvatarUpdateResult, BonkError, get_client

from .auth_guards import api_login_required, bonk_token_required
from .events import log_event
from .login import login_failure_message
from .models import Skin

logger = logging.getLogger(__name__)


def _debug_wear(request, label: str, **extra):
    """
    TEMPORARY diagnostics for the "login modal keeps reappearing" bug.
    Never logs the token itself — only whether one exists.
    Remove once the cause is found.
    """
    bonk = BonkSession(request.session)
    raw_cookie = request.META.get("HTTP_COOKIE", "")
    # No username or session key: these lines are about session state, not people.
    logger.info(
        "[wear-debug] %s | has_token=%s | token_expires_in=%s | "
        "sessionid_cookie_count=%s | host=%s | %s",
        label,
        bool(request.session.get("bonk_token")),
        bonk.expires_in_seconds,
        raw_cookie.count("sessionid="),
        request.get_host(),
        extra,
    )


def _resolve_slot(request) -> AvatarSlot:
    """The slot from the form if valid, else the player's active slot, else 3."""
    return AvatarSlot.choose(request.POST.get("slot"), BonkSession(request.session).active_slot)


# Failures a new bonk.io login can't fix: (HTTP status, sentence for the player).
_WEAR_FAILURES = {
    BonkError.AVATAR_TOO_BIG: (
        422,
        "This skin is too big for bonk.io (it has too many shapes), so it can't be worn.",
    ),
    BonkError.RATE_LIMITED: (
        503,
        "bonk.io is limiting requests from Bonkverse right now. Try again in a few minutes.",
    ),
    BonkError.UNAVAILABLE: (502, "bonk.io isn't responding. Try again in a minute."),
}
_UNKNOWN_FAILURE = (502, "bonk.io didn't accept this skin.")


def _update_failed_response(result: BonkAvatarUpdateResult) -> JsonResponse:
    """The JSON reply when bonk.io didn't apply the skin."""
    if result.error == BonkError.TOKEN_REJECTED:
        # The one case a fresh bonk.io login fixes: open the login modal.
        return JsonResponse({"ok": False, "auth": "bonk", "error": result.error}, status=401)
    status, message = _WEAR_FAILURES.get(result.error, _UNKNOWN_FAILURE)
    # No auth tag, so the page shows `message` and never opens the modal.
    return JsonResponse({"ok": False, "error": result.error, "message": message}, status=status)


def _wear(request, skin_code: str, **debug) -> tuple[AvatarSlot, JsonResponse | None]:
    """Send `skin_code` to the player's bonk.io account.

    Returns the slot used, and an error response if bonk.io didn't apply it.
    """
    bonk = BonkSession(request.session)
    token = bonk.token  # guaranteed present by bonk_token_required
    slot = _resolve_slot(request)
    result = get_client().update_avatar(token, slot, skin_code)
    if not result.ok:
        _debug_wear(request, "wear: bonk update failed", err=result.error, slot=slot, **debug)
        return slot, _update_failed_response(result)
    bonk.store_token(token)  # sliding TTL
    return slot, None


@api_login_required
@require_POST
@limit("login", method="POST")
def bonk_login_for_wear(request):
    """Mint a bonk.io token from credentials (the rare first-time / expired path)."""
    bonk_username = request.POST.get("bonk_username")
    password = request.POST.get("bonk_password")
    if not bonk_username or not password:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)

    result = get_client().login(bonk_username, password)
    if not result.ok:
        # Bad bonk credentials — 401 WITHOUT an `auth` tag so the client treats
        # it as a credential error, not a session-expired redirect.
        return JsonResponse(
            {
                "ok": False,
                "error": result.error,
                "message": login_failure_message(result.error),
            },
            status=401,
        )

    bonk = BonkSession(request.session)
    bonk.store_token(result.token)
    bonk.store_active_slot(result.active_slot)
    _debug_wear(request, "login: token saved", active_slot=result.active_slot)
    active_slot = result.active_slot.number if result.active_slot else None
    return JsonResponse({"ok": True, "active_slot": active_slot})


@bonk_token_required
@require_POST
@limit("write")
def wear_skin_code(request):
    """Wear an unsaved editor skin from a raw skin_code (no DB row)."""
    skin_code = request.POST.get("skin_code")
    if not skin_code:
        return JsonResponse({"ok": False, "error": "skin_code_not_found"}, status=400)

    slot, error_response = _wear(request, skin_code, source="editor_unsaved")
    if error_response:
        return error_response
    log_event(request.user, "skin_worn", metadata={"source": "editor_unsaved"})
    return JsonResponse({"ok": True, "slot": slot.number})


@bonk_token_required
@require_POST
@limit("write")
def wear_skin(request, skin_id: int):
    """Wear a gallery skin by id in the requested (or active) slot."""
    _debug_wear(request, "wear: passed decorator", skin_id=skin_id)
    skin = get_object_or_404(Skin, id=skin_id)
    if not skin.skin_code:
        return JsonResponse({"ok": False, "error": "skin_code_not_found"}, status=400)

    slot, error_response = _wear(request, skin.skin_code, skin_id=skin_id)
    if error_response:
        return error_response
    log_event(request.user, "skin_worn", skin=skin)
    return JsonResponse({"ok": True, "slot": slot.number})
