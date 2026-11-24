"""Wearing skins on bonk.io from Bonkverse.

Owns: the wear endpoints (gallery skin by id, unsaved editor skin by code) and
the in-page bonk.io login used when the player's bonk.io account needs
connecting. Tokens come only from the token broker (accounts/bonk_tokens.py),
which refreshes an expired one with the remember-me token when it can.
A wear into the player's active slot is recorded as the skin they wear
(players.services.record_worn_skin).
Does not own: the bonk.io session rules (core/bonk/session.py) or the HTTP
calls to bonk.io (integrations/bonk_api.py).

JSON contract the frontend relies on (tests/test_wear.py):
- 401 with auth="bonkverse" -> sign in to the site
- 401 with auth="bonk"      -> show the bonk.io login modal (no linked
                               account, or the broker needs the password)
- 401 without auth          -> the bonk.io credentials were wrong
- any other failure         -> no modal; show `message` (a sentence):
    422 avatar_too_big   the skin is over bonk.io's size limit
    503 rate_limited     bonk.io is limiting skin changes from Bonkverse, or
                         its login pause is on (which stops wears and token
                         refreshes too)
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

from core.bonk import AvatarSlot
from core.token_crypto import bonk_session
from core.logs import mark_expected_error
from core.ratelimits import describe_wait, limit
from integrations.bonk_api import (
    AVATAR_UPDATE_SCRIPT,
    BonkAvatarUpdateResult,
    BonkError,
    get_client,
    rate_limit_cooldowns,
)

from accounts.services import (
    ReconnectNeeded,
    TokensPaused,
    TokensUnavailable,
    active_link,
    attempt_login,
    bot_check_site_key,
    connect_from_wear,
    login_failure_message,
    sign_in,
    usable_bonk_token,
)
from core.auth_guards import api_login_required
from players.services import WornSkinSource, forget_user_skin, record_worn_skin

from accounts.services import log_event
from skins.models import Skin

logger = logging.getLogger(__name__)


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
# While bonk.io's login pause is on, no wear is sent either: bonk.io restarts
# its block on any request during it (integrations/bonk_api.py, _Cooldowns).
_LOGIN_PAUSE_MESSAGE = (
    "bonk.io has paused Bonkverse for everyone, so this isn't your fault. Try again in {wait}."
)

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
        if rate_limit_cooldowns.login_paused():
            message = _LOGIN_PAUSE_MESSAGE
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


def _reconnect_response() -> JsonResponse:
    """The one reply that opens the bonk.io login popup."""
    return JsonResponse({"ok": False, "auth": "bonk"}, status=401)


def _paused_response(request, seconds: int) -> JsonResponse:
    """bonk.io is limiting Bonkverse; the token broker didn't ask it."""
    mark_expected_error(request)
    response = JsonResponse(
        {
            "ok": False,
            "error": BonkError.RATE_LIMITED,
            "message": _LOGIN_PAUSE_MESSAGE.format(wait=describe_wait(seconds)),
            "retry_after": seconds,
        },
        status=503,
    )
    response["Retry-After"] = str(seconds)
    return response


def _token_for(request, link, *, force_refresh=False) -> tuple[str | None, JsonResponse | None]:
    """A usable bonk.io token for `link` from the token broker, or the reply
    to send instead (popup, pause, or bonk.io unreachable)."""
    try:
        return usable_bonk_token(link, force_refresh=force_refresh), None
    except ReconnectNeeded:
        return None, _reconnect_response()
    except TokensPaused as paused:
        return None, _paused_response(request, paused.seconds)
    except TokensUnavailable:
        status, message = _WEAR_FAILURES[BonkError.UNAVAILABLE]
        return None, JsonResponse(
            {"ok": False, "error": BonkError.UNAVAILABLE, "message": message}, status=status
        )


def _wear(request, skin_code: str) -> tuple[AvatarSlot | None, JsonResponse | None]:
    """Send `skin_code` to the bonk.io account this browser acts as.

    The token comes from the token broker (accounts/bonk_tokens.py), which
    refreshes an expired one with the remember-me token when the player has
    one. If bonk.io refuses a token before its expiry ("token"), it's
    refreshed once and the wear tried again; never more.

    Returns the slot used, and an error response if bonk.io didn't apply it.
    """
    link = active_link(request)
    if link is None:
        return None, _reconnect_response()
    slot = AvatarSlot.choose(
        request.POST.get("slot"), link.active_slot or bonk_session(request).active_slot
    )
    with _wear_lock(request.user.pk) as acquired:
        if not acquired:
            return slot, JsonResponse(
                {"ok": False, "error": "wear_in_progress", "message": _IN_PROGRESS_MESSAGE},
                status=429,
            )
        token, refusal = _token_for(request, link)
        if refusal:
            return slot, refusal
        result = get_client().update_avatar(token, slot, skin_code)
        if result.error == BonkError.TOKEN_REJECTED:
            token, refusal = _token_for(request, link, force_refresh=True)
            if refusal:
                return slot, refusal
            result = get_client().update_avatar(token, slot, skin_code)
    if not result.ok:
        # integrations/bonk_api.py logs bonk.io's refusal code.
        return slot, _update_failed_response(request, result)
    if link.active_slot is not None and slot.number == link.active_slot:
        # Only the active slot is what the player wears in game. A failure
        # here must not turn a skin bonk.io applied into an error reply.
        try:
            if record_worn_skin(link.bonk_player.bonk_id, skin_code, WornSkinSource.WEAR):
                forget_user_skin(request.user)
        except Exception:
            logger.exception("could not record the worn skin after a wear")
    return slot, None


@api_login_required
@require_POST
@limit("login", method="POST")
def bonk_login_for_wear(request):
    """The Wear popup's bonk.io login: connect (or reconnect) an account.

    Logging in to a different bonk.io account than the one in use adds it to
    the player's accounts and switches to it (`switched_to` in the reply), so
    the Wear goes to the account they just typed the password for.

    With "Keep me connected for Wear" ticked (`bonk_remember`), the link keeps
    a remember-me token and the popup shouldn't be needed again on this
    account until bonk.io revokes it.
    """
    bonk_username = request.POST.get("bonk_username")
    password = request.POST.get("bonk_password")
    if not bonk_username or not password:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)
    remember = request.POST.get("bonk_remember") in ("1", "on", "true")

    attempt = attempt_login(request, bonk_username, password, via="wear", remember=remember)
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
        # The next try must pass the "not a bot" check: the popup shows it
        # (core/js/bv-wear.js).
        site_key = bot_check_site_key(request)
        if site_key:
            body["bot_check"] = site_key
        return JsonResponse(body, status=401)

    result = attempt.result
    active_slot = result.active_slot.number if result.active_slot else None

    if result.username.value.casefold() != request.user.username.casefold():
        # Another of the player's bonk.io accounts: the password proves it's
        # theirs, so it joins their group and becomes the account in use, as
        # "Add account" does (RFC-0003 phase 5). Never linked to this site
        # account: each bonk.io account is its own site account.
        sign_in(request, result, remember=remember, add=True)
        return JsonResponse(
            {"ok": True, "active_slot": active_slot, "switched_to": request.user.username}
        )

    bonk = bonk_session(request)
    # The account this browser now acts as; its tokens live on the link.
    bonk.store_identity(result.username.value, result.bonk_id)
    bonk.store_active_slot(result.active_slot)
    try:
        connect_from_wear(request.user, result, remember=remember)
    except Exception:
        logger.exception("could not link the account after a wear login")
    try:
        if record_worn_skin(result.bonk_id, result.skin_code, WornSkinSource.LOGIN):
            forget_user_skin(request.user)
    except Exception:
        logger.exception("could not record the worn skin after a wear login")
    return JsonResponse({"ok": True, "active_slot": active_slot})


@api_login_required
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


@api_login_required
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
