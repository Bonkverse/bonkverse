"""Skin submissions from BonxBot, the Bonkverse Discord bot.

Owns: POST /api/bot/skins/ — the bot's shared-secret check, reading its JSON,
and mapping import results to status codes the bot can act on (2xx = stored,
4xx = will never work so stop retrying, 5xx = try again later).
Does not own: rendering or storing the skin (skins/skin_import.py).

Request:  Authorization: Bearer <BONXBOT_API_TOKEN>
          {"link": "...", "name": "...", "creator": "...", "skin_code": "...",
           "discord_user_id": 123, "bonx_skin_id": 45,
           "creator_source": "submitter" | "bonkleagues"}
          creator_source is optional (missing or anything else = unchecked).
          With skin_code the editor renders the skin and BonkLeagues is never
          contacted; without it, the link is read from BonkLeagues.
Response: 201 created / 200 already on Bonkverse, both {"created", "skin": {...}};
          otherwise {"error": "<code>", "retryable": bool}.
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.bot_auth import bot_authorized
from core.ratelimits import limit
from accounts.services import log_event
from skins.models import CreatorSource, SubmissionSource
from skins.skin_import import ImportFailure, import_bonkleagues_skin
from skins.submitters import Submission, discord_id_or_none

ERROR_STATUS = {
    ImportFailure.INVALID_LINK: 422,
    ImportFailure.LINK_TOO_LONG: 422,
    ImportFailure.UNSAFE_SVG: 422,
    ImportFailure.SVG_TOO_LARGE: 422,
    ImportFailure.INVALID_SKIN_CODE: 422,
    ImportFailure.RENDER_FAILED: 502,
    ImportFailure.FETCH_FAILED: 502,
    ImportFailure.STORAGE_FAILED: 500,
}


# What BonxBot may say about the creator. It decides with the same rule as the
# upload page (skins.submitters.resolve_creator): "submitter" = the user's own
# linked bonk.io account, "bonkleagues" = the BonkLeagues author, because the
# user said they didn't make it. BonxBot verifies the accounts (friend request);
# Bonkverse trusts the token-authenticated bot (owner decision, 2026-11-17).
_BOT_CREATOR_SOURCES = {CreatorSource.SUBMITTER, CreatorSource.BONKLEAGUES}


def _discord_submission(body: dict) -> Submission:
    """Anything else, including older BonxBot versions that don't say, is unchecked."""
    source = body.get("creator_source")
    return Submission(
        source=SubmissionSource.DISCORD,
        creator_source=(
            source
            if isinstance(source, str) and source in _BOT_CREATOR_SOURCES
            else CreatorSource.AS_ENTERED
        ),
        discord_user_id=discord_id_or_none(body.get("discord_user_id")),
    )


def _error(code: str, status: int) -> JsonResponse:
    return JsonResponse({"error": code, "retryable": status >= 500}, status=status)


@csrf_exempt  # token-authenticated, no cookies involved
@limit("upload")
@require_POST
def submit_skin(request):
    if not bot_authorized(request):
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
        submission=_discord_submission(body),
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
