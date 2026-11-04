"""Skin submissions from BonxBot, the Bonkverse Discord bot.

Owns: POST /api/bot/skins/ — the bot's shared-secret check, reading its JSON,
and mapping import results to status codes the bot can act on (2xx = stored,
4xx = will never work so stop retrying, 5xx = try again later).
Does not own: rendering or storing the skin (skins/skin_import.py).

Request:  Authorization: Bearer <BONXBOT_API_TOKEN>
          {"link": "...", "name": "...", "creator": "...", "skin_code": "...",
           "discord_user_id": 123, "bonx_skin_id": 45}
          With skin_code the editor renders the skin and BonkLeagues is never
          contacted; without it, the link is read from BonkLeagues.
Response: 201 created / 200 already on Bonkverse, both {"created", "skin": {...}};
          otherwise {"error": "<code>", "retryable": bool}.
"""

import hmac
import json

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.ratelimits import limit
from skins.events import log_event
from skins.skin_import import ImportFailure, import_bonkleagues_skin

ERROR_STATUS = {
    ImportFailure.INVALID_LINK: 422,
    ImportFailure.LINK_TOO_LONG: 422,
    ImportFailure.UNSAFE_SVG: 422,
    ImportFailure.RENDER_FAILED: 502,
    ImportFailure.FETCH_FAILED: 502,
    ImportFailure.STORAGE_FAILED: 500,
}


def _bot_authorized(request) -> bool:
    expected = settings.BONXBOT_API_TOKEN
    given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def _error(code: str, status: int) -> JsonResponse:
    return JsonResponse({"error": code, "retryable": status >= 500}, status=status)


@csrf_exempt  # token-authenticated, no cookies involved
@limit("upload")
@require_POST
def submit_skin(request):
    if not _bot_authorized(request):
        return _error("unauthorized", 401)
    try:
        body = json.loads(request.body)
    except ValueError:
        return _error("bad_json", 400)
    if not isinstance(body, dict):
        return _error("bad_json", 400)

    result = import_bonkleagues_skin(
        body.get("link", ""),
        body.get("name"),
        body.get("creator"),
        skin_code=body.get("skin_code"),
    )
    if result.error:
        return _error(result.error, ERROR_STATUS[result.error])

    skin = result.skin
    if result.created:
        log_event(
            None,
            "skin_uploaded",
            skin=skin,
            source="discord",
            discord_user_id=body.get("discord_user_id"),
            bonx_skin_id=body.get("bonx_skin_id"),
        )
    payload = {
        "id": skin.id,
        "name": skin.name,
        "creator": skin.creator,
        "url": skin.get_absolute_url(),
    }
    return JsonResponse(
        {"created": result.created, "skin": payload}, status=201 if result.created else 200
    )
