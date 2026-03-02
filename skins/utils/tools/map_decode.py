import os
import requests

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt


def map_decode_page(request):
    return render(request, "tools/map_decoder.html")


@require_http_methods(["POST"])
def api_map_decode(request):
    encoded = (request.POST.get("encoded") or "").strip()
    if not encoded:
        return JsonResponse({"error": "Missing encoded map string"}, status=400)

    base_url = os.environ.get("DECODER_SERVICE_URL", "").rstrip("/")
    if not base_url:
        return JsonResponse({"error": "DECODER_SERVICE_URL not configured"}, status=500)

    headers = {"Content-Type": "application/json"}
    key = os.environ.get("DECODER_SERVICE_KEY")
    if key:
        headers["X-Decoder-Key"] = key

    try:
        r = requests.post(
            f"{base_url}/decode/map",
            json={"encoded": encoded},
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as e:
        return JsonResponse({"error": "Decoder service unreachable", "details": str(e)}, status=502)

    # Pass through JSON (and status)
    try:
        data = r.json()
    except ValueError:
        return JsonResponse({"error": "Decoder returned non-JSON", "raw": r.text[:2000]}, status=502)

    return JsonResponse(data, status=r.status_code)