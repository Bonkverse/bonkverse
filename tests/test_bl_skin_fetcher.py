"""Tests for the BLSkinFetcher client (integrations/bl_skin_fetcher.py)."""

import base64

import pytest

from integrations.bl_skin_fetcher import fetch

FETCHER_URL = "https://fetcher.test/api/getSkin"
LINK = "https://bonkleagues.io/s/3BMOQWd"
PNG = b"\x89PNG fake"


def _reply(**overrides):
    """A successful /api/getSkin?media=true answer, as the service sends it."""
    body = {
        "name": "Reality.exe",
        "author": "Somepoop",
        "skinCode": "CgcDYQACCSEB",
        "finalUrl": "https://bonkleagues.io/skins.html#...",
        "media": {
            "svg": "<svg/>",
            "pngBase64": base64.b64encode(PNG).decode(),
        },
    }
    body.update(overrides)
    return body


def test_keeps_name_and_author_from_bonkleagues(mocked_http):
    mocked_http.get(FETCHER_URL, json=_reply())

    result = fetch(FETCHER_URL, LINK)

    assert result.error is None
    assert (result.skin.name, result.skin.author) == ("Reality.exe", "Somepoop")
    assert result.skin.skin_code == "CgcDYQACCSEB"
    assert result.skin.png == PNG
    assert result.skin.thumbnail == PNG  # no thumbnail sent: falls back to the PNG


@pytest.mark.parametrize("author", [None, "", "   ", 42])
def test_missing_or_blank_author_is_none(mocked_http, author):
    """BonkLeagues listings without "by <author>" come back as null; that is not an error."""
    mocked_http.get(FETCHER_URL, json=_reply(author=author))

    result = fetch(FETCHER_URL, LINK)

    assert result.error is None
    assert result.skin.author is None


def test_author_keeps_its_spaces(mocked_http):
    """bonk.io names can start or end with spaces (core/bonk/usernames.py), so they stay."""
    mocked_http.get(FETCHER_URL, json=_reply(author=" The Saucy Tulip "))

    assert fetch(FETCHER_URL, LINK).skin.author == " The Saucy Tulip "


def test_reply_without_name_or_author_still_imports(mocked_http):
    body = _reply()
    del body["name"], body["author"]
    mocked_http.get(FETCHER_URL, json=body)

    result = fetch(FETCHER_URL, LINK)

    assert result.error is None
    assert (result.skin.name, result.skin.author) == (None, None)


def test_sends_link_and_asks_for_media(mocked_http):
    call = mocked_http.get(FETCHER_URL, json=_reply())

    fetch(FETCHER_URL, LINK)

    params = call.calls[0].request.params
    assert params == {"link": LINK, "media": "true"}


def test_missing_media_is_an_error(mocked_http):
    mocked_http.get(FETCHER_URL, json=_reply(media={}))

    assert fetch(FETCHER_URL, LINK).error == "fetcher_missing_fields"


def test_bad_status_is_an_error(mocked_http):
    mocked_http.get(FETCHER_URL, json={"error": "Failed to extract skin"}, status=500)

    assert fetch(FETCHER_URL, LINK).error == "fetcher_status_500"
