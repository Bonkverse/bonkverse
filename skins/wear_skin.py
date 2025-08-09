# skins/wear_skin.py
import time, requests
from dataclasses import dataclass
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from urllib.parse import urlparse, parse_qs
from .models import Skin

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
BONK_AVATAR_UPDATE_URL = "https://bonk2.io/scripts/avatar_update.php"
TIMEOUT = 10

TOKEN_TTL = 14 * 24 * 60 * 60  # 14 days

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
            # Bonk returns 'activeAvatarNumber' (integer 1..3)
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

@login_required
@require_POST
def bonk_login_for_wear(request):
    u = request.POST.get("bonk_username")
    p = request.POST.get("bonk_password")
    if not u or not p:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)

    res = _bonk_login(u, p)
    if not res.ok:
        return JsonResponse({"ok": False, "error": res.error}, status=401)

    _save_session_token(request, res.token)
    _save_active_slot(request, res.active_slot)
    return JsonResponse({"ok": True, "active_slot": res.active_slot})

@login_required
@require_POST
def wear_skin(request, skin_id: int):
    token = _get_session_token(request)
    if not token:
        return JsonResponse({"ok": False, "need_login": True}, status=401)

    # Prefer explicit slot from client if ever provided, else use remembered active slot, else fallback to 3
    slot = request.POST.get("slot")
    if slot:
        try:
            slot = int(slot)
        except Exception:
            slot = None
    if slot not in (1, 2, 3, 4, 5):
        slot = _get_active_slot(request) or 3

    skin = get_object_or_404(Skin, id=skin_id)
    skin_code = _extract_skin_code(skin.image_url)
    if not skin_code:
        return JsonResponse({"ok": False, "error": "skin_code_not_found"}, status=400)

    ok, err = _bonk_update_avatar(token, slot, skin_code)
    if not ok:
        # token may be stale; force a fresh login
        return JsonResponse({"ok": False, "need_login": True, "error": err or "update_failed"}, status=401)

    # Sliding renewal of token TTL
    _save_session_token(request, token)
    # And if user switched active slot in-game, you may want to refresh later on login again.
    return JsonResponse({"ok": True, "slot": slot})
