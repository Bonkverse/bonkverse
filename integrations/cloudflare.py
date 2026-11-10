"""Cloudflare's API: purging files from the edge cache.

Owns: the purge request shape, the API token header, the timeout, reading
Cloudflare's `{"success": ..., "errors": [...]}` reply, and keeping the token
out of logs. Every call returns a `PurgeResult` instead of raising.
Does not own: which files changed (the caller says) or the cache rules
themselves (set in the Cloudflare dashboard, see docs/operations/).

Free of Django at import time; `purge_media_paths()` reads the zone, token
and site URL from settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.cloudflare.com/client/v4"
DEFAULT_TIMEOUT = (3.0, 10.0)  # (connect, read) seconds
# Cloudflare accepts at most 30 URLs per purge-by-URL request on every plan.
MAX_FILES_PER_REQUEST = 30


@dataclass(frozen=True)
class PurgeResult:
    """What happened to a purge.

    `skipped` means Cloudflare isn't configured here (local, CI), which is
    fine: cached copies expire on their own. `error` is a short reason for
    logs when Cloudflare was asked and the purge didn't happen.
    """

    ok: bool
    skipped: bool = False
    error: str | None = None


def purge_files(
    zone_id: str, api_token: str, urls: list[str], *, timeout=DEFAULT_TIMEOUT
) -> PurgeResult:
    """Remove `urls` (full URLs, at most 30) from Cloudflare's cache for one zone."""
    if not zone_id or not api_token:
        return PurgeResult(ok=False, skipped=True)
    if not urls:
        return PurgeResult(ok=True)
    if len(urls) > MAX_FILES_PER_REQUEST:
        raise ValueError(f"Cloudflare purges at most {MAX_FILES_PER_REQUEST} URLs per request")
    return _purge(zone_id, api_token, {"files": urls}, f"{len(urls)} files", timeout)


def purge_everything(zone_id: str, api_token: str, *, timeout=DEFAULT_TIMEOUT) -> PurgeResult:
    """Empty Cloudflare's whole cache for one zone (every page, script and image).

    For changes too big to list file by file, like re-rendering every skin.
    The cache refills from the site as visitors ask for things.
    """
    if not zone_id or not api_token:
        return PurgeResult(ok=False, skipped=True)
    return _purge(zone_id, api_token, {"purge_everything": True}, "everything", timeout)


def _purge(zone_id: str, api_token: str, body: dict, what: str, timeout) -> PurgeResult:
    try:
        response = requests.post(
            f"{API_BASE}/zones/{zone_id}/purge_cache",
            headers={"Authorization": f"Bearer {api_token}"},
            json=body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning("cloudflare purge: unreachable: %s", type(exc).__name__)
        return PurgeResult(ok=False, error="unreachable")

    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.ok and data.get("success"):
        return PurgeResult(ok=True)

    # Codes only: Cloudflare's messages can echo the request, never the token,
    # but codes are all we need to look an error up.
    codes = [e.get("code") for e in data.get("errors") or [] if isinstance(e, dict)]
    logger.warning(
        "cloudflare purge failed | http=%s | error_codes=%s | purged=%s",
        response.status_code,
        codes,
        what,
    )
    return PurgeResult(ok=False, error=f"status_{response.status_code}")


def purge_whole_site() -> PurgeResult:
    """Empty Cloudflare's cache for bonkverse.io, using Django settings."""
    from django.conf import settings

    return purge_everything(settings.CLOUDFLARE_ZONE_ID, settings.CLOUDFLARE_CACHE_API_TOKEN)


def purge_media_paths(paths: list[str]) -> PurgeResult:
    """Purge site paths such as "/media/skins/1.png" using Django settings."""
    from django.conf import settings

    base = settings.BONKVERSE_BASE_URL
    return purge_files(
        settings.CLOUDFLARE_ZONE_ID,
        settings.CLOUDFLARE_CACHE_API_TOKEN,
        [f"{base}{path}" for path in paths],
    )
