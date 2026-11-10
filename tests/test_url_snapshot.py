"""Every public URL path, pinned, so moving code between apps can't change one.

RFC-0001 Phase 5 moves views, templates and URLs out of `skins/` into their
own apps. People, bots, the extension and old bookmarks use these paths, so a
move must keep every one of them. This test compares the URL conf against
`tests/fixtures/url_routes.json`:

- A path that disappears or changes fails the test. Moves must keep paths.
- A new path also fails until it is added to the file, so adding a route is
  always a visible, deliberate change.
- URL names are pinned too. A PR may rename them (for example to a
  namespaced name like `site_pages:privacy`) only together with every
  `{% url %}` and `reverse()` that uses them, and updates the file in the
  same PR, so the diff shows exactly which names changed.

To update the file after a deliberate change:

    python -m tests.test_url_snapshot > tests/fixtures/url_routes.json
"""

import json
from pathlib import Path

from django.urls import URLPattern, URLResolver, get_resolver

SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "url_routes.json"

# Django's own admin, static and media mounts are not ours to pin.
SKIP_PREFIXES = ("admin/", "^static/", "static/", "^media/")


def _walk(patterns, route_prefix="", name_prefix=""):
    for entry in patterns:
        route = route_prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            namespace = f"{name_prefix}{entry.namespace}:" if entry.namespace else name_prefix
            yield from _walk(entry.url_patterns, route, namespace)
        elif isinstance(entry, URLPattern):
            name = f"{name_prefix}{entry.name}" if entry.name else None
            yield route, name


def current_routes() -> list[dict]:
    """The URL conf as a sorted list of {route, name}, one entry per path."""
    routes = {}
    for route, name in _walk(get_resolver().url_patterns):
        if route.startswith(SKIP_PREFIXES):
            continue
        # The first match wins in Django, so a later duplicate never answers.
        routes.setdefault(route, name)
    return [{"route": route, "name": routes[route]} for route in sorted(routes)]


def _load_snapshot() -> list[dict]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_no_path_was_removed_or_changed():
    pinned = {entry["route"] for entry in _load_snapshot()}
    now = {entry["route"] for entry in current_routes()}

    missing = sorted(pinned - now)

    assert missing == [], "these URL paths no longer exist; moves must keep paths"


def test_new_paths_are_added_to_the_snapshot():
    pinned = {entry["route"] for entry in _load_snapshot()}
    now = {entry["route"] for entry in current_routes()}

    added = sorted(now - pinned)

    assert added == [], "new paths: add them to tests/fixtures/url_routes.json"


def test_url_names_match_the_snapshot():
    pinned = {entry["route"]: entry["name"] for entry in _load_snapshot()}
    now = {entry["route"]: entry["name"] for entry in current_routes()}

    renamed = {
        route: {"was": pinned[route], "now": now[route]}
        for route in pinned.keys() & now.keys()
        if pinned[route] != now[route]
    }

    assert renamed == {}, "URL names changed: update every use and the snapshot"


def test_snapshot_file_is_sorted_and_has_no_duplicates():
    routes = [entry["route"] for entry in _load_snapshot()]

    assert routes == sorted(set(routes))


if __name__ == "__main__":
    import os

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bonk_skin_search.settings")
    django.setup()
    print(json.dumps(current_routes(), indent=2))
