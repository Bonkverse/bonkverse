"""Frontend structure rules from RFC-0001 Phase 3, checked on the source and
on rendered pages.

- Requests from page scripts go through static/core/js/bv-api.js: no page
  defines its own getCSRF/postForm or reads the CSRF cookie itself.
- Wearing and the bonk.io login go through static/core/js/bv-wear.js and the
  one modal partial: three copies of that flow are how the reappearing-modal
  bug hid for weeks.
- Skin cards come from two partials (_skin_card.html, _skin_card_compact.html)
  and behave through static/core/js/bv-cards.js: no page writes its own card
  or wires its own card buttons.
"""

import re
from pathlib import Path

import pytest

from tests.factories import SkinFactory

REPO = Path(__file__).resolve().parent.parent
TEMPLATES = REPO / "skins" / "templates"
STATIC_JS = REPO / "skins" / "static"
SHARED = {
    STATIC_JS / "core" / "js" / "bv-api.js",
    STATIC_JS / "core" / "js" / "bv-wear.js",
    STATIC_JS / "core" / "js" / "bv-cards.js",
}
PARTIALS = TEMPLATES / "skins" / "partials"
CARD_PARTIALS = {PARTIALS / "_skin_card.html", PARTIALS / "_skin_card_compact.html"}

# Card markup: an element whose class list names a piece of the card.
CARD_MARKUP = re.compile(r'class="[^"]*\b(skin-card|skin-tile|card-more-dropdown|vote-row)\b[^"]*"')
# Card behavior: a script selecting the card's buttons or image.
CARD_BEHAVIOR = re.compile(
    r"""['"`][^'"`]*\.(card-more-btn|wear-card-action|vote-up|vote-down|fav-toggle|skin-card-img)\b"""
)
MODAL_PARTIAL = TEMPLATES / "skins" / "partials" / "_bonk_login_modal.html"

# Helpers only bv-api.js may define, and the cookie only it may read.
FORBIDDEN = [
    (
        re.compile(r"function\s+(getCSRF|getCookie|postForm|postFormNoRedirect)\b"),
        "own fetch helper",
    ),
    (re.compile(r"bv_csrftoken"), "reads the CSRF cookie directly"),
    (
        re.compile(r"bonk_login_for_wear|bonkLoginForm|doBonkLogin|openBonkLogin"),
        "own bonk.io login",
    ),
]


def _page_sources():
    for path in [*TEMPLATES.rglob("*.html"), *STATIC_JS.rglob("*.js")]:
        if path in SHARED or path.name.endswith(".min.js"):
            continue
        yield path


def test_no_page_has_its_own_request_or_bonk_login_helpers():
    found = []
    for path in _page_sources():
        text = path.read_text(encoding="utf-8")
        for pattern, why in FORBIDDEN:
            if path == MODAL_PARTIAL and why == "own bonk.io login":
                continue  # the partial holds the login URL for bv-wear.js
            for match in pattern.finditer(text):
                found.append(f"{path.relative_to(REPO)}: {why} ({match.group(0)})")
    assert found == [], "use BVApi / BVWear (static/core/js/) instead:\n" + "\n".join(found)


def test_only_the_partial_defines_the_bonk_login_modal():
    defining = [
        path.relative_to(REPO).as_posix()
        for path in TEMPLATES.rglob("*.html")
        if 'id="bonk-login-modal"' in path.read_text(encoding="utf-8")
    ]
    assert defining == ["skins/templates/skins/partials/_bonk_login_modal.html"]


@pytest.mark.django_db
@pytest.mark.parametrize("page", ["/search/", "DETAIL", "/my-profile/"])
def test_pages_with_wear_have_one_modal_and_the_shared_scripts(logged_in_client, page):
    skin = SkinFactory()
    url = f"/skins/detail/{skin.id}" if page == "DETAIL" else page

    html = logged_in_client.get(url).content.decode()

    assert html.count('id="bonk-login-modal"') == 1
    assert "data-login-url=" in html
    assert "core/js/bv-api" in html
    assert "core/js/bv-wear" in html


@pytest.mark.django_db
def test_modal_points_at_the_wear_login_endpoint(logged_in_client):
    from django.urls import reverse

    html = logged_in_client.get("/search/").content.decode()

    assert f'data-login-url="{reverse("bonk_login_for_wear")}"' in html


def test_only_the_card_partials_write_card_markup():
    found = [
        f"{path.relative_to(REPO)}: {m.group(0)}"
        for path in TEMPLATES.rglob("*.html")
        if path not in CARD_PARTIALS
        for m in CARD_MARKUP.finditer(path.read_text(encoding="utf-8"))
    ]
    assert found == [], (
        "include skins/partials/_skin_card.html or _skin_card_compact.html instead:\n"
        + "\n".join(found)
    )


def test_only_bv_cards_wires_card_buttons():
    found = [
        f"{path.relative_to(REPO)}: {m.group(0)}"
        for path in _page_sources()
        for m in CARD_BEHAVIOR.finditer(path.read_text(encoding="utf-8"))
    ]
    assert found == [], "card behavior belongs in static/core/js/bv-cards.js:\n" + "\n".join(found)


@pytest.mark.django_db
@pytest.mark.parametrize("page", ["/search/", "/my-profile/", "/new/"])
def test_card_pages_load_bv_cards(logged_in_client, page):
    SkinFactory()

    html = logged_in_client.get(page).content.decode()

    assert "core/js/bv-cards" in html


@pytest.mark.django_db
def test_search_card_shows_the_visitors_vote_and_favorite(logged_in_client, user):
    from skins.models import SkinVote

    skin = SkinFactory(name="Votedskin")
    SkinVote.objects.create(user=user, skin=skin, vote="down")
    user.favorite_skins.add(skin)

    html = logged_in_client.get("/search/").content.decode()

    assert 'class="vote-down active"' in html
    assert 'class="vote-up active"' not in html
    assert 'class="fav-toggle active"' in html
