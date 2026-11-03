"""Smoke test: every route in the URL conf answers without a server error.

Each route is requested with GET, once anonymously and once as a logged-in
user. Any status is acceptable except a 5xx or an unhandled exception:
redirects, 401/403 auth responses, 404 for a missing object and 405 for
POST-only endpoints are all "the route is alive".

A new route needs nothing here; it is picked up automatically. If it has a
URL converter this file does not know how to fill, add it to `_fill_kwargs`.
"""

import pytest
from django.urls import URLPattern, URLResolver, get_resolver

# Routes that are not ours or cannot be smoke-tested meaningfully with GET.
SKIP_PREFIXES = ("admin/", "static/", "media/", "^static/", "^media/")

# Known crashes the RFC found. Each is fixed in Phase 1 with a regression test;
# `strict=True` makes the suite fail when the bug is fixed so the mark gets removed.
_RATELIMIT_BUG = (
    "RFC-0001 Phase 1: @ratelimit decorates _get_queryset(period), so it receives a str "
    "instead of a request",
    AttributeError,
)
KNOWN_BROKEN = {
    "leaderboards/wins/<str:period>/": _RATELIMIT_BUG,
    "leaderboards/wins/": _RATELIMIT_BUG,
    "leaderboards/losses/<str:period>/": _RATELIMIT_BUG,
    "leaderboards/losses/": _RATELIMIT_BUG,
    "leaderboards/winrate/<str:period>/": _RATELIMIT_BUG,
    "leaderboards/winrate/": _RATELIMIT_BUG,
    # Found by this smoke test: GET falls through and the view returns None.
    "api/join-matchmaking/": (
        "RFC-0001 Phase 1: join_matchmaking has no require_POST and returns None on GET",
        ValueError,
    ),
}


def _walk(patterns, prefix=""):
    for entry in patterns:
        route = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            yield from _walk(entry.url_patterns, route)
        elif isinstance(entry, URLPattern):
            yield route, entry


def _collect_routes():
    seen = set()
    for route, entry in _walk(get_resolver().url_patterns):
        if route.startswith(SKIP_PREFIXES) or route in seen:
            continue
        seen.add(route)
        yield route, entry


ROUTES = list(_collect_routes())


def _fill_kwargs(entry, skin) -> dict:
    """Pick a concrete value for every path converter in the route."""
    sample = {"int": skin.id, "uuid": skin.uuid, "slug": "minimalist", "string": "today"}
    kwargs = {}
    for name, converter in entry.pattern.converters.items():
        # IntConverter -> "int", StringConverter -> "string", UUIDConverter -> "uuid", ...
        type_name = type(converter).__name__.removesuffix("Converter").lower()
        if type_name not in sample:
            pytest.fail(f"Smoke test does not know how to fill <{type_name}:{name}>")
        kwargs[name] = sample[type_name]
    return kwargs


def _build_url(route: str, entry, skin) -> str:
    url = "/" + route
    for name, value in _fill_kwargs(entry, skin).items():
        # Swap "<conv:name>" for the value without depending on reverse(),
        # so unnamed routes are covered too.
        start = url.index("<")
        end = url.index(">", start)
        assert url[start:end].endswith(name), (route, name)
        url = url[:start] + str(value) + url[end + 1 :]
    return url


def _params():
    for route, entry in ROUTES:
        marks = []
        if route in KNOWN_BROKEN:
            reason, exc = KNOWN_BROKEN[route]
            # `raises=` makes sure it fails for the known reason, not a new one.
            marks.append(pytest.mark.xfail(reason=reason, raises=exc, strict=True))
        yield pytest.param(route, entry, id=route or "<root>", marks=marks)


@pytest.mark.django_db
@pytest.mark.parametrize("as_user", [False, True], ids=["anon", "user"])
@pytest.mark.parametrize("route,entry", list(_params()))
def test_route_does_not_500(client, user, skin, route, entry, as_user):
    if as_user:
        client.force_login(user)
    url = _build_url(route, entry, skin)

    response = client.get(url)

    assert response.status_code < 500, f"GET {url} -> {response.status_code}"


def test_smoke_covers_a_reasonable_number_of_routes():
    """Guard against the walker silently finding nothing."""
    assert len(ROUTES) >= 50


# Routes whose behavior depends on query parameters. Add a row when a bug is
# found that only appears with specific parameters.
QUERY_CASES = [
    pytest.param("/search/?q=abc&sort=newest", id="search-query-newest"),
    pytest.param("/search/?mode=creator&q=x", id="search-creator"),
    pytest.param(
        "/search/?sort=newest",
        id="search-empty-newest",
        marks=pytest.mark.xfail(
            reason="RFC-0001 Phase 1: empty query slices [:50] before order_by",
            raises=TypeError,
            strict=True,
        ),
    ),
]


@pytest.mark.django_db
@pytest.mark.parametrize("url", QUERY_CASES)
def test_query_variants_do_not_500(client, skin, url):
    response = client.get(url)

    assert response.status_code < 500, f"GET {url} -> {response.status_code}"
