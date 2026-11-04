"""Wearing skins on bonk.io from Bonkverse.

Owns: the wear endpoints (gallery skin by id, unsaved editor skin by code) and
the in-page bonk.io login used when the player's bonk.io token is missing.
Does not own: the bonk.io session rules (core/bonk/session.py) or, after
RFC-0001 Phase 2.2, the HTTP calls to bonk.io (integrations/bonk_api.py).

JSON contract the frontend relies on (tests/test_wear.py):
- 401 with auth="bonkverse" -> sign in to the site
- 401 with auth="bonk"      -> show the bonk.io login modal
- 401 without auth          -> the bonk.io credentials were wrong
"""

import logging
from dataclasses import dataclass

import requests
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from core.bonk import AvatarSlot, BonkSession
from core.ratelimits import limit

from .auth_guards import api_login_required, bonk_token_required
from .events import log_event
from .models import Skin

logger = logging.getLogger(__name__)

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
BONK_AVATAR_UPDATE_URL = "https://bonk2.io/scripts/avatar_update.php"
TIMEOUT = 10


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


@dataclass
class BonkLoginResult:
    ok: bool
    token: str | None
    active_slot: AvatarSlot | None
    error: str | None


def _bonk_login(username: str, password: str) -> BonkLoginResult:
    try:
        r = requests.post(
            BONK_LOGIN_URL,
            data={"task": "legacy", "username": username, "password": password},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("r") == "success" and data.get("token"):
            active = AvatarSlot.parse(
                data.get("activeAvatarNumber") or data.get("activeavatarnumber")
            )
            return BonkLoginResult(True, data["token"], active, None)
        return BonkLoginResult(False, None, None, data.get("error") or "login_failed")
    except Exception:
        return BonkLoginResult(False, None, None, "network_error")


def _bonk_update_avatar(token: str, slot: AvatarSlot, skin_code: str):
    try:
        r = requests.post(
            BONK_AVATAR_UPDATE_URL,
            data={
                "task": "updateavatar",
                "token": token,
                "newavatarslot": str(slot),
                "newavatar": skin_code,
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("r") != "success":
            # Token is never in the response; safe to log.
            logger.warning(
                "[wear-debug] avatar_update non-success | http=%s | body=%s | skin_code_len=%s | slot=%s",
                r.status_code,
                r.text[:500],
                len(skin_code or ""),
                slot,
            )
        return (data.get("r") == "success", data.get("error"))
    except Exception as e:
        logger.warning("[wear-debug] avatar_update exception: %r", e)
        return (False, "network_error")


def _resolve_slot(request) -> AvatarSlot:
    """The slot from the form if valid, else the player's active slot, else 3."""
    return AvatarSlot.choose(request.POST.get("slot"), BonkSession(request.session).active_slot)


@api_login_required
@require_POST
@limit("login", method="POST")
def bonk_login_for_wear(request):
    """Mint a bonk.io token from credentials (the rare first-time / expired path)."""
    bonk_username = request.POST.get("bonk_username")
    password = request.POST.get("bonk_password")
    if not bonk_username or not password:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)

    result = _bonk_login(bonk_username, password)
    if not result.ok:
        # Bad bonk credentials — 401 WITHOUT an `auth` tag so the client treats
        # it as a credential error, not a session-expired redirect.
        return JsonResponse({"ok": False, "error": result.error}, status=401)

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
    bonk = BonkSession(request.session)
    token = bonk.token  # guaranteed present by decorator
    skin_code = request.POST.get("skin_code")
    if not skin_code:
        return JsonResponse({"ok": False, "error": "skin_code_not_found"}, status=400)

    slot = _resolve_slot(request)
    ok, err = _bonk_update_avatar(token, slot, skin_code)
    if not ok:
        _debug_wear(request, "wear_code: bonk rejected update", err=err, slot=slot)
        # Token went stale at bonk's side — ask for a fresh bonk login.
        return JsonResponse(
            {"ok": False, "auth": "bonk", "error": err or "update_failed"}, status=401
        )

    bonk.store_token(token)  # sliding TTL
    log_event(request.user, "skin_worn", metadata={"source": "editor_unsaved"})
    return JsonResponse({"ok": True, "slot": slot.number})


@bonk_token_required
@require_POST
@limit("write")
def wear_skin(request, skin_id: int):
    """Wear a gallery skin by id in the requested (or active) slot."""
    _debug_wear(request, "wear: passed decorator", skin_id=skin_id)
    bonk = BonkSession(request.session)
    token = bonk.token  # guaranteed present by decorator
    slot = _resolve_slot(request)
    skin = get_object_or_404(Skin, id=skin_id)
    skin_code = skin.skin_code
    if not skin_code:
        return JsonResponse({"ok": False, "error": "skin_code_not_found"}, status=400)

    ok, err = _bonk_update_avatar(token, slot, skin_code)
    if not ok:
        _debug_wear(request, "wear: bonk rejected update", err=err, slot=slot, skin_id=skin_id)
        return JsonResponse(
            {"ok": False, "auth": "bonk", "error": err or "update_failed"}, status=401
        )

    bonk.store_token(token)  # sliding TTL
    log_event(request.user, "skin_worn", skin=skin)
    return JsonResponse({"ok": True, "slot": slot.number})
