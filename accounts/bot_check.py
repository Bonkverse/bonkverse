"""The "not a bot" check (Cloudflare Turnstile) on bonk.io logins.

Owns: when a login must pass the check, and checking the answer.
Does not own: the Cloudflare call (integrations/turnstile.py), the login
guards it adds to (login_attempts.py), or the widget on the pages
(accounts/templates/accounts/login.html, core/js/bv-wear.js).

Why (RFC-0003 Part 1, item 10): on 2026-11-10 a bot logged in 10 new
accounts 17 times in 100 s, each from a different IP, and bonk.io paused
logins for everyone. Per-visitor limits can't catch IP rotation. The check
is shown only when it's likely to matter, so most players never see it: the
visitor already had a wrong password or unknown username, or the site is
close to its wrong-password budget or its per-minute cap.

Off until TURNSTILE_SECRET_KEY is set. If Cloudflare can't be reached, the
login goes ahead: the check is one guard of several and must never be the
reason nobody can log in.
"""

from __future__ import annotations

import logging

from django.conf import settings

from core.client_ip import client_ip
from integrations import turnstile

from .login_attempts import looks_risky

logger = logging.getLogger("skins.login")


def enabled() -> bool:
    return bool(settings.TURNSTILE_SECRET_KEY and settings.TURNSTILE_SITE_KEY)


def wanted(request) -> bool:
    """Whether this visitor's next login must pass the check."""
    return enabled() and looks_risky(request)


def site_key_if_wanted(request) -> str | None:
    """The public site key for the page's widget, or None when not needed."""
    return settings.TURNSTILE_SITE_KEY if wanted(request) else None


def passes(request) -> bool:
    """Whether the request carries a genuine answer (or Cloudflare is down)."""
    result = turnstile.verify(
        settings.TURNSTILE_SECRET_KEY,
        request.POST.get(turnstile.RESPONSE_FIELD),
        client_ip(request),
    )
    if result.unavailable:
        logger.warning("bot check skipped: Cloudflare couldn't be asked")
        return True
    return result.ok
