"""The Map Decoder tool (site_pages/views/tools.py, integrations/map_decoder.py)."""

import json

import pytest
import requests

URL = "/api/tools/map-decode/"
DECODER = "https://decoder.test"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _decoder(settings):
    settings.DECODER_SERVICE_URL = DECODER
    settings.DECODER_SERVICE_KEY = "decoder-secret"


def _decode(client, encoded="ILAcJAhBFBjBzCIn"):
    return client.post(URL, {"encoded": encoded})


def test_returns_decoded_map_and_sends_key(client, mocked_http):
    call = mocked_http.post(f"{DECODER}/decode/map", json={"m": {"n": "Simple 1v1"}})

    response = _decode(client)

    assert response.status_code == 200
    assert response.json() == {"m": {"n": "Simple 1v1"}}
    request = call.calls[0].request
    assert request.headers["X-Decoder-Key"] == "decoder-secret"
    assert json.loads(request.body) == {"encoded": "ILAcJAhBFBjBzCIn"}


def test_bad_map_string_explains_what_the_decoder_said(client, mocked_http):
    mocked_http.post(f"{DECODER}/decode/map", json={"error": "not a valid map"}, status=422)

    response = _decode(client)

    assert response.status_code == 400
    assert response.json() == {
        "error": "Couldn't decode that map string.",
        "details": "not a valid map",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"body": requests.ConnectionError("down")},
        {"body": "Traceback (most recent call last): secret internals", "status": 500},
        {"json": {"error": "worker crashed at /srv/decoder.js:12"}, "status": 500},
    ],
)
def test_decoder_failure_shows_a_sentence_not_internals(client, mocked_http, kwargs):
    """Regression: the page used to get up to 2,000 characters of the
    decoder's raw reply, and its 5xx status passed straight through."""
    mocked_http.post(f"{DECODER}/decode/map", **kwargs)

    response = _decode(client)

    assert response.status_code == 502
    assert response.json() == {"error": "The map decoder isn't responding. Try again in a minute."}


def test_not_configured_is_503(client, mocked_http, settings):
    settings.DECODER_SERVICE_URL = ""

    response = _decode(client)

    assert response.status_code == 503
    assert len(mocked_http.calls) == 0


def test_empty_input_is_400(client, mocked_http):
    assert _decode(client, encoded="  ").status_code == 400
    assert len(mocked_http.calls) == 0
