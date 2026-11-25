"""Serving uploaded and rendered skin files (/media/...).

Owns: rate limiting, cache headers and the sandbox CSP for media files
served by Django.
Does not own: writing those files (skin_media.py).

On 2026-11-03 one client fetched ~30k skin images in under an hour (1.9 GB),
each URL once, so Cloudflare's cache could not absorb it and every request
reached Django, which served /media/ with no limit at all.
"""

from django.conf import settings
from django.views.static import serve

from core.ratelimits import limit

# Browsers keep a file for an hour; Cloudflare's edge for a week. Re-render
# purges the edge copy (integrations/cloudflare.py), so a week is safe.
MEDIA_CACHE_CONTROL = "public, max-age=3600, s-maxage=604800"

# A skin's SVG opened on its own is a document on this site's origin. The
# sanitizer (svg_sanitizer.py) keeps script out of uploads; this makes sure a
# file that ever got past it still can't do anything: no scripts, forms,
# plugins or popups (sandbox), and nothing loaded but its own inline styles and
# data: images. Has no effect where skins are shown with <img>.
MEDIA_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"


@limit("media")
def serve_media(request, path):
    """Serve a file from MEDIA_ROOT, rate-limited per visitor IP.

    Only successful responses get cache headers; a 404 raises before that, so
    a missing file is never cached at the edge.
    """
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    response["Cache-Control"] = MEDIA_CACHE_CONTROL
    response["Content-Security-Policy"] = MEDIA_CSP
    return response
