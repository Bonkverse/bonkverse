"""Characterization tests for the bonk.io-backed login flow (skins/login.py).

These pin today's behavior so Phase 2 can move the bonk.io call into
integrations/bonk_api.py without changing what users see. bonk.io is always
faked with `responses`; see tests/fixtures/bonk/.
"""

import logging

import pytest
import requests
from django.urls import reverse

from skins.models import BonkAccountLink, BonkPlayer, BonkUser, UserEvent
from tests.conftest import load_bonk_fixture

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
LOGIN_URL = "/login/"

pytestmark = pytest.mark.django_db


def _post_login(client, username="TestPlayer", password="hunter2", **extra):
    return client.post(LOGIN_URL, {"username": username, "password": password, **extra})


class TestSuccessfulLogin:
    @pytest.fixture(autouse=True)
    def _bonk_accepts(self, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

    def test_redirects_to_profile(self, client):
        response = _post_login(client)

        assert response.status_code == 302
        assert response.url == reverse("my_profile")

    def test_logs_user_in_and_creates_site_account(self, client):
        _post_login(client)

        user = BonkUser.objects.get(username="TestPlayer")
        assert client.session["_auth_user_id"] == str(user.pk)
        assert UserEvent.objects.filter(user=user, event_type="user_logged_in").exists()

    def test_stores_bonk_session_from_response(self, client):
        _post_login(client)

        session = client.session
        assert session["bonk_token"] == "SCRUBBED-TEST-TOKEN-abc123"
        assert session["bonk_username"] == "TestPlayer"
        assert session["bonk_user_id"] == 1234567
        assert session["bonk_active_slot"] == 2
        assert session["bonk_token_expires"] > 0

    def test_never_stores_password_in_session(self, client):
        _post_login(client, password="hunter2")

        assert "hunter2" not in str(dict(client.session.items()))

    def test_links_site_account_to_bonk_player(self, client):
        _post_login(client)

        player = BonkPlayer.objects.get(bonk_id=1234567)
        assert player.username == "TestPlayer"
        link = BonkAccountLink.objects.get(user__username="TestPlayer", bonk_player=player)
        assert link.active is True
        # The token is stored signed, never raw.
        assert "SCRUBBED-TEST-TOKEN-abc123" not in link.token_encrypted

    def test_uses_username_returned_by_bonk_not_typed_one(self, client, mocked_http):
        # BONK: bonk.io returns the canonical username; it can differ from what was typed.
        mocked_http.replace(
            "POST",
            BONK_LOGIN_URL,
            json={**load_bonk_fixture("login_success"), "username": "Canonical Name"},
        )

        _post_login(client, username="canonical name")

        assert BonkUser.objects.filter(username="Canonical Name").exists()
        assert not BonkUser.objects.filter(username="canonical name").exists()

    def test_token_is_redacted_in_logs(self, client, caplog):
        with caplog.at_level(logging.DEBUG, logger="skins.login"):
            _post_login(client)

        assert "SCRUBBED-TEST-TOKEN-abc123" not in caplog.text
        assert "***REDACTED***" in caplog.text

    def test_follows_safe_next_url(self, client):
        response = _post_login(client, next="/categories/")

        assert response.url == "/categories/"

    def test_ignores_offsite_next_url(self, client):
        response = _post_login(client, next="https://evil.example.com/")

        assert response.url == reverse("my_profile")


class TestFailedLogin:
    def test_wrong_password_rerenders_form_without_logging_in(self, client, mocked_http):
        # BONK: login_legacy.php answers HTTP 200 even when the login fails.
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_wrong_password"))

        response = _post_login(client)

        assert response.status_code == 200
        assert "_auth_user_id" not in client.session
        assert "bonk_token" not in client.session
        assert not BonkUser.objects.exists()

    def test_network_error_shows_message_instead_of_500(self, client, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, body=requests.ConnectionError("bonk.io down"))

        response = _post_login(client)

        assert response.status_code == 200
        assert "_auth_user_id" not in client.session
        messages = [str(m) for m in response.context["messages"]]
        assert any("Network error" in m for m in messages)

    def test_non_json_response_is_handled(self, client, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, body="<html>Cloudflare challenge</html>", status=503)

        response = _post_login(client)

        assert response.status_code == 200
        assert "_auth_user_id" not in client.session


def test_login_page_renders(client):
    response = client.get(LOGIN_URL)

    assert response.status_code == 200


def test_logout_clears_bonk_session(bonk_session_client):
    response = bonk_session_client.get("/logout/")

    assert response.status_code == 302
    assert "bonk_token" not in bonk_session_client.session
    assert "_auth_user_id" not in bonk_session_client.session
