"""Rate-limit tiers, the `limit` decorator, and the 429 response.

Owns: the named tiers views use (`@limit("browse")`), and what a visitor sees
when limited: an HTML page for browsers, the JSON error contract for API and
AJAX calls, both with a Retry-After header.
Does not own: which IP a request is from (core/client_ip.py) or the numbers for
each tier, which live in settings.RATE_LIMITS so they can change per environment.

Each decorated view keeps its own counter per visitor, so hitting the search
limit does not block the home page.
"""

import functools
import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from django.shortcuts import render
from django_ratelimit import ALL
from django_ratelimit.core import get_usage

logger = logging.getLogger(__name__)


def _rate_for(tier: str):
    """Rate callable for django-ratelimit, read at request time so settings overrides apply."""

    def rate(group, request):
        return settings.RATE_LIMITS[tier]

    return rate


def limit(tier: str, *, method=ALL, key="ip", group: str | None = None):
    """Rate-limit a view using a named tier from settings.RATE_LIMITS.

    Args:
        tier: Key in settings.RATE_LIMITS, e.g. "browse", "search", "write".
        method: HTTP method(s) that count toward the limit. Defaults to all.
            Use method="POST" when only submissions should count (login).
        key: Who gets their own counter. "ip" (default) for anonymous pages;
            "user_or_ip" for actions taken as a signed-in account, so one
            person can't spend the budget of a whole school or household and
            one household's busy player doesn't block the rest.
        group: Share one counter between several views (e.g. both wear
            endpoints). Defaults to a counter per view.

    Raises:
        ImproperlyConfigured: At import time, if the tier does not exist.
    """
    if tier not in settings.RATE_LIMITS:
        raise ImproperlyConfigured(f"Unknown rate-limit tier {tier!r}")
    shared_group = group

    def decorator(view):
        group = shared_group or f"{view.__module__}.{view.__qualname__}"

        @functools.wraps(view)
        def wrapped(request, *args, **kwargs):
            usage = get_usage(
                request,
                group=f"{group}:{tier}",
                key=key,
                rate=_rate_for(tier),
                method=method,
                increment=True,
            )
            if usage is not None and usage["should_limit"]:
                logger.info("rate limited: tier=%s view=%s", tier, group)
                return too_many_requests(request, retry_after=usage["time_left"], tier=tier)
            return view(request, *args, **kwargs)

        # Read by `manage.py audit_rate_limits` to list every route's limit.
        wrapped.rate_limit_tier = tier
        wrapped.rate_limit_method = method
        wrapped.rate_limit_key = key
        return wrapped

    return decorator


def _wants_json(request) -> bool:
    """API and AJAX callers get JSON; browsers navigating to a page get HTML."""
    if request.path.startswith("/api/"):
        return True
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return True
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


def _describe_wait(seconds: int | None) -> str:
    """Human wait time: "42 seconds", "about 3 minutes", or "a minute" when unknown."""
    if not seconds or seconds <= 0:
        return "a minute"
    if seconds < 90:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    return f"about {round(seconds / 60)} minutes"


# Tiers whose 429 page also invites the visitor to ask for bulk access. Only
# someone collecting skins in bulk gets near the media limit (2026-11-03 scrape).
BULK_ACCESS_TIERS = {"media"}


def too_many_requests(request, *, retry_after: int | None = None, tier: str | None = None):
    """Build the 429 response for a rate-limited request.

    Args:
        request: The limited request.
        retry_after: Seconds until the visitor's window resets, if known.
        tier: The rate-limit tier that was exceeded, if known. For the media
            tier the page asks bulk collectors to contact us instead.

    Returns:
        A JsonResponse ({"ok": false, "error": "rate_limited", ...}) for API/AJAX
        callers, otherwise the rendered 429.html page. Status 429 either way.
    """
    retry_after = retry_after if retry_after and retry_after > 0 else None

    if _wants_json(request):
        body = {"ok": False, "error": "rate_limited"}
        if retry_after:
            body["retry_after"] = retry_after
        if tier in BULK_ACCESS_TIERS:
            body["contact"] = settings.BONKVERSE_DISCORD_URL
        response = JsonResponse(body, status=429)
    else:
        response = render(
            request,
            "429.html",
            {
                "wait": _describe_wait(retry_after),
                "retry_after": retry_after,
                # Reloading after a POST would make the browser resubmit the form
                # (e.g. a login), so only page views reload themselves.
                "auto_reload": request.method in ("GET", "HEAD"),
                "bulk_access": tier in BULK_ACCESS_TIERS,
                "discord_url": settings.BONKVERSE_DISCORD_URL,
            },
            status=429,
        )

    if retry_after:
        response["Retry-After"] = str(retry_after)
    return response


def ratelimited_view(request, exception):
    """settings.RATELIMIT_VIEW: the same 429 for views still on the old @ratelimit decorator."""
    logger.info("rate limited (legacy decorator): path=%s", request.path)
    return too_many_requests(request)
