"""Wearing skins on bonk.io from Bonkverse.

Owns: the wear endpoints (gallery skin by id, unsaved editor skin by code) and
the in-page bonk.io login used when the player's bonk.io token is missing.
A wear into the player's active slot is recorded as the skin they wear
(players.services.record_worn_skin).
Does not own: the bonk.io session rules (core/bonk/session.py) or the HTTP
calls to bonk.io (integrations/bonk_api.py).

JSON contract the frontend relies on (tests/test_wear.py):
- 401 with auth="bonkverse" -> sign in to the site
- 401 with auth="bonk"      -> show the bonk.io login modal
- 401 without auth          -> the bonk.io credentials were wrong
- any other failure         -> no modal; show `message` (a sentence):
    422 avatar_too_big   the skin is over bonk.io's size limit
    503 rate_limited     bonk.io is limiting skin changes from Bonkverse
                         (+ retry_after seconds and a Retry-After header, and
                         the wait in `message`)
    429 wear_in_progress this account already has a wear waiting on bonk.io
    429 rate_limited     this account wore too many skins too fast (core/ratelimits)
    502 network_error    bonk.io couldn't be reached
    502 rejected         a refusal code we don't recognise (logged)

Only bonk.io's "token" refusal opens the login modal. Treating every refusal
as an expired token made the modal reappear forever for a too-big skin, and
every time bonk.io was rate-limiting the server (docs/bonk/api.md). The pages'
side of this contract is static/core/js/bv-wear.js.

Spam protection (incident 2026-11-09): bonk.io limits the server's single
outbound IP, so one player's click-spam paused wearing for everyone. Three
layers keep one account from spending that shared budget, all in Redis so
every gunicorn worker sees them:
1. One wear in flight per account (`_wear_lock`): double-clicks and parallel
   tabs get 429 wear_in_progress instead of a second bonk.io call.
2. Per-account rate tiers "wear_burst" and "wear" (settings.RATE_LIMITS),
   shared by both wear endpoints.
3. The bonk.io cooldown (integrations/bonk_api.py): after "ratelimited", no
   worker calls avatar_update.php until it ends. It grows with each limit in
   a row, and `retry_after` tells the page how long it has left.
"""

import logging
import math
from contextlib import contextmanager

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from core.bonk import AvatarSlot, BonkSession
from core.logs import mark_expected_error
from core.ratelimits import describe_wait, limit
from integrations.bonk_api import (
    AVATAR_UPDATE_SCRIPT,
    BonkAvatarUpdateResult,
    BonkError,
    get_client,
    rate_limit_cooldowns,
)

from accounts.services import attempt_login, login_failure_message
from core.auth_guards import api_login_required, bonk_token_required
from players.services import WornSkinSource, forget_user_skin, record_worn_skin

from .events import log_event
from .models import Skin

logger = logging.getLogger(__name__)


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
        "bonk.io is limiting skin changes from Bonkverse right now. Try again in {wait}.",
    ),
    BonkError.UNAVAILABLE: (502, "bonk.io isn't responding. Try again in a minute."),
}
_UNKNOWN_FAILURE = (502, "bonk.io didn't accept this skin.")

# Both wear endpoints share one per-account counter.
_WEAR_GROUP = "skins.wear"

# Longest a wear can hold its account's lock: longer than the bonk.io
# (connect + read) timeout, so a stuck call can't lock an account for good.
_WEAR_LOCK_SECONDS = 15
_IN_PROGRESS_MESSAGE = "Still applying your last skin. Give it a second."


@contextmanager
def _wear_lock(user_id):
    """Hold this account's one-wear-at-a-time lock.

    Yields True if this request holds the lock (or the cache is down, in which
    case we let the wear through rather than block everyone), False if another
    wear for the account is still waiting on bonk.io.

    cache.add is atomic (Redis SET NX): of several requests arriving in the
    same instant, exactly one gets True. A plain "read, then write" check is
    what let bursts through before.
    """
    key = f"wear:inflight:{user_id}"
    try:
        added = cache.add(key, 1, timeout=_WEAR_LOCK_SECONDS)
    except Exception:
        added = None
    if added is False:
        yield False
        return
    try:
        yield True
    finally:
        if added:
            try:
                cache.delete(key)
            except Exception:
                pass


def retry_after_for(script: str) -> int | None:
    """Whole seconds until `script` may be called again, or None if it may now."""
    return math.ceil(rate_limit_cooldowns.remaining(script)) or None


def _update_failed_response(request, result: BonkAvatarUpdateResult) -> JsonResponse:
    """The JSON reply when bonk.io didn't apply the skin."""
    if result.error == BonkError.TOKEN_REJECTED:
        # The one case a fresh bonk.io login fixes: open the login modal.
        return JsonResponse({"ok": False, "auth": "bonk", "error": result.error}, status=401)
    status, message = _WEAR_FAILURES.get(result.error, _UNKNOWN_FAILURE)
    retry_after = None
    if result.error == BonkError.RATE_LIMITED:
        # How long every worker will keep answering this without asking bonk.io,
        # so the page can wait instead of retrying into the pause.
        retry_after = retry_after_for(AVATAR_UPDATE_SCRIPT)
        message = message.format(wait=describe_wait(retry_after))
        # Expected, and integrations/bonk_api.py already logged it as a
        # WARNING; don't also log "ERROR Service Unavailable" (or send it to
        # Sentry) for every one.
        mark_expected_error(request)
    # No auth tag, so the page shows `message` and never opens the modal.
    body = {"ok": False, "error": result.error, "message": message}
    if retry_after:
        body["retry_after"] = retry_after
    response = JsonResponse(body, status=status)
    if retry_after:
        response["Retry-After"] = str(retry_after)
    return response


def _wear(request, skin_code: str) -> tuple[AvatarSlot, JsonResponse | None]:
    """Send `skin_code` to the player's bonk.io account.

    Returns the slot used, and an error response if bonk.io didn't apply it.
    """
    bonk = BonkSession(request.session)
    token = bonk.token  # guaranteed present by bonk_token_required
    slot = _resolve_slot(request)
    with _wear_lock(request.user.pk) as acquired:
        if not acquired:
            return slot, JsonResponse(
                {"ok": False, "error": "wear_in_progress", "message": _IN_PROGRESS_MESSAGE},
                status=429,
            )
        result = get_client().update_avatar(token, slot, skin_code)
    if not result.ok:
        # integrations/bonk_api.py logs bonk.io's refusal code.
        return slot, _update_failed_response(request, result)
    bonk.store_token(token)  # sliding TTL
    if slot == bonk.active_slot:
        # Only the active slot is what the player wears in game. A failure
        # here must not turn a skin bonk.io applied into an error reply.
        try:
            if record_worn_skin(bonk.bonk_id, skin_code, WornSkinSource.WEAR):
                forget_user_skin(request.user)
        except Exception:
            logger.exception("could not record the worn skin after a wear")
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

    attempt = attempt_login(request, bonk_username, password, via="wear")
    if not attempt.ok:
        # Bad bonk credentials (or held for too many) — 401 WITHOUT an `auth`
        # tag so the client treats it as a credential error, not a
        # session-expired redirect.
        retry_after = attempt.retry_after
        body = {
            "ok": False,
            "error": attempt.error,
            "message": login_failure_message(attempt.error, retry_after),
        }
        if retry_after:
            body["retry_after"] = retry_after
        return JsonResponse(body, status=401)

    result = attempt.result

    bonk = BonkSession(request.session)
    bonk.store_token(result.token)
    # The account this token belongs to, which wears record their skin on.
    bonk.store_identity(result.username.value, result.bonk_id)
    bonk.store_active_slot(result.active_slot)
    try:
        if record_worn_skin(result.bonk_id, result.skin_code, WornSkinSource.LOGIN):
            forget_user_skin(request.user)
    except Exception:
        logger.exception("could not record the worn skin after a wear login")
    active_slot = result.active_slot.number if result.active_slot else None
    return JsonResponse({"ok": True, "active_slot": active_slot})


@bonk_token_required
@require_POST
@limit("wear_burst", key="user_or_ip", group=_WEAR_GROUP)
@limit("wear", key="user_or_ip", group=_WEAR_GROUP)
def wear_skin_code(request):
    """Wear an unsaved editor skin from a raw skin_code (no DB row)."""
    skin_code = request.POST.get("skin_code")
    if not skin_code:
        return JsonResponse({"ok": False, "error": "skin_code_not_found"}, status=400)

    slot, error_response = _wear(request, skin_code)
    if error_response:
        return error_response
    log_event(request.user, "skin_worn", metadata={"source": "editor_unsaved"})
    return JsonResponse({"ok": True, "slot": slot.number})


@bonk_token_required
@require_POST
@limit("wear_burst", key="user_or_ip", group=_WEAR_GROUP)
@limit("wear", key="user_or_ip", group=_WEAR_GROUP)
def wear_skin(request, skin_id: int):
    """Wear a gallery skin by id in the requested (or active) slot."""
    skin = get_object_or_404(Skin, id=skin_id)
    if not skin.skin_code:
        return JsonResponse({"ok": False, "error": "skin_code_not_found"}, status=400)

    slot, error_response = _wear(request, skin.skin_code)
    if error_response:
        return error_response
    log_event(request.user, "skin_worn", skin=skin)
    return JsonResponse({"ok": True, "slot": slot.number})
