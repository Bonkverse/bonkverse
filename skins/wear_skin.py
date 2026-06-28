# skins/wear_skin.py
import time, requests
from dataclasses import dataclass
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from urllib.parse import urlparse, parse_qs
from .models import Skin
from .auth_guards import api_login_required, bonk_token_required

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
BONK_AVATAR_UPDATE_URL = "https://bonk2.io/scripts/avatar_update.php"
TIMEOUT = 10
TOKEN_TTL = 14 * 24 * 60 * 60  # 14 days
# TOKEN_TTL = 30  # 30 seconds for testing


def _extract_skin_code(image_url: str):
    try:
        return parse_qs(urlparse(image_url).query).get("skinCode", [None])[0]
    except Exception:
        return None


@dataclass
class BonkLoginResult:
    ok: bool
    token: str | None
    active_slot: int | None
    error: str | None


def _save_session_token(request, token: str):
    request.session["bonk_token"] = token
    request.session["bonk_token_expires"] = time.time() + TOKEN_TTL
    request.session.modified = True


def _save_active_slot(request, slot: int | None):
    if slot in (1, 2, 3, 4, 5):
        request.session["bonk_active_slot"] = slot
        request.session.modified = True


def _get_session_token(request):
    tok = request.session.get("bonk_token")
    exp = request.session.get("bonk_token_expires", 0)
    if tok and time.time() < exp:
        return tok
    return None


def _get_active_slot(request):
    slot = request.session.get("bonk_active_slot")
    return slot if slot in (1, 2, 3, 4, 5) else None


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
            active = data.get("activeAvatarNumber") or data.get("activeavatarnumber")
            try:
                active = int(active) if active is not None else None
            except Exception:
                active = None
            return BonkLoginResult(True, data["token"], active, None)
        return BonkLoginResult(False, None, None, data.get("error") or "login_failed")
    except Exception:
        return BonkLoginResult(False, None, None, "network_error")


def _bonk_update_avatar(token: str, slot: int, skin_code: str):
    try:
        r = requests.post(
            BONK_AVATAR_UPDATE_URL,
            data={"task": "updateavatar", "token": token,
                  "newavatarslot": str(slot), "newavatar": skin_code},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("r") == "success", data.get("error"))
    except Exception:
        return (False, "network_error")


def _resolve_slot(request):
    slot = request.POST.get("slot")
    if slot:
        try:
            slot = int(slot)
        except Exception:
            slot = None
    if slot not in (1, 2, 3, 4, 5):
        slot = _get_active_slot(request) or 3
    return slot


@api_login_required
@require_POST
def bonk_login_for_wear(request):
    """Mint a bonk.io token from credentials (the rare first-time / expired path)."""
    u = request.POST.get("bonk_username")
    p = request.POST.get("bonk_password")
    if not u or not p:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)

    res = _bonk_login(u, p)
    if not res.ok:
        # Bad bonk credentials — 401 WITHOUT an `auth` tag so the client treats
        # it as a credential error, not a session-expired redirect.
        return JsonResponse({"ok": False, "error": res.error}, status=401)

    _save_session_token(request, res.token)
    _save_active_slot(request, res.active_slot)
    return JsonResponse({"ok": True, "active_slot": res.active_slot})


@bonk_token_required
@require_POST
def wear_skin_code(request):
    """Wear an unsaved editor skin from a raw skin_code (no DB row)."""
    token = _get_session_token(request)  # guaranteed present by decorator
    skin_code = request.POST.get("skin_code")
    if not skin_code:
        return JsonResponse({"ok": False, "error": "skin_code_not_found"}, status=400)

    slot = _resolve_slot(request)
    ok, err = _bonk_update_avatar(token, slot, skin_code)
    if not ok:
        # Token went stale at bonk's side — ask for a fresh bonk login.
        return JsonResponse({"ok": False, "auth": "bonk", "error": err or "update_failed"}, status=401)

    _save_session_token(request, token)  # sliding TTL
    return JsonResponse({"ok": True, "slot": slot})


# ── Existing gallery "wear by id" — unchanged ────────────────────────────────
@bonk_token_required
@require_POST
def wear_skin(request, skin_id: int):
    token = _get_session_token(request)  # guaranteed present by decorator
    slot = _resolve_slot(request)
    skin = get_object_or_404(Skin, id=skin_id)
    skin_code = skin.skin_code
    if not skin_code:
        return JsonResponse({"ok": False, "error": "skin_code_not_found"}, status=400)

    ok, err = _bonk_update_avatar(token, slot, skin_code)
    if not ok:
        return JsonResponse({"ok": False, "auth": "bonk", "error": err or "update_failed"}, status=401)

    _save_session_token(request, token)
    return JsonResponse({"ok": True, "slot": slot})