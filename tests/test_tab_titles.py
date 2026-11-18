"""Browser tab titles: one format, "Page · Bonkverse" (design review
2026-11-09). Before, skin pages, leaderboards, Discord servers and the map
decoder all fell back to "Bonk.io Skin Search", which also showed in
bookmarks, history and link previews.

Every HTML page the URL conf serves is checked, so a new page that forgets
its {% block title %} fails here.
"""

import re

import pytest

from tests.test_smoke import ROUTES, _build_url

TITLE = re.compile(r"<title>(.*?)</title>", re.S)

pytestmark = pytest.mark.django_db


def _title(response):
    match = TITLE.search(response.content.decode())
    return " ".join(match.group(1).split()) if match else None


def _html_pages(client, skin):
    for route, entry in ROUTES:
        response = client.get(_build_url(route, entry, skin))
        if response.status_code == 200 and "text/html" in response.get("Content-Type", ""):
            title = _title(response)
            if title is not None:
                yield route, title


@pytest.mark.parametrize("as_user", [False, True], ids=["anon", "user"])
def test_every_page_title_names_bonkverse_last(client, user, skin, as_user):
    if as_user:
        client.force_login(user)

    pages = dict(_html_pages(client, skin))

    assert len(pages) >= 20  # the walker found the site's pages
    wrong = {
        route: title
        for route, title in pages.items()
        if title != "Bonkverse" and not title.endswith(" · Bonkverse")
    }
    assert wrong == {}


def test_nothing_is_called_bonk_io_skin_search(client, skin):
    titles = [title for _, title in _html_pages(client, skin)]

    assert not [t for t in titles if "Skin Search" in t]


def test_skin_page_title_names_the_skin_and_its_creator(client):
    from tests.factories import SkinFactory

    skin = SkinFactory(name="Bongo Cat", creator="Isabelle26")

    response = client.get(skin.get_absolute_url())

    assert _title(response) == "Bongo Cat by Isabelle26 · Bonkverse"
    assert '<meta property="og:title" content="Bongo Cat by Isabelle26 · Bonkverse">' in (
        response.content.decode()
    )


def test_search_title_shows_the_query(client):
    assert _title(client.get("/search/?q=cat")) == "“cat” · Skins · Bonkverse"
    assert _title(client.get("/search/")) == "Skins · Bonkverse"
