"""Matchmaking: the "coming soon" page and a pass-through to the BonkBot API.

Owns: forwarding a join-matchmaking request to BonkBot and relaying its answer.
Does not own: matchmaking itself (lives in the BonkBot service).
"""

import json
import logging

import requests
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.ratelimits import limit

logger = logging.getLogger(__name__)

BONKBOT_JOIN_URL = "https://bonkbot-api-production.up.railway.app/join-matchmaking"
# (connect, read) seconds. Without a timeout a hung BonkBot held a web worker forever.
BONKBOT_TIMEOUT = (3, 10)


@csrf_exempt
@require_POST
@limit("write")
def join_matchmaking(request):
    """Forward the JSON body to BonkBot and return its JSON response and status.

    Errors are JSON too: 400 for a body that isn't JSON, 502 when BonkBot can't
    be reached or answers with something that isn't JSON. Error details stay in
    the server log rather than the response.
    """
    try:
        payload = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    try:
        response = requests.post(BONKBOT_JOIN_URL, json=payload, timeout=BONKBOT_TIMEOUT)
        return JsonResponse(response.json(), status=response.status_code, safe=False)
    except (requests.RequestException, ValueError):
        logger.warning("join-matchmaking: BonkBot unreachable or non-JSON reply", exc_info=True)
        return JsonResponse({"error": "matchmaking_unavailable"}, status=502)


@limit("browse")
def matchmaking_page(request):
    return render(request, "skins/matchmaking.html")
