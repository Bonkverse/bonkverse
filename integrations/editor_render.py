"""The skin editor's render service (`/api/render-bundle` on editor.bonkverse.io).

Owns: the request shape for rendering a skin code into SVG + PNG + thumbnail,
the timeout, decoding the PNGs from base64, and turning every failure into a
`RenderResult` with an error instead of an exception.
Does not own: undoing URL-encoding on stored codes (core/bonk SkinCode), SVG
safety checks, files on disk or database rows.

Free of Django at import time; `render_skin_code()` reads the URL from settings.
"""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = (5.0, 30.0)  # (connect, read) seconds
RENDER_SIZE = 512


@dataclass(frozen=True)
class RenderedSkin:
    svg: str
    png: bytes
    thumbnail: bytes


@dataclass(frozen=True)
class RenderResult:
    skin: RenderedSkin | None = None
    error: str | None = None  # short reason for logs


def render(base_url: str, skin_code: str, *, timeout=DEFAULT_TIMEOUT) -> RenderResult:
    """Render a plain (not URL-encoded) skin code. Never raises for network or reply problems."""
    try:
        response = requests.post(
            f"{base_url}/api/render-bundle",
            json={"skinCode": skin_code, "size": RENDER_SIZE},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning("render service unreachable: %s", type(exc).__name__)
        return RenderResult(error="render_unreachable")

    if not response.ok:
        logger.warning("render service returned %s", response.status_code)
        return RenderResult(error=f"render_status_{response.status_code}")

    try:
        data = response.json()
    except ValueError:
        return RenderResult(error="render_bad_json")

    if not data.get("ok"):
        return RenderResult(error=f"render_refused: {data.get('error', 'unknown')}")

    svg = data.get("svg")
    png_b64 = data.get("pngBase64")
    if not svg or not png_b64:
        return RenderResult(error="render_missing_fields")

    try:
        png = base64.b64decode(png_b64, validate=True)
        thumb_b64 = data.get("thumbnailBase64")
        thumbnail = base64.b64decode(thumb_b64, validate=True) if thumb_b64 else png
    except (binascii.Error, ValueError):
        return RenderResult(error="render_bad_media")

    return RenderResult(skin=RenderedSkin(svg=svg, png=png, thumbnail=thumbnail))


def render_skin_code(skin_code: str) -> RenderResult:
    """`render` against the configured editor (settings.BONKVERSE_RENDER_URL)."""
    from django.conf import settings

    return render(settings.BONKVERSE_RENDER_URL, skin_code)
