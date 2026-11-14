"""Matchmaking: the "coming soon" page and a pass-through to the BonkBot API.

Owns: forwarding a join-matchmaking request to BonkBot and relaying its answer.
Does not own: the HTTP call (integrations/bonkbot.py) or matchmaking itself
(the BonkBot service).
"""

import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.ratelimits import limit
from integrations.bonkbot import join_matchmaking_configured


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

    reply = join_matchmaking_configured(payload)
    if not reply.ok:
        return JsonResponse({"error": "matchmaking_unavailable"}, status=502)
    return JsonResponse(reply.body, status=reply.status, safe=False)


@limit("browse")
def matchmaking_page(request):
    return render(request, "skins/matchmaking.html")
