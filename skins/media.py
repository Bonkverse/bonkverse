"""Serving uploaded and rendered skin files (/media/...).

Owns: rate limiting and cache headers for media files served by Django.
Does not own: writing those files (upload.py, rerender.py, apis/publish_skin.py).

On 2026-11-03 one client fetched ~30k skin images in under an hour (1.9 GB),
each URL once, so Cloudflare's cache could not absorb it and every request
reached Django, which served /media/ with no limit at all.
"""

from django.conf import settings
from django.views.static import serve

from core.ratelimits import limit

# Browsers keep a file for an hour; Cloudflare's edge for a week. Re-render
# purges the edge copy (rerender.purge_cloudflare_cache), so a week is safe.
MEDIA_CACHE_CONTROL = "public, max-age=3600, s-maxage=604800"


@limit("media")
def serve_media(request, path):
    """Serve a file from MEDIA_ROOT, rate-limited per visitor IP.

    Only successful responses get cache headers; a 404 raises before that, so
    a missing file is never cached at the edge.
    """
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    response["Cache-Control"] = MEDIA_CACHE_CONTROL
    return response
