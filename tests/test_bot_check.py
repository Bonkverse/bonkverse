"""Tests for the "not a bot" check on bonk.io logins (accounts/bot_check.py,
integrations/turnstile.py). RFC-0003 Part 1, item 10.

Regression: on 2026-11-10 a bot logged in 10 new accounts 17 times in 100 s
from rotating IPs, which per-visitor limits can't stop, and bonk.io paused
logins for everyone. The check shows only when it's likely to matter, so most
players never see it.
"""

import pytest
import requests

from accounts import login_attempts
from accounts.login_attempts import BOT_CHECK
from integrations import turnstile
from tests.conftest import load_bonk_fixture

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
SITEVERIFY = turnstile.SITEVERIFY_URL
LOGIN_URL = "/login/"
WEAR_LOGIN_URL = "/api/bonk/login/"
SITE_KEY = "0x4AAAAAAGP08z9bSQTcL_Xu"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def turnstile_on(settings):
    settings.TURNSTILE_SITE_KEY = SITE_KEY
    settings.TURNSTILE_SECRET_KEY = "test-secret"
    # One person's tries in a row: no per-account cap in these tests.
    settings.BONK_LOGIN_LIMITS = {**settings.BONK_LOGIN_LIMITS, "account_per_minute": 0}


def _post_login(client, answer=None, ip="203.0.113.7", username="TestPlayer"):
    form = {"username": username, "password": "pw"}
    if answer is not None:
        form[turnstile.RESPONSE_FIELD] = answer
    return client.post(LOGIN_URL, form, REMOTE_ADDR=ip)


def _one_wrong_password(client, mocked_http):
    mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_wrong_password"))
    return _post_login(client)


class TestWhenItShows:
    def test_a_first_login_on_a_calm_site_never_sees_it(self, client, mocked_http):
        siteverify = mocked_http.post(SITEVERIFY, json={"success": True})
        bonk = mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        page = client.get(LOGIN_URL, REMOTE_ADDR="203.0.113.7")
        response = _post_login(client)

        assert page.context["turnstile_site_key"] is None
        assert b"cf-turnstile" not in page.content
        assert response.status_code == 302
        assert bonk.call_count == 1
        assert siteverify.call_count == 0

    def test_after_a_wrong_password_the_page_shows_it(self, client, mocked_http):
        response = _one_wrong_password(client, mocked_http)

        assert response.context["turnstile_site_key"] == SITE_KEY
        assert b'class="cf-turnstile' in response.content
        assert b"challenges.cloudflare.com/turnstile/v0/api.js" in response.content

    def test_after_a_wrong_password_on_the_site_everyone_sees_it(self, client, mocked_http):
        """One wrong password is one short of the site-wide budget of 2."""
        _one_wrong_password(client, mocked_http)

        page = client.get(LOGIN_URL, REMOTE_ADDR="198.51.100.40")

        assert page.context["turnstile_site_key"] == SITE_KEY

    def test_close_to_the_site_cap_it_shows(self, client, settings, monkeypatch):
        monkeypatch.setattr(login_attempts, "_now", lambda: 1_800_000_000.0)
        cap = settings.BONK_LOGIN_LIMITS["site_per_minute"]
        for _ in range(cap - 1):
            login_attempts._over_cap("site", cap)

        page = client.get(LOGIN_URL, REMOTE_ADDR="198.51.100.40")

        assert page.context["turnstile_site_key"] == SITE_KEY

    def test_off_without_a_secret(self, client, mocked_http, settings):
        settings.TURNSTILE_SECRET_KEY = ""
        response = _one_wrong_password(client, mocked_http)
        bonk = mocked_http.replace("POST", BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        again = _post_login(client)

        assert response.context["turnstile_site_key"] is None
        assert again.status_code == 302
        assert bonk.call_count == 1


class TestTheCheck:
    def test_without_an_answer_bonk_is_not_asked(self, client, mocked_http):
        _one_wrong_password(client, mocked_http)
        bonk = mocked_http.replace("POST", BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        response = _post_login(client)

        assert bonk.call_count == 0
        assert [str(m) for m in response.context["messages"]] == [
            "Bonk.io login failed: Confirm you're not a bot, then log in again."
        ]
        assert response.context["turnstile_site_key"] == SITE_KEY

    def test_a_genuine_answer_lets_the_login_through(self, client, mocked_http):
        _one_wrong_password(client, mocked_http)
        siteverify = mocked_http.post(SITEVERIFY, json={"success": True})
        bonk = mocked_http.replace("POST", BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        response = _post_login(client, answer="token-from-widget")

        assert response.status_code == 302
        assert bonk.call_count == 1
        body = siteverify.calls[0].request.body
        assert "secret=test-secret" in body and "response=token-from-widget" in body
        assert "remoteip=203.0.113.7" in body

    def test_a_rejected_answer_is_turned_away(self, client, mocked_http):
        _one_wrong_password(client, mocked_http)
        mocked_http.post(
            SITEVERIFY, json={"success": False, "error-codes": ["invalid-input-response"]}
        )
        bonk = mocked_http.replace("POST", BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        response = _post_login(client, answer="forged")

        assert bonk.call_count == 0
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "reply",
        [
            {"body": requests.ConnectionError("down")},
            {"body": "<html>oops</html>"},
            {"json": {"success": False, "error-codes": ["invalid-input-secret"]}},
        ],
        ids=["unreachable", "not_json", "our_secret_is_wrong"],
    )
    def test_when_cloudflare_cannot_judge_the_login_goes_ahead(self, client, mocked_http, reply):
        """The check is one guard of several; it must never lock everyone out."""
        _one_wrong_password(client, mocked_http)
        mocked_http.post(SITEVERIFY, **reply)
        bonk = mocked_http.replace("POST", BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        response = _post_login(client, answer="anything")

        assert bonk.call_count == 1
        assert response.status_code == 302


class TestWearPopup:
    def test_a_failed_popup_login_asks_for_the_check(self, logged_in_client, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_wrong_password"))

        response = logged_in_client.post(
            WEAR_LOGIN_URL, {"bonk_username": "TestPlayer", "bonk_password": "wrong"}
        )

        assert response.status_code == 401
        assert response.json()["bot_check"] == SITE_KEY

    def test_the_next_popup_login_needs_an_answer(self, logged_in_client, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_wrong_password"))
        form = {"bonk_username": "TestPlayer", "bonk_password": "pw"}
        logged_in_client.post(WEAR_LOGIN_URL, form)

        response = logged_in_client.post(WEAR_LOGIN_URL, form)

        assert response.json()["error"] == BOT_CHECK
        assert len([c for c in mocked_http.calls if "login_legacy" in c.request.url]) == 1


def test_an_empty_answer_is_refused_without_asking_cloudflare(mocked_http):
    result = turnstile.verify("secret", "")

    assert result.ok is False and result.unavailable is False
    assert len(mocked_http.calls) == 0
