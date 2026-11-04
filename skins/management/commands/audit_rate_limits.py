"""List every route with its rate-limit tier and current rate.

Read-only. The list is built from the URL conf and the @limit decorators, so it
always matches the code; the numbers come from settings.RATE_LIMITS (and any
RATE_LIMIT_<TIER> env overrides).

    python manage.py audit_rate_limits
    python manage.py audit_rate_limits --missing   # only routes without a tier
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import URLPattern, URLResolver, get_resolver

SKIP_PREFIXES = ("admin/", "static/", "^static/")


def _walk(patterns, prefix=""):
    for entry in patterns:
        route = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            yield from _walk(entry.url_patterns, route)
        elif isinstance(entry, URLPattern):
            yield route, entry.callback


def _method_label(method) -> str:
    if method is None or method == (None,):
        return "all"
    if isinstance(method, str):
        return method
    return ",".join(method)


def collect_rows():
    """Return (route, view, tier, rate, methods) for each route, tier None if untiered."""
    rows, seen = [], set()
    for route, callback in _walk(get_resolver().url_patterns):
        if route.startswith(SKIP_PREFIXES) or route in seen:
            continue
        seen.add(route)
        view = f"{callback.__module__}.{callback.__qualname__}"
        tier = getattr(callback, "rate_limit_tier", None)
        rate = settings.RATE_LIMITS.get(tier, "") if tier else ""
        methods = _method_label(getattr(callback, "rate_limit_method", None)) if tier else ""
        rows.append(("/" + route, view, tier, rate, methods))
    return rows


class Command(BaseCommand):
    help = "List every route with its rate-limit tier and current rate."

    def add_arguments(self, parser):
        parser.add_argument(
            "--missing", action="store_true", help="Only show routes that are not on a tier."
        )

    def handle(self, *args, missing=False, **options):
        rows = collect_rows()
        if missing:
            rows = [r for r in rows if r[2] is None]

        self.stdout.write(self.style.MIGRATE_HEADING("Tiers (settings.RATE_LIMITS)"))
        for tier, rate in settings.RATE_LIMITS.items():
            self.stdout.write(f"  {tier:<8} {rate}")
        self.stdout.write("")

        width = max((len(r[0]) for r in rows), default=10)
        self.stdout.write(self.style.MIGRATE_HEADING("Routes"))
        for route, view, tier, rate, methods in sorted(rows, key=lambda r: (r[2] is None, r[0])):
            if tier:
                limit_text = f"{tier:<8} {rate:<7} {methods:<5}"
            else:
                limit_text = self.style.WARNING(f"{'—':<8} {'':<7} {'':<5}")
            self.stdout.write(f"  {route:<{width}}  {limit_text}  {view}")

        untiered = sum(1 for r in rows if r[2] is None)
        self.stdout.write("")
        summary = f"{untiered} routes without a tier (old @ratelimit decorator, or no limit)."
        if not missing:
            summary = f"{len(rows) - untiered} routes on a tier, " + summary
        self.stdout.write(summary)
