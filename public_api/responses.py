"""The reply envelope for the public API (RFC-0001's JSON contract).

    {"ok": true, "data": {...}}
    {"ok": false, "error": "not_found"}

Error codes are snake_case and stable: callers branch on them, so renaming
one is a breaking change. `auth` appears only on 401s; extra fields (such as
`retry_after` on 429s) may be added at any time.
"""

from django.http import JsonResponse

API_VERSION = "1"


def ok(data, *, status=200, cache_seconds=None):
    response = JsonResponse({"ok": True, "data": data}, status=status)
    response["X-Bonkverse-API-Version"] = API_VERSION
    if cache_seconds:
        # Private: the reply is for one key, and shared caches must not hand
        # it to a request without one.
        response["Cache-Control"] = f"private, max-age={cache_seconds}"
    return response


def fail(error, status, *, auth=None, **extra):
    body = {"ok": False, "error": error}
    if auth:
        body["auth"] = auth
    body.update(extra)
    response = JsonResponse(body, status=status)
    response["X-Bonkverse-API-Version"] = API_VERSION
    return response
