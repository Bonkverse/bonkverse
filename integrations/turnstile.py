"""Cloudflare Turnstile: checking a "not a bot" answer from the login forms.

Owns: the siteverify request shape, the timeout, reading Cloudflare's
`{"success": ..., "error-codes": [...]}` reply, and keeping the secret out of
logs. Every call returns a `TurnstileResult` instead of raising.
Does not own: when a login needs the check (accounts/bot_check.py) or the
widget on the page (accounts/templates/accounts/login.html, core/js/bv-wear.js).

Free of Django at import time; `get_secret()` reads the secret from settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
DEFAULT_TIMEOUT = (3.0, 5.0)  # (connect, read) seconds
# The form field the Turnstile widget fills in inside the form it sits in.
RESPONSE_FIELD = "cf-turnstile-response"


@dataclass(frozen=True)
class TurnstileResult:
    """Cloudflare's verdict on one answer.

    `unavailable` means Cloudflare couldn't be asked (network error, bad
    reply). Callers let the login through then: the check is one guard of
    several, and it must never be the reason nobody can log in.
    """

    ok: bool
    unavailable: bool = False
    error_codes: tuple[str, ...] = field(default=())


def verify(
    secret: str, response: str | None, remote_ip: str | None = None, *, timeout=DEFAULT_TIMEOUT
):
    """Ask Cloudflare whether `response` (the widget's answer) is genuine.

    An empty `response` fails without a call: the visitor didn't do the check.
    """
    if not response:
        return TurnstileResult(ok=False, error_codes=("missing-input-response",))
    form = {"secret": secret, "response": response}
    if remote_ip:
        form["remoteip"] = remote_ip
    try:
        reply = requests.post(SITEVERIFY_URL, data=form, timeout=timeout)
        data = reply.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("turnstile siteverify unreachable: %s", type(exc).__name__)
        return TurnstileResult(ok=False, unavailable=True)
    if not isinstance(data, dict):
        logger.warning("turnstile siteverify gave no usable answer | http=%s", reply.status_code)
        return TurnstileResult(ok=False, unavailable=True)
    codes = tuple(str(code) for code in data.get("error-codes") or ())
    if data.get("success") is True:
        return TurnstileResult(ok=True)
    # A wrong or missing secret is our setup, not the visitor's answer.
    if any(code in ("missing-input-secret", "invalid-input-secret") for code in codes):
        logger.error("turnstile secret rejected by Cloudflare | codes=%s", ",".join(codes))
        return TurnstileResult(ok=False, unavailable=True, error_codes=codes)
    return TurnstileResult(ok=False, error_codes=codes)
