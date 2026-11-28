"""Who may edit and delete a skin (skins/views/my_skins.py).

Only the skin's creator, matched case-insensitively like bonk.io names
("The Saucy Tulip" and "the saucy tulip" are one account). Whoever submitted a
skin credited to someone else gets no rights over it.
"""

import json

import pytest

from skins.models import Skin
from tests.factories import SkinFactory, UserFactory

pytestmark = pytest.mark.django_db

AJAX = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
def tulip(client):
    user = UserFactory(username="The Saucy Tulip")
    client.force_login(user)
    return user


def _edit(client, skin, **fields):
    data = {"name": "Renamed", "tags": json.dumps([]), **fields}
    return client.post(f"/skin/{skin.id}/edit/", data, headers=AJAX)


def _delete(client, skin):
    return client.post(f"/skin/{skin.id}/delete/", headers=AJAX)


# --- the bug: edit and delete compared case-sensitively ----------------------


def test_creator_can_edit_when_credited_in_other_case(client, tulip):
    skin = SkinFactory(creator="the saucy tulip")

    response = _edit(client, skin)

    assert response.status_code == 200, response.content
    skin.refresh_from_db()
    assert skin.name == "Renamed"


def test_creator_can_delete_when_credited_in_other_case(client, tulip):
    skin = SkinFactory(creator="THE SAUCY TULIP")

    response = _delete(client, skin)

    assert response.json() == {"ok": True, "data": {"deleted_ids": [skin.id]}}
    assert not Skin.objects.filter(id=skin.id).exists()


# --- everyone else is refused --------------------------------------------------


def test_others_cannot_edit(client, tulip):
    skin = SkinFactory(creator="Somepoop", name="Reality.exe")

    response = _edit(client, skin)

    assert response.status_code == 403
    skin.refresh_from_db()
    assert skin.name == "Reality.exe"


def test_others_cannot_delete(client, tulip):
    skin = SkinFactory(creator="Somepoop")

    response = _delete(client, skin)

    assert response.status_code == 403
    assert Skin.objects.filter(id=skin.id).exists()


def test_submitter_of_someone_elses_skin_cannot_edit_or_delete(client, tulip):
    skin = SkinFactory(
        creator="Somepoop",
        submitted_by=tulip,
        submission_source="website",
        creator_source="bonkleagues",
    )

    assert _edit(client, skin).status_code == 403
    assert _delete(client, skin).status_code == 403
    assert Skin.objects.filter(id=skin.id).exists()


def test_spaces_still_matter(client, tulip):
    """bonk.io keeps spaces: " The Saucy Tulip" is a different account."""
    skin = SkinFactory(creator=" The Saucy Tulip")

    assert _delete(client, skin).status_code == 403


def test_delete_refuses_a_plain_visit(client, tulip):
    """A GET (a link or <img> on another site) must never delete anything."""
    skin = SkinFactory(creator="The Saucy Tulip")

    response = client.get(f"/skin/{skin.id}/delete/")

    assert response.status_code == 405
    assert Skin.objects.filter(id=skin.id).exists()


def test_bulk_delete_removes_only_own_skins(client, tulip):
    mine = SkinFactory(creator="the saucy tulip")
    theirs = SkinFactory(creator="Somepoop")

    response = client.post("/skins/bulk-delete/", {"skin_ids": [mine.id, theirs.id]}, headers=AJAX)

    assert response.json() == {"ok": True, "data": {"deleted_ids": [mine.id]}}
    assert list(Skin.objects.values_list("id", flat=True)) == [theirs.id]


# "ſ" (long s): casefold() makes it "s" (the old is_owned_by) and Postgres
# UPPER() makes it "S" (made_by, which bulk delete trusted on its own).
LOOKALIKE = "The \u017faucy Tulip"


def test_a_lookalike_name_cant_edit_or_delete_the_real_creators_skins(client):
    client.force_login(UserFactory(username=LOOKALIKE))
    skin = SkinFactory(creator="The Saucy Tulip", name="Hot Dog")

    assert _edit(client, skin).status_code == 403
    assert _delete(client, skin).status_code == 403
    bulk = client.post("/skins/bulk-delete/", {"skin_ids": [skin.id]}, headers=AJAX)

    assert bulk.json() == {"ok": True, "data": {"deleted_ids": []}}
    skin.refresh_from_db()
    assert skin.name == "Hot Dog"


def test_profile_skins_tab_lists_own_skins_in_any_case(client, tulip):
    SkinFactory(creator="the saucy tulip", name="Hot Dog")
    SkinFactory(creator="Somepoop", name="Reality.exe")

    response = client.get("/player/The Saucy Tulip/skins/")

    assert [s.name for s in response.context["page_obj"]] == ["Hot Dog"]


# --- the model and queryset helpers ------------------------------------------


def test_is_owned_by():
    user = UserFactory(username="The Saucy Tulip")

    assert SkinFactory(creator="the SAUCY tulip").is_owned_by(user)
    assert not SkinFactory(creator="Somepoop").is_owned_by(user)
    assert not SkinFactory(creator=None).is_owned_by(user)


def test_is_owned_by_anonymous_is_false(rf):
    from django.contrib.auth.models import AnonymousUser

    assert not SkinFactory(creator="").is_owned_by(AnonymousUser())


def test_made_by_ignores_case_but_not_spaces():
    match = SkinFactory(creator="the saucy tulip")
    SkinFactory(creator=" The Saucy Tulip")
    SkinFactory(creator="Somepoop")

    assert list(Skin.objects.made_by("The Saucy Tulip")) == [match]
