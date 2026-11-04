"""Tests for BonxBot skin submissions (skins/apis/bot_skins.py, skins/skin_import.py)."""

import base64
import json

import pytest
import responses

from skins.models import Skin, SkinImage, UserEvent
from skins.skin_import import clean_creator, clean_skin_name
from tests.factories import SkinFactory

pytestmark = pytest.mark.django_db

URL = "/api/bot/skins/"
FETCHER = "https://fetcher.test/api/getSkin"
TOKEN = "test-bot-token"
LINK = "https://bonkleagues.io/s/AbC1234"
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    '<rect width="10" height="10" fill="red"/></svg>'
)
PNG = b"\x89PNG fake"


@pytest.fixture(autouse=True)
def _bot_settings(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.BLSKIN_FETCHER_URL = FETCHER
    settings.BONXBOT_API_TOKEN = TOKEN


def _fetcher_replies(mocked_http, *, svg=SVG, status=200):
    body = {
        "skinCode": "CODE123",
        "media": {"svg": svg, "pngBase64": base64.b64encode(PNG).decode()},
    }
    mocked_http.add(responses.GET, FETCHER, json=body, status=status)


def _submit(client, token=TOKEN, **fields):
    data = {"link": LINK, "name": "Fire Dragon", "creator": "Some Artist", **fields}
    return client.post(
        URL,
        json.dumps(data),
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_creates_skin_with_images_and_discord_provenance(client, mocked_http, tmp_path):
    _fetcher_replies(mocked_http)

    response = _submit(client, discord_user_id=42, bonx_skin_id=7)

    assert response.status_code == 201
    skin = Skin.objects.get()
    assert (skin.name, skin.creator, skin.link, skin.skin_code) == (
        "Fire Dragon",
        "Some Artist",
        LINK,
        "CODE123",
    )
    assert response.json() == {
        "created": True,
        "skin": {
            "id": skin.id,
            "name": "Fire Dragon",
            "creator": "Some Artist",
            "url": skin.get_absolute_url(),
        },
    }
    assert sorted(SkinImage.objects.values_list("kind", flat=True)) == ["png", "svg", "thumbnail"]
    assert (tmp_path / f"skins/{skin.id}_thumb.png").read_bytes() == PNG  # falls back to the PNG
    event = UserEvent.objects.get(event_type="skin_uploaded")
    assert event.user is None
    assert event.metadata == {"source": "discord", "discord_user_id": 42, "bonx_skin_id": 7}


def test_same_link_again_returns_existing_skin_without_fetching(client, mocked_http):
    existing = SkinFactory(link=LINK)

    response = _submit(client)

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["skin"]["id"] == existing.id
    assert Skin.objects.count() == 1
    assert len(mocked_http.calls) == 0


@pytest.mark.parametrize("token", ["", "wrong-token"])
def test_rejects_missing_or_wrong_token(client, token):
    response = _submit(client, token=token)

    assert response.status_code == 401
    assert not Skin.objects.exists()


def test_refuses_everything_when_no_token_is_configured(client, settings):
    settings.BONXBOT_API_TOKEN = ""

    assert _submit(client, token="").status_code == 401


@pytest.mark.parametrize(
    "link",
    ["http://bonkleagues.io/s/AbC1234", "https://evil.example/s/AbC1234", "not a link", ""],
)
def test_non_bonkleagues_links_are_permanent_errors(client, link):
    response = _submit(client, link=link)

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_link", "retryable": False}


def test_link_longer_than_the_column_is_rejected_before_fetching(client, mocked_http):
    response = _submit(client, link=LINK + "?x=" + "a" * 300)

    assert response.status_code == 422
    assert response.json()["error"] == "link_too_long"
    assert len(mocked_http.calls) == 0


def test_fetcher_down_is_retryable_and_stores_nothing(client, mocked_http):
    _fetcher_replies(mocked_http, status=503)

    response = _submit(client)

    assert response.status_code == 502
    assert response.json() == {"error": "fetch_failed", "retryable": True}
    assert not Skin.objects.exists()


def test_unsafe_svg_is_rejected(client, mocked_http, tmp_path):
    _fetcher_replies(mocked_http, svg='<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>')

    response = _submit(client)

    assert response.status_code == 422
    assert response.json()["error"] == "unsafe_svg"
    assert not Skin.objects.exists()
    assert not (tmp_path / "skins").exists() or not any((tmp_path / "skins").iterdir())


def test_get_is_not_allowed(client):
    assert client.get(URL).status_code == 405


def test_bad_json_is_a_400(client):
    response = client.post(
        URL, "{nope", content_type="application/json", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("Fire🔥Dragon!!", "FireDragon"),
        ("  lots   of   space ", "lots of space"),
        ("snake_case 2", "snake_case 2"),
        ("🔥🔥", "UnnamedSkin"),
        (None, "UnnamedSkin"),
    ],
)
def test_clean_skin_name(raw, cleaned):
    assert clean_skin_name(raw) == cleaned


def test_clean_creator_keeps_spaces_but_fills_blanks():
    assert clean_creator(" Spaced  Name ") == " Spaced  Name "
    assert clean_creator("   ") == "UnknownSkinCreator"
    assert clean_creator(None) == "UnknownSkinCreator"
