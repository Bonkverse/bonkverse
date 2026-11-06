"""The Map Decoder tool page and its API.

Owns: the /tools/map-decode/ page and /api/tools/map-decode/, input checks,
and what the page is told when decoding fails.
Does not own: the decoder service call (integrations/map_decoder.py).

The page shows `error` (and `details`, when present) as-is, so both are
sentences meant for people. Service internals stay in the server log.
"""

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from core.ratelimits import limit
from integrations.map_decoder import DecodeError, decode_map_configured


@limit("browse")
def map_decode_page(request):
    return render(request, "tools/map_decoder.html")


@require_http_methods(["POST"])
@limit("search")
def api_map_decode(request):
    encoded = (request.POST.get("encoded") or "").strip()
    if not encoded:
        return JsonResponse({"error": "Missing encoded map string"}, status=400)

    result = decode_map_configured(encoded)

    if result.error == DecodeError.NOT_CONFIGURED:
        return JsonResponse({"error": "Map decoder is not available right now"}, status=503)
    if result.error == DecodeError.REJECTED:
        body = {"error": "Couldn't decode that map string."}
        if result.detail:
            body["details"] = result.detail
        return JsonResponse(body, status=400)
    if result.error:
        return JsonResponse(
            {"error": "The map decoder isn't responding. Try again in a minute."}, status=502
        )
    return JsonResponse(result.data, status=200, safe=False)
