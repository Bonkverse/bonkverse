"""Old share links (/skins/share/<id>/<uuid>/) are all over Discord. They go
to the one skin page, which has no generated description (design review
2026-11-09: descriptions stay as search data only)."""

import pytest

from tests.factories import SkinFactory

pytestmark = pytest.mark.django_db


def test_share_link_redirects_permanently_to_the_skin_page(client):
    skin = SkinFactory()

    response = client.get(f"/skins/share/{skin.id}/{skin.uuid}/")

    assert response.status_code == 301
    assert response["Location"] == skin.get_absolute_url()


def test_share_link_with_the_wrong_uuid_is_404(client):
    skin = SkinFactory()
    other = SkinFactory()

    assert client.get(f"/skins/share/{skin.id}/{other.uuid}/").status_code == 404


def test_skin_page_never_shows_the_generated_description(client):
    skin = SkinFactory(description="This design evokes a sense of whimsy and charm.")

    response = client.get(skin.get_absolute_url())

    assert "evokes a sense of whimsy" not in response.content.decode()
