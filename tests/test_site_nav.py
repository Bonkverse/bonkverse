"""The shared header and footer come from Bonkverse/ui's nav.json
(skins.context_processors.site_nav)."""

import json
from pathlib import Path

import pytest
from django.urls import Resolver404, resolve

NAV = json.loads((Path(__file__).resolve().parent.parent / "skins/static/ui/nav.json").read_text())


def _links():
    for item in NAV["header"]:
        yield from item.get("items", [item])
    yield from NAV["skinTabs"]
    yield from NAV["account"]["items"]
    for column in NAV["footer"]:
        yield from column["items"]


@pytest.mark.parametrize(
    "href", sorted({link["href"] for link in _links() if link["href"].startswith("/")})
)
def test_every_site_path_in_nav_json_exists(href):
    try:
        resolve(href)
    except Resolver404:
        pytest.fail(f"nav.json links to {href}, which this site doesn't serve")


@pytest.mark.django_db
def test_header_renders_every_nav_item(client):
    html = client.get("/").content.decode()
    for item in NAV["header"]:
        assert item["label"] in html
        for sub in item.get("items", []):
            assert sub["label"] in html


@pytest.mark.django_db
def test_other_sites_use_this_deployments_urls(client, settings):
    settings.BONKVERSE_REPLAYS_URL = "http://replays.local"
    html = client.get("/").content.decode()
    assert 'href="http://replays.local/"' in html
    assert "https://replays.bonkverse.io/" not in html


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path,current",
    [("/search/", "Skins"), ("/players/", "Players"), ("/developers/", "Developers")],
)
def test_current_section_is_highlighted(client, path, current):
    html = client.get(path).content.decode()
    assert f'aria-current="page">{current}</a>' in html


@pytest.mark.django_db
def test_skin_tabs_show_on_skin_pages_only(client):
    assert 'aria-label="Skins"' in client.get("/new/").content.decode()
    assert 'aria-label="Skins"' not in client.get("/players/").content.decode()


@pytest.mark.django_db
def test_signed_in_header_logs_out_with_a_post_form(logged_in_client):
    html = logged_in_client.get("/").content.decode()
    assert '<form method="post" action="/logout/">' in html
