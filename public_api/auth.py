"""Who is calling the public API, and how much they may call it.

Owns: reading the key from `Authorization: Bearer bvk_...`, the 401 replies,
per-key rate limits (with RateLimit-* headers on every reply), slowing down
key guessing by IP, and recording when a key was last used.
Does not own: the key format or storage (keys.py), the reply envelope
(responses.py) or what each endpoint returns (views.py).

Sessions and cookies are never used here: a browser that is signed in to
bonkverse.io gets no special access, so these views don't need CSRF.
"""

from __future__ import annotations

import functools
import logging

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit import ALL
from django_ratelimit.core import get_usage

from core.client_ip import client_ip

from .keys import find_active_key
from .models import ApiKey
from .responses import fail

logger = logging.getLogger(__name__)

# Failed key checks allowed per IP before that IP gets 429s for a while.
AUTH_FAIL_TIER = "api_auth_fail"
LAST_USED_WRITE_SECONDS = 60


def _rate_tier(tier: str, api_key: ApiKey) -> str:
    """The settings.RATE_LIMITS entry for this key: partner keys get the
    "<tier>_partner" rate when one is set."""
    if api_key.tier == ApiKey.TIER_PARTNER and f"{tier}_partner" in settings.RATE_LIMITS:
        return f"{tier}_partner"
    return tier


def _usage(request, group, bucket, tier, *, increment):
    """django-ratelimit usage for one bucket, or None if the cache is down
    (requests then go through: fail open, as everywhere else, ADR 0003)."""
    return get_usage(
        request,
        group=group,
        key=lambda _group, _request: bucket,
        rate=settings.RATE_LIMITS[tier],
        method=ALL,
        increment=increment,
    )


def _presented_key(request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _touch(api_key: ApiKey):
    """Save last_used_at at most once a minute per key."""
    if cache.add(f"public_api:touched:{api_key.pk}", 1, LAST_USED_WRITE_SECONDS):
        ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())


def _with_rate_headers(response, usage):
    if usage is not None:
        response["RateLimit-Limit"] = str(usage["limit"])
        response["RateLimit-Remaining"] = str(max(usage["limit"] - usage["count"], 0))
        response["RateLimit-Reset"] = str(usage["time_left"])
    return response


def _too_many(usage):
    # At least 1 second: right at the end of a window time_left can be 0, and
    # a 429 must still say when to try again (was a flaky test, 2026-11-09).
    wait = max(int(usage.get("time_left") or 0), 1)
    response = fail("rate_limited", 429, retry_after=wait)
    response["Retry-After"] = str(wait)
    return response


def api_endpoint(tier: str, *, methods=("GET",)):
    """Make a view a public API endpoint.

    Args:
        tier: Key in settings.RATE_LIMITS for this endpoint ("api",
            "api_bulk"). Counted per API key, not per IP. Partner keys use
            "<tier>_partner" when it exists.
        methods: Allowed HTTP methods; others get 405 method_not_allowed.

    The view is called with request.api_key set to the caller's ApiKey.

    Raises:
        ImproperlyConfigured: At import time, if a tier does not exist.
    """
    for name in (tier, AUTH_FAIL_TIER):
        if name not in settings.RATE_LIMITS:
            raise ImproperlyConfigured(f"Unknown rate-limit tier {name!r}")

    def decorator(view):
        group = f"public_api:{view.__module__}.{view.__qualname__}"

        @csrf_exempt
        @functools.wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                response = fail("method_not_allowed", 405)
                response["Allow"] = ", ".join(methods)
                return response

            ip_bucket = f"ip:{client_ip(request)}"
            # Peek without counting: only failures count, and once this IP has
            # used up its failures it waits, even with a good key.
            fails = _usage(request, AUTH_FAIL_TIER, ip_bucket, AUTH_FAIL_TIER, increment=False)
            if fails is not None and fails["count"] >= fails["limit"]:
                return _too_many(fails)

            raw = _presented_key(request)
            api_key = find_active_key(raw) if raw else None
            if api_key is None:
                _usage(request, AUTH_FAIL_TIER, ip_bucket, AUTH_FAIL_TIER, increment=True)
                code = "missing_api_key" if raw is None else "invalid_api_key"
                logger.info("public api: %s path=%s", code, request.path)
                response = fail(code, 401, auth="api_key")
                response["WWW-Authenticate"] = 'Bearer realm="bonkverse"'
                return response

            rate_tier = _rate_tier(tier, api_key)
            usage = _usage(request, group, f"key:{api_key.pk}", rate_tier, increment=True)
            if usage is not None and usage["should_limit"]:
                logger.info(
                    "public api: rate limited key=bvk_%s tier=%s", api_key.prefix, rate_tier
                )
                return _with_rate_headers(_too_many(usage), usage)

            _touch(api_key)
            request.api_key = api_key
            response = view(request, *args, **kwargs)
            logger.info(
                "public api: key=bvk_%s %s %s -> %s",
                api_key.prefix,
                request.method,
                request.path,
                response.status_code,
            )
            return _with_rate_headers(response, usage)

        # Read by `manage.py audit_rate_limits` and the every-route-has-a-tier test.
        wrapped.rate_limit_tier = tier
        wrapped.rate_limit_method = ",".join(methods)
        return wrapped

    return decorator
