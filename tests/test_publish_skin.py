"""Tests for publishing a skin from the editor (skins/apis/publish_skin.py)."""

import pytest

from skins.models import Skin
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/publish-skin/"
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    '<rect width="10" height="10" fill="red"/></svg>'
)


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def _publish(client, **extra):
    return client.post(URL, {"skin_name": "My Skin", "skin_code": "CODE", "svg": SVG, **extra})


def test_creator_name_is_never_trimmed(client):
    """Regression: the creator name was .strip()ped, so a bonk.io name with
    leading or trailing spaces (real names have them) was saved without."""
    client.force_login(UserFactory(username=" Spaced  Name "))

    response = _publish(client)

    assert response.status_code == 201
    assert Skin.objects.get().creator == " Spaced  Name "


def test_creator_field_in_form_is_ignored(client):
    client.force_login(UserFactory(username="RealCreator"))

    _publish(client, creator="Someone Else")

    assert Skin.objects.get().creator == "RealCreator"


def test_anonymous_cannot_publish(client):
    response = _publish(client)

    assert response.status_code == 401
    assert not Skin.objects.exists()


def test_oversized_svg_gets_a_size_message_not_unsafe(client):
    """A skin over the size limit is too detailed, not unsafe: say so."""
    client.force_login(UserFactory(username="BigSkinMaker"))
    padding = "<!--" + "x" * 2_000_000 + "-->"
    big_svg = SVG.replace("</svg>", padding + "</svg>")

    response = _publish(client, svg=big_svg)

    assert response.status_code == 422
    assert "too detailed" in response.json()["error"]
    assert "Unsafe" not in response.json()["error"]
    assert not Skin.objects.exists()
