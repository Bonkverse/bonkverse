"""Tests for the Cloudflare cache purge client (integrations/cloudflare.py)."""

import json
import logging

import pytest
import requests

from integrations.cloudflare import MAX_FILES_PER_REQUEST, purge_files, purge_media_paths

ZONE = "zone123"
TOKEN = "cf-secret-token"
PURGE_URL = f"https://api.cloudflare.com/client/v4/zones/{ZONE}/purge_cache"


def test_sends_files_with_bearer_token(mocked_http):
    call = mocked_http.post(PURGE_URL, json={"success": True, "errors": []})

    result = purge_files(ZONE, TOKEN, ["https://bonkverse.io/media/skins/1.png"])

    assert result.ok is True
    request = call.calls[0].request
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.body) == {"files": ["https://bonkverse.io/media/skins/1.png"]}


@pytest.mark.parametrize("zone,token", [("", TOKEN), (ZONE, "")])
def test_skipped_when_not_configured(mocked_http, zone, token):
    result = purge_files(zone, token, ["https://bonkverse.io/x"])

    assert (result.ok, result.skipped) == (False, True)
    assert len(mocked_http.calls) == 0


def test_cloudflare_refusal_is_logged_without_the_token(mocked_http, caplog):
    """Regression: failures used to be swallowed by `except: pass`."""
    mocked_http.post(
        PURGE_URL,
        json={"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]},
        status=403,
    )

    with caplog.at_level(logging.WARNING, logger="integrations.cloudflare"):
        result = purge_files(ZONE, TOKEN, ["https://bonkverse.io/x"])

    assert (result.ok, result.error) == (False, "status_403")
    assert "cloudflare purge failed" in caplog.text
    assert "10000" in caplog.text
    assert TOKEN not in caplog.text


def test_unreachable_is_a_result_not_an_exception(mocked_http):
    mocked_http.post(PURGE_URL, body=requests.ConnectionError("down"))

    assert purge_files(ZONE, TOKEN, ["https://bonkverse.io/x"]).error == "unreachable"


def test_too_many_files_is_a_programming_error():
    with pytest.raises(ValueError):
        purge_files(ZONE, TOKEN, [f"https://bonkverse.io/{i}" for i in range(31)])
    assert MAX_FILES_PER_REQUEST == 30


def test_purge_media_paths_builds_urls_from_settings(settings, mocked_http):
    settings.CLOUDFLARE_ZONE_ID = ZONE
    settings.CLOUDFLARE_CACHE_API_TOKEN = TOKEN
    settings.BONKVERSE_BASE_URL = "https://staging.bonkverse.test"
    call = mocked_http.post(PURGE_URL, json={"success": True})

    purge_media_paths(["/media/skins/1.svg"])

    assert json.loads(call.calls[0].request.body) == {
        "files": ["https://staging.bonkverse.test/media/skins/1.svg"]
    }
