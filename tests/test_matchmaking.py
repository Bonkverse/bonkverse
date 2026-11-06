"""Join-matchmaking pass-through (skins/bonkbot.py) and the removed leaderboards.

join-matchmaking used to answer GET with a crash (the view returned None),
had no timeout on the BonkBot call and no rate limit, and echoed exception
text to the caller.
"""

import pytest
import requests


URL = "/api/join-matchmaking/"
BONKBOT_JOIN_URL = "https://bonkbot-api-production.up.railway.app/join-matchmaking"

pytestmark = pytest.mark.django_db


def _post(client, body='{"username": "TestPlayer"}'):
    return client.post(URL, data=body, content_type="application/json")


def test_get_is_not_allowed(client):
    """Regression: GET returned None from the view, a 500."""
    assert client.get(URL).status_code == 405


def test_relays_bonkbot_response_and_status(client, mocked_http):
    call = mocked_http.post(BONKBOT_JOIN_URL, json={"queued": True, "position": 3}, status=202)

    response = _post(client)

    assert response.status_code == 202
    assert response.json() == {"queued": True, "position": 3}
    assert call.calls[0].request.body == b'{"username": "TestPlayer"}'


def test_invalid_json_is_400(client, mocked_http):
    response = _post(client, body="not json")

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_json"}


@pytest.mark.parametrize(
    "failure",
    [requests.ConnectionError("boom: internal detail"), requests.Timeout("slow")],
    ids=["unreachable", "timeout"],
)
def test_bonkbot_failure_is_502_without_internal_details(client, mocked_http, failure):
    mocked_http.post(BONKBOT_JOIN_URL, body=failure)

    response = _post(client)

    assert response.status_code == 502
    assert response.json() == {"error": "matchmaking_unavailable"}


def test_bonkbot_non_json_reply_is_502(client, mocked_http):
    mocked_http.post(BONKBOT_JOIN_URL, body="<html>oops</html>", status=500)

    assert _post(client).status_code == 502


def test_bonkbot_call_has_a_timeout(client, mocked_http, monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(kwargs)
        raise requests.Timeout

    monkeypatch.setattr("integrations.bonkbot.requests.post", fake_post)

    _post(client)

    assert seen.get("timeout")


def test_is_rate_limited(client, mocked_http, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "write": "2/m"}
    mocked_http.post(BONKBOT_JOIN_URL, json={"queued": True})

    codes = [_post(client).status_code for _ in range(3)]

    assert codes == [200, 200, 429]


@pytest.mark.parametrize(
    "url",
    ["/leaderboards/wins/", "/leaderboards/losses/week/", "/leaderboards/winrate/all/"],
)
def test_win_loss_leaderboards_are_gone(client, url):
    """Removed in RFC-0001 Phase 1 (they crashed on every visit)."""
    assert client.get(url).status_code == 404


def test_nav_no_longer_links_to_win_loss_leaderboards(client):
    html = client.get("/").content.decode()

    assert "/leaderboards/wins/" not in html
    assert "Most Upvoted" in html
