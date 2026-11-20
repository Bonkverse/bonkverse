"""Per-key API usage: counting requests by day, and reading them back for the
key's usage page (/developers/keys/<prefix>/).

Owns: the ApiKeyUsageDay counters (one row per key, day and endpoint) and
the 30-day summary the page shows.
Does not own: rate limiting or the live "left this minute" numbers
(auth.py), or deleting old rows (tasks.py).

Counting never breaks the API: if the database write fails, the request is
still answered and the miss is logged (fail open, as the rate limits do,
ADR 0003).
"""

import logging
from datetime import date, timedelta

from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import F, Sum
from django.urls import URLPattern
from django.utils import timezone

from .models import ApiKeyUsageDay

logger = logging.getLogger(__name__)

# How many days of usage a key keeps, today included.
USAGE_DAYS = 30


def today() -> date:
    return timezone.now().date()  # UTC: TIME_ZONE is UTC


def record(api_key, endpoint: str, status: int) -> None:
    """Count one request with a valid key to `endpoint` (the view's name)
    that was answered with `status`."""
    limited = int(status == 429)
    error = int(status >= 400 and status != 429)
    day = today()
    try:
        rows = ApiKeyUsageDay.objects.filter(api_key=api_key, day=day, endpoint=endpoint)
        changes = dict(
            requests=F("requests") + 1,
            rate_limited=F("rate_limited") + limited,
            errors=F("errors") + error,
        )
        if rows.update(**changes):
            return
        try:
            with transaction.atomic():
                ApiKeyUsageDay.objects.create(
                    api_key=api_key,
                    day=day,
                    endpoint=endpoint,
                    requests=1,
                    rate_limited=limited,
                    errors=error,
                )
        except IntegrityError:
            # Another request made today's row first: count on it.
            rows.update(**changes)
    except DatabaseError:
        logger.exception("public api: usage not recorded key=bvk_%s", api_key.prefix)


def endpoints() -> list[dict]:
    """Every public API endpoint, in the order the docs list them:
    {"name": view name, "label": "GET /api/v1/…", "view": the view}."""
    from . import urls  # the URLconf imports the views, which import this module

    found = []
    for pattern in urls.urlpatterns:
        if not isinstance(pattern, URLPattern):
            continue
        view = pattern.callback
        path = str(pattern.pattern).replace("<username:username>", "{username}")
        method = getattr(view, "rate_limit_method", "GET").split(",")[0]
        found.append({"name": view.__name__, "label": f"{method} /api/v1/{path}", "view": view})
    return found


def summary(api_key) -> dict:
    """The key's last USAGE_DAYS days: totals, requests per day (oldest
    first, days without use included) and a row per endpoint used."""
    last = today()
    first = last - timedelta(days=USAGE_DAYS - 1)
    rows = ApiKeyUsageDay.objects.filter(api_key=api_key, day__gte=first)

    per_day = {row["day"]: row["n"] for row in rows.values("day").annotate(n=Sum("requests"))}
    days = [first + timedelta(days=i) for i in range(USAGE_DAYS)]
    busiest = max(per_day.values(), default=0)
    daily = [
        {
            "day": day,
            "requests": per_day.get(day, 0),
            # Bar height, out of 100; a day with any use shows at least a sliver.
            "height": round(per_day.get(day, 0) * 100 / busiest) if busiest else 0,
        }
        for day in days
    ]
    for entry in daily:
        if entry["requests"] and entry["height"] < 2:
            entry["height"] = 2

    by_endpoint = {
        row["endpoint"]: row
        for row in rows.values("endpoint").annotate(
            requests=Sum("requests"), rate_limited=Sum("rate_limited"), errors=Sum("errors")
        )
    }
    labels = {e["name"]: e["label"] for e in endpoints()}
    table = [
        {**row, "label": labels.get(name, name)}
        for name, row in sorted(by_endpoint.items(), key=lambda item: -item[1]["requests"])
    ]
    totals = {
        key: sum(row[key] for row in table) for key in ("requests", "rate_limited", "errors")
    }
    return {
        "first": first,
        "last": last,
        "days": USAGE_DAYS,
        "daily": daily,
        "busiest": busiest,
        "endpoints": table,
        "totals": totals,
    }


def prune(keep_days: int = USAGE_DAYS) -> int:
    """Delete usage older than the page shows. Returns the rows deleted."""
    cutoff = today() - timedelta(days=keep_days - 1)
    deleted, _ = ApiKeyUsageDay.objects.filter(day__lt=cutoff).delete()
    return deleted
