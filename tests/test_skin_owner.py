"""Managing your own skins on your profile (design review: one profile).

The Skins tab shows the owner card (⋯ Edit, Copy link, Delete; Select) only
to the skin's owner; the edit endpoint takes a name and tags
(skins/editing.py); the friend-sync progress shows on the first page after
login wherever it landed (players/context_processors.py friend_sync).
"""

import json

import pytest

from skins import editing
from skins.models import Skin
from tests.factories import SkinFactory, UserFactory

pytestmark = pytest.mark.django_db

AJAX = {"X-Requested-With": "XMLHttpRequest"}
LABELS = {
    "style": "minimalistic",
    "colors": ["red"],
    "themes": ["cat", "animal"],
    "objects": ["Hat"],
    "references": ["meme"],
}


@pytest.fixture
def owner(client):
    user = UserFactory(username="Maker")
    client.force_login(user)
    return user


def _skins_tab(client, name="Maker", query=""):
    return client.get(f"/player/{name}/skins/{query}").content.decode()


# ── Who sees the owner tools ────────────────────────────────────────


def test_owner_gets_edit_delete_select_on_created(client, owner):
    SkinFactory(creator="Maker", labels=LABELS)

    html = _skins_tab(client)

    assert "data-skin-edit" in html and "data-skin-delete" in html
    assert 'id="skin-select-toggle"' in html
    assert "js/skin_owner.js" in html
    assert (
        'data-tags="[&quot;cat&quot;, &quot;animal&quot;, &quot;Hat&quot;, &quot;meme&quot;]"'
        in html
    )


def test_owner_favorites_view_is_the_normal_card(client, owner):
    SkinFactory(creator="Someone").favorited_by.add(owner)

    html = _skins_tab(client, query="?view=favorites")

    assert "data-skin-edit" not in html
    assert "skin_owner.js" not in html


@pytest.mark.parametrize("signed_in", [False, True])
def test_visitors_never_get_owner_tools(client, signed_in):
    UserFactory(username="Maker")
    SkinFactory(creator="Maker")
    if signed_in:
        client.force_login(UserFactory(username="Visitor"))

    html = _skins_tab(client)

    assert "data-skin-edit" not in html
    assert "skin-select-toggle" not in html
    assert "Upload a skin" not in html


def test_owner_header_has_upload_and_settings(client, owner):
    html = _skins_tab(client)

    assert 'href="/upload/"' in html
    assert 'href="/settings/profile/"' in html and "Profile settings</span>" in html


def test_owner_with_no_skins_is_offered_upload(client, owner):
    html = _skins_tab(client)

    assert "No skins yet." in html
    assert html.count('href="/upload/"') >= 2  # header and the empty state


# ── Editing: name and tags ──────────────────────────────────────────


def _edit(client, skin, name="New name", tags=()):
    return client.post(
        f"/skin/{skin.id}/edit/", {"name": name, "tags": json.dumps(list(tags))}, headers=AJAX
    )


def test_edit_renames_and_sets_tags_keeping_style_and_colors(client, owner):
    skin = SkinFactory(creator="Maker", labels=LABELS, description="AI words")

    response = _edit(client, skin, "  Cool   Cat ", ["Cat", "meme", "space"])

    assert response.json() == {
        "ok": True,
        "data": {"name": "Cool Cat", "tags": ["cat", "space", "meme"]},
    }
    skin.refresh_from_db()
    assert skin.name == "Cool Cat"
    assert skin.labels == {
        "style": "minimalistic",
        "colors": ["red"],
        "themes": ["cat", "space"],  # kept "cat", new "space" goes to themes
        "objects": [],  # "Hat" removed
        "references": ["meme"],
    }
    assert skin.description == "AI words"  # not edited any more, not cleared


@pytest.mark.parametrize(
    "name, tags, message",
    [
        ("   ", [], "Give the skin a name."),
        ("x" * 101, [], "Names can be up to 100 characters."),
        ("Ok", ["y" * 41], "Tags can be up to 40 characters."),
        ("Ok", [f"t{i}" for i in range(31)], "A skin can have up to 30 tags."),
    ],
)
def test_edit_refuses_bad_input_and_saves_nothing(client, owner, name, tags, message):
    skin = SkinFactory(creator="Maker", name="Before")

    response = _edit(client, skin, name, tags)

    assert response.status_code == 400
    assert response.json()["message"] == message
    skin.refresh_from_db()
    assert skin.name == "Before"


def test_edit_needs_sign_in_and_post(client):
    skin = SkinFactory(creator="Maker")

    assert _edit(client, skin).status_code == 401
    assert client.get(f"/skin/{skin.id}/edit/").status_code == 405


def test_tags_of_reads_themes_objects_references_once():
    skin = Skin(labels={"themes": ["Cat", "cat"], "objects": ["hat"], "references": "oops"})

    assert editing.tags_of(skin) == ["Cat", "hat"]


def test_bulk_delete_caps_how_many_at_once(client, owner):
    response = client.post("/skins/bulk-delete/", {"skin_ids": list(range(1, 102))}, headers=AJAX)

    assert response.status_code == 400
    assert response.json()["error"] == "too_many"


# ── After login: friend sync progress on the page you land on ──────


def test_friend_sync_progress_shows_once_on_the_next_page(client, owner):
    session = client.session
    session["show_friend_sync_toast"] = True
    session.save()

    first = client.get("/categories/").content.decode()
    second = client.get("/categories/").content.decode()

    assert 'id="bv-friend-sync" data-url="/api/friends-sync-status/"' in first
    assert "players/js/friend_sync.js" in first
    assert "bv-friend-sync" not in second
