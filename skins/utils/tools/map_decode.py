import logging

import requests
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from core.ratelimits import limit

logger = logging.getLogger(__name__)


@limit("browse")
def map_decode_page(request):
    return render(request, "tools/map_decoder.html")


@require_http_methods(["POST"])
@limit("search")
def api_map_decode(request):
    encoded = (request.POST.get("encoded") or "").strip()
    if not encoded:
        return JsonResponse({"error": "Missing encoded map string"}, status=400)

    base_url = settings.DECODER_SERVICE_URL
    if not base_url:
        return JsonResponse({"error": "Map decoder is not available right now"}, status=503)

    headers = {"Content-Type": "application/json"}
    key = settings.DECODER_SERVICE_KEY
    if key:
        headers["X-Decoder-Key"] = key

    try:
        r = requests.post(
            f"{base_url}/decode/map",
            json={"encoded": encoded},
            headers=headers,
            timeout=15,
        )
    except requests.RequestException:
        logger.warning("map decoder unreachable", exc_info=True)
        return JsonResponse({"error": "Decoder service unreachable"}, status=502)

    # Pass through JSON (and status)
    try:
        data = r.json()
    except ValueError:
        return JsonResponse(
            {"error": "Decoder returned non-JSON", "raw": r.text[:2000]}, status=502
        )

    return JsonResponse(data, status=r.status_code)
