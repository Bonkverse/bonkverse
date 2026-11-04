"""BLSkinFetcher: the Railway service that reads a BonkLeagues link and renders the skin.

Owns: the request shape for `/api/getSkin?link=...&media=true`, the timeout,
decoding the rendered PNGs from base64, and turning every failure into a
`FetchResult` with an error instead of an exception.
Does not own: checking the SVG is safe, files on disk or database rows
(skins/skin_import.py does those).

Free of Django at import time; `fetch_skin()` reads the URL from settings.
"""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = (5.0, 30.0)  # (connect, read) seconds; rendering can be slow


@dataclass(frozen=True)
class FetchedSkin:
    skin_code: str
    svg: str
    png: bytes
    thumbnail: bytes


@dataclass(frozen=True)
class FetchResult:
    skin: FetchedSkin | None = None
    error: str | None = None  # short reason for logs, never shown to players as-is


def fetch(url: str, link: str, *, timeout=DEFAULT_TIMEOUT) -> FetchResult:
    """Fetch and render one BonkLeagues skin. Never raises for network or reply problems."""
    try:
        response = requests.get(url, params={"link": link, "media": "true"}, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("skin fetcher unreachable: %s", type(exc).__name__)
        return FetchResult(error="fetcher_unreachable")

    if response.status_code != 200:
        logger.warning("skin fetcher returned %s for %s", response.status_code, link)
        return FetchResult(error=f"fetcher_status_{response.status_code}")

    try:
        data = response.json()
    except ValueError:
        return FetchResult(error="fetcher_bad_json")

    media = data.get("media") or {}
    skin_code = data.get("skinCode")
    svg = media.get("svg")
    png_b64 = media.get("pngBase64")
    if not skin_code or not svg or not png_b64:
        return FetchResult(error="fetcher_missing_fields")

    try:
        png = base64.b64decode(png_b64, validate=True)
        thumb_b64 = media.get("thumbnailBase64")
        thumbnail = base64.b64decode(thumb_b64, validate=True) if thumb_b64 else png
    except (binascii.Error, ValueError):
        return FetchResult(error="fetcher_bad_media")

    return FetchResult(skin=FetchedSkin(skin_code=skin_code, svg=svg, png=png, thumbnail=thumbnail))


def fetch_skin(link: str) -> FetchResult:
    """`fetch` against the configured service (settings.BLSKIN_FETCHER_URL)."""
    from django.conf import settings

    return fetch(settings.BLSKIN_FETCHER_URL, link)
