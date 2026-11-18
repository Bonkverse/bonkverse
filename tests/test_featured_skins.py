"""Where Bonkverse puts a skin forward on its own: category covers, the home
carousels and the leaderboards (design review 2026-11-09, "Fix first").

Covers are hand-picked (CategoryCover), never the category's most upvoted
match, and a skin with an open report is left out of all three until staff
resolve the report. Search and the skin's own page still find it.
"""

import pytest
from django.contrib.admin.sites import site
from django.core.cache import cache

from skins.categories import category_tiles
from skins.models import CategoryCover, Skin, SkinReport
from skins.selectors import home_strips, top_skins
from tests.factories import CategoryCoverFactory, SkinFactory, SkinReportFactory

pytestmark = pytest.mark.django_db

ANIMAL = {"style": "", "themes": ["animal"], "objects": [], "references": [], "colors": []}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _tile(slug):
    return next(t for t in category_tiles() if t["slug"] == slug)


# ── Skin.objects.without_open_reports ────────────────────────────────


def test_open_reports_hide_a_skin_and_resolved_ones_dont():
    clean = SkinFactory()
    reported = SkinFactory()
    resolved = SkinFactory()
    SkinReportFactory(skin=reported)
    SkinReportFactory(skin=resolved, resolved=True)

    assert set(Skin.objects.without_open_reports()) == {clean, resolved}


# ── Category covers ───────────────────────────────────────────────────


def test_most_upvoted_match_is_never_the_cover_on_its_own():
    """The bug: the top-voted 'animal' skin (anything at all) became the cover."""
    SkinFactory(labels=ANIMAL, upvotes=999, image_url="/media/skins/top.png")

    assert _tile("animals")["cover"] is None


def test_the_hand_picked_skin_is_the_cover():
    SkinFactory(labels=ANIMAL, upvotes=999, image_url="/media/skins/top.png")
    pick = SkinFactory(image_url="/media/skins/pick.png")
    CategoryCoverFactory(category="animals", skin=pick)

    assert _tile("animals")["cover"] == "/media/skins/pick.png"


def test_a_reported_pick_leaves_the_tile_empty():
    pick = SkinFactory(image_url="/media/skins/pick.png")
    CategoryCoverFactory(category="animals", skin=pick)
    SkinReportFactory(skin=pick)

    assert _tile("animals")["cover"] is None


def test_a_new_pick_shows_without_waiting_for_the_cache():
    category_tiles()  # fills the hour-long count cache
    CategoryCoverFactory(category="animals", skin=SkinFactory(image_url="/media/skins/p.png"))

    assert _tile("animals")["cover"] == "/media/skins/p.png"


def test_categories_page_shows_the_pick(client):
    CategoryCoverFactory(category="animals", skin=SkinFactory(image_url="/media/skins/p.png"))

    html = client.get("/categories/").content.decode()

    assert 'src="/media/skins/p.png" alt="Animals"' in html


def test_admin_offers_only_real_categories():
    form_class = site._registry[CategoryCover].form
    choices = dict(form_class.base_fields["category"].choices)

    assert "animals" in choices and "nope" not in choices


# ── Home carousels and leaderboards ──────────────────────────────────


def test_home_carousels_leave_out_reported_skins():
    clean = SkinFactory(upvotes=1)
    reported = SkinFactory(upvotes=50)
    SkinReportFactory(skin=reported)

    for strip in home_strips().values():
        assert list(strip) == [clean]


def test_leaderboards_leave_out_reported_skins(client):
    clean = SkinFactory(upvotes=1)
    reported = SkinFactory(upvotes=50)
    SkinReportFactory(skin=reported)

    assert list(top_skins("upvotes", 10)) == [clean]
    assert list(top_skins("favorites", 10)) == [clean]
    assert reported.name not in client.get("/leaderboards/upvoted/").content.decode()


def test_search_and_the_skin_page_still_find_a_reported_skin(client):
    reported = SkinFactory(name="Zebra stripes")
    SkinReportFactory(skin=reported)

    assert client.get(reported.get_absolute_url()).status_code == 200
    assert "Zebra stripes" in client.get("/search/?q=Zebra&mode=name").content.decode()


def test_resolving_a_report_in_the_admin_brings_the_skin_back(admin_client):
    skin = SkinFactory()
    report = SkinReportFactory(skin=skin)

    admin_client.post(
        "/admin/skins/skinreport/",
        {"action": "resolve_reports", "_selected_action": [report.pk]},
    )

    assert SkinReport.objects.get(pk=report.pk).resolved
    assert list(top_skins("upvotes", 10)) == [skin]


@pytest.mark.parametrize(
    "url",
    ["/admin/skins/skinreport/", "/admin/skins/categorycover/", "/admin/skins/skin/"],
)
def test_admin_lists_show_the_skin_image(admin_client, url):
    skin = SkinFactory(image_url="/media/skins/look.png")
    SkinReportFactory(skin=skin)
    CategoryCoverFactory(skin=skin)

    html = admin_client.get(url).content.decode()

    assert 'src="/media/skins/look.png"' in html


def test_admin_report_page_previews_the_skin(admin_client):
    report = SkinReportFactory(skin=SkinFactory(image_url="/media/skins/look.png"))

    html = admin_client.get(f"/admin/skins/skinreport/{report.pk}/change/").content.decode()

    assert 'src="/media/skins/look.png"' in html and 'width="160"' in html
