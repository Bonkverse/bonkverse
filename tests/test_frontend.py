"""Frontend structure rules from RFC-0001 Phase 3, checked on the source and
on rendered pages.

- Requests from page scripts go through static/core/js/bv-api.js: no page
  defines its own getCSRF/postForm or reads the CSRF cookie itself.
- Wearing and the bonk.io login go through static/core/js/bv-wear.js and the
  one modal partial: three copies of that flow are how the reappearing-modal
  bug hid for weeks.
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
}
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
