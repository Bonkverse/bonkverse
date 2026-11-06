"""The map decoder service: turning an encoded bonk.io map string into JSON.

Owns: the `POST /decode/map` request, the optional `X-Decoder-Key` header,
the timeout, and sorting the reply into decoded / rejected input / no
usable answer. Every call returns a `DecodeResult` instead of raising.
Does not own: the Tools page or what it shows (skins/utils/tools/map_decode.py).

Free of Django at import time; `decode_map_configured()` reads the URL and
key from settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = (3.0, 15.0)  # (connect, read) seconds
_DETAIL_LENGTH = 300


class DecodeError:
    """`DecodeResult.error` codes."""

    NOT_CONFIGURED = "not_configured"  # no DECODER_SERVICE_URL here
    REJECTED = "rejected"  # decoder answered 4xx: the map string is the problem
    UNAVAILABLE = "unavailable"  # unreachable, 5xx, or not JSON


@dataclass(frozen=True)
class DecodeResult:
    data: Any = None  # the decoded map, on success
    error: str | None = None
    # With REJECTED: the decoder's own short explanation of what's wrong with
    # the input (safe to show; it describes the person's own string).
    detail: str = ""


def decode_map(
    base_url: str, encoded: str, *, key: str = "", timeout=DEFAULT_TIMEOUT
) -> DecodeResult:
    if not base_url:
        return DecodeResult(error=DecodeError.NOT_CONFIGURED)

    headers = {"X-Decoder-Key": key} if key else {}
    try:
        response = requests.post(
            f"{base_url}/decode/map", json={"encoded": encoded}, headers=headers, timeout=timeout
        )
    except requests.RequestException as exc:
        logger.warning("map decoder: unreachable: %s", type(exc).__name__)
        return DecodeResult(error=DecodeError.UNAVAILABLE)

    try:
        data = response.json()
    except ValueError:
        logger.warning("map decoder: non-JSON reply, http=%s", response.status_code)
        return DecodeResult(error=DecodeError.UNAVAILABLE)

    if response.ok:
        return DecodeResult(data=data)
    if 400 <= response.status_code < 500:
        return DecodeResult(error=DecodeError.REJECTED, detail=_detail(data))
    logger.warning("map decoder: http=%s", response.status_code)
    return DecodeResult(error=DecodeError.UNAVAILABLE)


def decode_map_configured(encoded: str) -> DecodeResult:
    """`decode_map` against settings.DECODER_SERVICE_URL / DECODER_SERVICE_KEY."""
    from django.conf import settings

    return decode_map(settings.DECODER_SERVICE_URL, encoded, key=settings.DECODER_SERVICE_KEY)


def _detail(data: Any) -> str:
    """The decoder's explanation, if it gave a short text one."""
    if not isinstance(data, dict):
        return ""
    for field in ("details", "error", "message"):
        value = data.get(field)
        if isinstance(value, str) and value:
            return value[:_DETAIL_LENGTH]
    return ""
